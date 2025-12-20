import os
import sys

from src.utility.logger import get_logger

from src.core.mcp_server import MCPServer

logger = get_logger(__name__)


def main():
    """Starting the server.

    Google Drive credential is now provided per-request via X-Google-Credential header.
    Each user sets their own base64 encoded service account JSON in mcp.json headers.
    """
    mcp_server = MCPServer(
        name='Mindmup2 GDrive MCP Sever',
        host='0.0.0.0',
        port=9802
    )

    try:
        # MCP Client mode | stdio, sse, streamable-http
        transport = os.getenv('MCP_TRANSPORT', 'sse')
        logger.info(f'Starting server in {transport} mode.')
        logger.info('Credential is provided per-request via X-Google-Credential header.')
        mcp_server.start(transport=transport)

    except KeyboardInterrupt:
        logger.info('Server stopped by user.')
    except Exception as e:
        logger.error(f'Server error: {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()
