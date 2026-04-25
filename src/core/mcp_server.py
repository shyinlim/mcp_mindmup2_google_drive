import hashlib
import json
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from fastmcp.server.dependencies import get_http_headers
from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from src.core.gdrive_client import GoogleDriveClient
from src.core.gdrive_feature import GoogleDriveFeature
from src.core.mcp_read_tools import ReadToolsMixin
from src.core.mindmup_parser import MindmupParser
from src.utility.logger import get_logger

logger = get_logger(__name__)


class HealthCheckMiddleware:
    """Pure ASGI middleware: intercept GET /mcp without SSE Accept header.

    Claude Code health-checks MCP servers by sending GET /mcp with no
    Accept: text/event-stream header. FastMCP's streamable-http handler
    rejects this with 406 "Not Acceptable", causing Claude Code to mark
    the server as unhealthy. This middleware returns a simple 200 JSON
    response for that specific case, letting all other requests pass through.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get('path', '').rstrip('/')
        if scope['type'] != 'http' or scope['method'] != 'GET' or path != '/mcp':
            await self.app(scope, receive, send)
            return

        # Check if the request has Accept: text/event-stream (real SSE client)
        has_sse_accept = False
        for header_name, header_value in scope.get('headers', []):
            if header_name == b'accept' and b'text/event-stream' in header_value:
                has_sse_accept = True
                break

        if has_sse_accept:
            # Real SSE client — let FastMCP handle it
            await self.app(scope, receive, send)
            return

        # Health check probe (no SSE accept) — return 200 JSON
        response = JSONResponse({
            'status': 'ok',
            'message': 'MCP server is running. Use POST /mcp for MCP protocol.',
        })
        await response(scope, receive, send)


# Tool methods live in mcp_read_tools.py (ReadToolsMixin) to keep this file focused on infrastructure.
class MCPServer(ReadToolsMixin):

    def __init__(self, name: str, host: str, port: int):
        self.mcp = FastMCP(
            name=name,
            host=host,
            port=int(port)
        )
        self._setup_tool()
        self._setup_sse_route()
        self._inject_health_check_middleware()

    def _inject_health_check_middleware(self) -> None:
        """Wrap FastMCP's streamable_http_app so HealthCheckMiddleware is added.

        FastMCP builds the Starlette app lazily inside run(). We wrap the
        method so our middleware is injected right after the app is created,
        before Uvicorn starts serving.
        """
        original_method = self.mcp.streamable_http_app

        def patched() -> ASGIApp:
            app = original_method()
            app.add_middleware(HealthCheckMiddleware)
            return app

        self.mcp.streamable_http_app = patched

    @staticmethod
    def _attach_meta(response: Dict[str, Any]) -> Dict[str, Any]:
        """Attach _meta with estimated token usage to a response dict."""
        response_bytes = len(json.dumps(response, ensure_ascii=False).encode('utf-8'))
        response['_meta'] = {
            'response_bytes': response_bytes,
            'estimated_tokens': response_bytes // 3,
        }
        return response

    async def _get_gdrive_feature_from_header(self) -> GoogleDriveFeature:
        """Get GDrive feature from request header credential.

        Reads X-Google-Credential header (base64 encoded service account JSON),
        creates a new GoogleDriveClient, authenticates, and returns GoogleDriveFeature.

        Returns:
            GoogleDriveFeature instance authenticated with user's credential.

        Raises:
            ValueError: If header is missing or authentication fails.
        """
        headers = get_http_headers()
        credential_base64 = headers.get('x-google-credential')

        if not credential_base64:
            raise ValueError(
                "Missing X-Google-Credential header. "
                "Please set your base64 encoded service account JSON in mcp.json headers."
            )

        client_id = headers.get('x-client-id', 'default')
        if client_id == 'default':
            logger.warning(
                "X-Client-Id header not set. Using 'default' — cache may be "
                "shared with other clients using the same service account. "
                "Recommend setting X-Client-Id in mcp.json (e.g. 'shyin-claude-code')."
            )

        credential_hash = hashlib.sha256(credential_base64.encode()).hexdigest()[:16]

        client = GoogleDriveClient()
        auth_result = await client.authenticate_from_base64(credential_base64)

        if not auth_result.is_success:
            raise ValueError(f"Google Drive authentication failed: {auth_result.detail}")

        return GoogleDriveFeature(client, client_id=client_id, credential_hash=credential_hash)

    async def _find_file_by_name(self, gdrive_feature: GoogleDriveFeature, file_name: str) -> Optional[str]:
        """Find file ID by name. Returns None if not found."""
        mindmup_file = await gdrive_feature.search_mindmup_file(name_contain=file_name)
        if not mindmup_file:
            return None

        file_id = mindmup_file[0].id
        logger.info(f'Found file {mindmup_file[0].name} with ID {file_id}')
        return file_id

    async def _fetch_and_parse_mindmup(
            self, gdrive_feature: GoogleDriveFeature, file_id: str
    ) -> Tuple[Optional[Any], Optional[str], Dict[str, Any]]:
        """Download and parse mindmup file. Returns (mindmup, file_content, error_dict)."""
        # Download file
        download_result = await gdrive_feature.fetch_file_content(file_id=file_id)
        if not download_result.is_success:
            return None, None, {"error": download_result.detail}

        file_content = download_result.detail.get('content_str')
        if not file_content:
            return None, None, {"error": "No content in downloaded file."}

        # Parse mindmup
        try:
            mindmup = MindmupParser.parse_content(content=file_content)
            return mindmup, file_content, {}
        except Exception as e:
            return None, None, {"error": f"Parse error: {e}"}

    def _setup_tool(self):
        self.mcp.tool()(self.list_files)
        self.mcp.tool()(self.read_mindmap)
        self.mcp.tool()(self.search_mindmap)
        self.mcp.tool()(self.get_mindmap_section)

    def _setup_sse_route(self):
        @self.mcp.custom_route(path='/ping', methods=['GET'])
        async def ping_endpoint(request):
            """HTTP ping endpoint for SSE make sure keep-alive."""
            return JSONResponse({
                "result": "success",
                "time": datetime.now().isoformat(),
                "client_ip": request.client.host,
            })

        @self.mcp.custom_route(path='/health', methods=['GET'])
        async def health_check(request):
            """Health check endpoint."""
            return JSONResponse({
                "result": "success",
                "time": datetime.now().isoformat(),
                "message": "MCP server is running. Credential is provided per-request via X-Google-Credential header."
            })

    def start(self, transport: str = 'sse'):
        """For starting MCP Sever. 'run.py' will call this function."""
        self.mcp.run(transport=transport)
