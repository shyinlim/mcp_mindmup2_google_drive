from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from mcp.server.fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from src.model.gdrive_model import SearchQuery
from src.utility.logger import get_logger
from starlette.responses import JSONResponse

from src.core.gdrive_client import GoogleDriveClient
from src.core.gdrive_feature import GoogleDriveFeature
from src.core.mindmup_parser import MindmupParser

logger = get_logger(__name__)


class MCPServer:

    def __init__(self, name: str, host: str, port: int):
        self.mcp = FastMCP(
            name=name,
            host=host,
            port=int(port)
        )
        self._setup_tool()
        self._setup_sse_route()

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

        # Create new client and authenticate
        client = GoogleDriveClient()
        auth_result = await client.authenticate_from_base64(credential_base64)

        if not auth_result.is_success:
            raise ValueError(f"Google Drive authentication failed: {auth_result.detail}")

        return GoogleDriveFeature(client)

    async def _find_file_by_name(self, gdrive_feature: GoogleDriveFeature, file_name: str) -> Optional[str]:
        """Find file ID by name. Returns None if not found."""
        mindmup_file = await gdrive_feature.search_mindmup_file(name_contain=file_name)
        if not mindmup_file:
            return None

        file_id = mindmup_file[0].id
        logger.info(f'Found file {mindmup_file[0].name} with ID {file_id}')
        return file_id

    async def _download_and_parse_mindmup(
            self, gdrive_feature: GoogleDriveFeature, file_id: str
    ) -> Tuple[Optional[Any], Optional[str], Dict[str, Any]]:
        """Download and parse mindmup file. Returns (mindmup, file_content, error_dict)."""
        # Download file
        download_result = await gdrive_feature.download_file_content(file_id=file_id)
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

    async def _process_mindmup_content(self, file_id: str, file_content: str) -> Dict[str, Any]:
        """Process mindmup content with size-based handling.

        Returns different content types based on size:
        - full: < 800KB, returns complete content
        - structured: 800KB - 1MB, returns structured summary
        - chunked: > 800KB text, returns chunk metadata for pagination
        """
        try:
            mindmup = MindmupParser.parse_content(content=file_content)
        except Exception as e:
            return {"error": f"Mindmup parse error: {e}"}

        # Extract text content
        all_text_list = mindmup.extract_text_content()
        all_text = ' '.join(all_text_list) if all_text_list else ''
        content_length = len(all_text)

        # Base result (common fields)
        result = {
            "title": mindmup.title,
            "id": mindmup.id,
            "format_version": mindmup.format_version,
            "node_count": mindmup.get_node_count(),
            "original_content_length": content_length,
            "metadata": {
                "created_time": mindmup.created_time.isoformat() if mindmup.created_time else None,
                "modified_time": mindmup.modified_time.isoformat() if mindmup.modified_time else None,
                "author": mindmup.author
            }
        }

        # Large content (> 800KB): use chunked approach
        if content_length > 800 * 1024:
            chunk_list = MindmupParser.split_content_to_chunk(all_text)
            result["content_type"] = "chunked"
            result["total_chunk"] = len(chunk_list)
            result["chunk_metadata"] = [
                {
                    "chunk_index": c["chunk_index"],
                    "total_chunk": c["total_chunk"],
                    "start_pos": c["start_pos"],
                    "end_pos": c["end_pos"],
                    "size": len(c["content"])
                }
                for c in chunk_list
            ]
            result["structured_overview"] = MindmupParser.extract_mindmap_structure(mindmup)

        # Medium content (800KB - 1MB): use structured extraction
        elif content_length > MindmupParser.CLAUDE_MAX_CONTENT_LENGTH:
            result["content_type"] = "structured"
            result["structured_content"] = MindmupParser.extract_mindmap_structure(mindmup)

        # Small content (< 800KB): return full content
        else:
            result["content_type"] = "full"
            result["root_node"] = mindmup.root_node.to_dict()
            result["all_text_content"] = all_text

        return result

    async def gdrive_tool_list_file(
            self, max_result: int = 1000, file_type: Optional[str] = None,
            name_contain: Optional[str] = None) -> Dict[str, Any]:
        """List out Gdrive file list."""
        try:
            gdrive_feature = await self._get_gdrive_feature_from_header()

            query = SearchQuery(
                max_result=max_result,
                mime_type=[file_type] if file_type else [],
                name_contain=name_contain
            )
            result = await gdrive_feature.list_file(query=query)

            if not result.is_success:
                return {"error": result.detail}

            return result.detail

        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            error_message = f'gdrive_tool_list_file error: {e}'
            logger.error(error_message)
            return {"error": error_message}

    async def get_single_mindmup_tool(
            self, file_id: Optional[str] = None, file_name: Optional[str] = None) -> Dict[str, Any]:
        """Get single mindmup content - Using file id or file name.

        Args:
            file_id: Direct file ID to download.
            file_name: File name to search for (will use the first match).
        """
        if not file_id and not file_name:
            return {"error": "Either file_id or file_name must be provided."}

        try:
            gdrive_feature = await self._get_gdrive_feature_from_header()

            # If file_name is provided, search for the file first
            if file_name and not file_id:
                file_id = await self._find_file_by_name(gdrive_feature, file_name)
                if not file_id:
                    return {"error": f"No MindMup file found with name containing '{file_name}'."}

            # Check file metadata first
            file_metadata = await gdrive_feature.get_file_metadata(file_id)
            file_size = 0
            if file_metadata and 'size' in file_metadata:
                file_size = int(file_metadata.get('size', 0))
                logger.info(f'File {file_id} size: {file_size} bytes ({round(file_size / (1024 * 1024), 2)} MB)')

            # Download and parse
            mindmup, file_content, error = await self._download_and_parse_mindmup(gdrive_feature, file_id)
            if error:
                return error

            # Process mindmup content
            mindmap_data = await self._process_mindmup_content(file_id, file_content)
            if "error" in mindmap_data:
                return mindmap_data

            # Add file size info if available
            if file_size > 0:
                mindmap_data["file_size_mb"] = round(file_size / (1024 * 1024), 2)

            # If content is chunked, return partial status to guide AI to continue reading
            if mindmap_data.get("content_type") == "chunked":
                total_chunks = mindmap_data.get('total_chunk', 1)
                return {
                    "status": "partial",
                    "message": f"File too large for single response. This is the structure overview. Use next_action to read full content.",
                    "current_chunk": 0,
                    "total_chunks": total_chunks,
                    "file_id": file_id,
                    "file_size_mb": mindmap_data.get("file_size_mb"),
                    "node_count": mindmap_data.get("node_count"),
                    "content": mindmap_data.get("structured_overview"),
                    "next_action": f"Call get_mindmup_chunk_tool(file_id='{file_id}', chunk_index=0) to get chunk 1/{total_chunks}"
                }

            # If content is structured (medium size), also return partial with guidance
            if mindmap_data.get("content_type") == "structured":
                return {
                    "status": "partial",
                    "message": "File is medium size. Returning structured summary. Use next_action to read full content.",
                    "file_id": file_id,
                    "file_size_mb": mindmap_data.get("file_size_mb"),
                    "node_count": mindmap_data.get("node_count"),
                    "content": mindmap_data.get("structured_content"),
                    "next_action": f"Call get_mindmup_chunk_tool(file_id='{file_id}', chunk_index=0) to get full content"
                }

            # Content is complete (small file)
            return {
                "status": "complete",
                "file_id": file_id,
                "mindmap": mindmap_data
            }

        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            error_message = f'get_single_mindmup_tool error: {e}'
            logger.error(error_message)
            return {"error": error_message}

    async def analyze_mindmup_summary_tool(
            self, file_name: Optional[str] = None, file_id: Optional[str] = None) -> Dict[str, Any]:
        """Analyze and provide comprehensive summary for mindmup file.

        Returns complete overview including all section titles and chunk previews,
        so AI can understand full content scope before reading specific chunks.

        Args:
            file_name: File name to search for.
            file_id: Direct file ID.
        """
        if not file_id and not file_name:
            return {"error": "Either file_id or file_name must be provided."}

        try:
            gdrive_feature = await self._get_gdrive_feature_from_header()

            # Find file if needed
            if file_name and not file_id:
                file_id = await self._find_file_by_name(gdrive_feature, file_name)
                if not file_id:
                    return {"error": f"No MindMup file found with name '{file_name}'."}

            # Get file metadata
            file_metadata = await gdrive_feature.get_file_metadata(file_id)
            file_size = int(file_metadata.get('size', 0)) if file_metadata else 0

            # Download and parse
            mindmup, file_content, error = await self._download_and_parse_mindmup(gdrive_feature, file_id)
            if error:
                return error

            # Extract ALL text content for comprehensive analysis
            all_text_list = mindmup.extract_text_content()
            all_text = ' '.join(all_text_list) if all_text_list else ''
            content_length = len(all_text)

            # Get ALL node titles (no limit) for complete overview
            all_titles = MindmupParser.get_all_node_title(mindmup.root_node, max_title=5000)

            # Extract structure
            structured_data = MindmupParser.extract_mindmap_structure(mindmup)

            # Build main sections from hierarchy
            main_sections = []
            hierarchy = structured_data.get('hierarchy', {})
            if 'children' in hierarchy:
                main_sections = [s.get('title', '') for s in hierarchy['children']]

            # Build result
            result = {
                "file_info": {
                    "file_id": file_id,
                    "file_name": file_metadata.get('name', 'Unknown'),
                    "file_size_mb": round(file_size / (1024 * 1024), 2) if file_size else 0,
                    "title": mindmup.title,
                    "content_length": content_length
                },
                "overview": structured_data.get('overview'),
                "main_sections": main_sections,
                "all_section_titles": all_titles,
                "total_nodes": mindmup.get_node_count()
            }

            # Add chunk information if content is large enough to be chunked
            if content_length > MindmupParser.CLAUDE_MAX_CONTENT_LENGTH:
                chunk_previews = MindmupParser.get_chunk_previews(all_text)
                result["chunking_info"] = {
                    "total_chunks": len(chunk_previews),
                    "chunk_size_limit": MindmupParser.CLAUDE_MAX_CONTENT_LENGTH,
                    "chunk_previews": chunk_previews,
                    "usage_hint": f"Use get_mindmup_chunk_tool(file_id='{file_id}', chunk_index=N) to read specific chunks"
                }
            else:
                result["chunking_info"] = {
                    "total_chunks": 1,
                    "message": "File is small enough to read in single request"
                }

            return result

        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error(f'analyze_mindmup_summary_tool error: {e}')
            return {"error": str(e)}

    async def get_mindmup_chunk_tool(
            self, file_id: str, chunk_index: int = 0, search_keyword: Optional[str] = None) -> Dict[str, Any]:
        """Get specific chunk of a large mindmup file, with optional search.

        Args:
            file_id: File ID to download.
            chunk_index: Which chunk to retrieve (0-based). Use -1 for search-only mode.
            search_keyword: Optional keyword to search for in the mindmap.
        """
        try:
            gdrive_feature = await self._get_gdrive_feature_from_header()

            # Download and parse
            mindmup, file_content, error = await self._download_and_parse_mindmup(gdrive_feature, file_id)
            if error:
                return error

            result = {
                "file_id": file_id,
                "mindmap_info": {
                    "title": mindmup.title,
                    "node_count": mindmup.get_node_count()
                }
            }

            # If search keyword provided, perform search
            if search_keyword:
                search_result = MindmupParser.search_node(
                    node=mindmup.root_node,
                    keyword=search_keyword,
                    max_result=30
                )
                result["search_result"] = {
                    "keyword": search_keyword,
                    "total_found": len(search_result),
                    "result": search_result
                }

            # If chunk_index is -1, only return search results (search-only mode)
            if chunk_index == -1:
                result["status"] = "complete"
                result["message"] = "Search-only mode. Use chunk_index >= 0 to retrieve content."
                return result

            # Extract text content for chunking
            all_text_list = mindmup.extract_text_content()
            all_text = ' '.join(all_text_list) if all_text_list else ''

            # Split into chunk
            chunk_list = MindmupParser.split_content_to_chunk(content=all_text)

            if chunk_index >= len(chunk_list):
                return {
                    "error": f"Invalid chunk_index {chunk_index}. File has {len(chunk_list)} chunk total."
                }

            target_chunk = chunk_list[chunk_index]
            total_chunks = target_chunk["total_chunk"]
            is_last_chunk = chunk_index >= total_chunks - 1

            result["current_chunk"] = chunk_index
            result["total_chunks"] = total_chunks
            result["status"] = "complete" if is_last_chunk else "partial"
            result["chunk_info"] = {
                "content_length": len(target_chunk["content"]),
                "start_position": target_chunk["start_pos"],
                "end_position": target_chunk["end_pos"]
            }
            result["content"] = target_chunk["content"]
            result["mindmap_info"]["total_length"] = len(all_text)

            # Guide AI to continue reading if not complete
            if not is_last_chunk:
                next_index = chunk_index + 1
                result["next_action"] = f"Call get_mindmup_chunk_tool(file_id='{file_id}', chunk_index={next_index}) to get chunk {next_index + 1}/{total_chunks}"

            return result

        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            error_message = f'get_mindmup_chunk_tool error: {e}'
            logger.error(error_message)
            return {"error": error_message}

    async def get_multiple_mindmup_tool(
            self, folder_id: Optional[str] = None, name_contain: Optional[str] = None,
            max_result: int = 10) -> Dict[str, Any]:
        """Get multiple mindmup content - Using search and parse.

        Args:
            folder_id: Specific folder to search in. If None, searches globally.
            name_contain: Filter by file name containing this text.
            max_result: Maximum number of files to process (default: 10).
        """
        try:
            gdrive_feature = await self._get_gdrive_feature_from_header()

            # Searching all mindmup files using gdrive_feature
            mindmup_file = await gdrive_feature.search_mindmup_file(
                folder_id=folder_id,
                name_contain=name_contain
            )

            result_data = []

            # Limit the number of file to process
            file_to_process = mindmup_file[:max_result]

            logger.info(
                f'Found {len(mindmup_file)} MindMup file, processing first {len(file_to_process)}')

            # Loading and parsing mindmup one by one
            for file_info in file_to_process:
                try:
                    # Check file size before processing
                    if hasattr(file_info, 'size') and file_info.size:
                        file_size = int(file_info.size)
                        if not gdrive_feature.check_file_size(file_size, file_info.name):
                            # Skip large files and add a summary entry
                            result_data.append({
                                "file_id": file_info.id,
                                "file_name": file_info.name,
                                "file_url": file_info.web_view_link,
                                "last_modified": file_info.modified_time.isoformat() if file_info.modified_time else None,
                                "error": f"File too large ({file_size} bytes), skipped",
                                "file_size_bytes": file_size
                            })
                            continue

                    # Download the file from GDrive
                    download_result_frm_gdrive = await gdrive_feature.download_file_content(file_id=file_info.id)

                    if download_result_frm_gdrive.is_success:
                        file_content = download_result_frm_gdrive.detail.get('content_str')
                        if file_content:
                            try:
                                mindmap_data = await self._process_mindmup_content(file_info.id, file_content)
                                if "error" not in mindmap_data:
                                    # Add preview for multiple files
                                    if "all_text_content" in mindmap_data:
                                        mindmap_data["preview"] = MindmupParser.create_content_summary(
                                            mindmap_data["all_text_content"], max_length=500
                                        )
                                    result_data.append({
                                        "file_id": file_info.id,
                                        "file_name": file_info.name,
                                        "file_url": file_info.web_view_link,
                                        "last_modified": file_info.modified_time.isoformat() if file_info.modified_time else None,
                                        "mindmap": mindmap_data
                                    })
                                else:
                                    logger.error(f'get_multiple_mindmup_tool: {mindmap_data["error"]}')
                            except Exception as parse_error:
                                logger.error(
                                    f'get_multiple_mindmup_tool parse error: {file_info.id}, {parse_error}')

                except Exception as file_error:
                    logger.error(
                        f'get_multiple_mindmup_tool file error: {file_info.id}, {file_error}')

            logger.info(
                f'get_multiple_mindmup_tool: processed {len(result_data)} files')
            return {
                "result": result_data,
                "count": len(result_data)
            }

        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            error_message = f'get_multiple_mindmup_tool error: {e}'
            logger.error(error_message)
            return {"error": error_message}

    def _setup_tool(self):
        self.mcp.tool()(self.gdrive_tool_list_file)
        self.mcp.tool()(self.get_single_mindmup_tool)
        self.mcp.tool()(self.analyze_mindmup_summary_tool)
        self.mcp.tool()(self.get_mindmup_chunk_tool)
        self.mcp.tool()(self.get_multiple_mindmup_tool)

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
