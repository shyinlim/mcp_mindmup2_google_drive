from datetime import datetime
from typing import Optional, Dict, List, Any

from src.core import gdrive_cache
from src.core.gdrive_client import GoogleDriveClient
from src.model.common_model import OperationResult
from src.model.gdrive_model import FileInfo, SearchQuery, create_file_info
from src.utility.logger import get_logger

logger = get_logger(__name__)


class GoogleDriveFeature:

    def __init__(self, client: GoogleDriveClient, client_id: str, credential_hash: str):
        self.client = client
        self.client_id = client_id
        self.credential_hash = credential_hash

    async def list_file(
            self, query: Optional[SearchQuery] = None) -> OperationResult:
        """List out Gdrive file list."""

        try:
            if query is None:
                query = SearchQuery()

            search_query = query.to_drive_query()
            logger.info(f'list_file search_query: {search_query}')

            result = await self.client.run_sync(
                lambda: self.client.service.files().list(
                    q=search_query,
                    pageSize=min(query.max_result, 1000),
                    fields='nextPageToken,files(id,name,mimeType,size,modifiedTime,createdTime,parents,webViewLink,starred,shared,ownedByMe)',
                    orderBy='modifiedTime desc'
                ).execute()
            )

            result_file = result.get('files', [])
            file = [create_file_info(data) for data in result_file]
            logger.info(f'list_file found: {len(file)}')
            return OperationResult.success(detail={
                "files": file,
                "files_total_count": len(file),
                "next_page_token": result.get('nextPageToken')
            })
        except Exception as e:
            error_message = f'list_file error: {e}'
            logger.error(error_message)
            return OperationResult.fail(detail=error_message)

    async def search_mindmup_file(self, name_contain: Optional[str] = None) -> List[FileInfo]:
        """Search for MindMup files in Google Drive.

        Args:
            name_contain: Optional filename filter.

        Returns:
            List of FileInfo objects for MindMup files, sorted by modified time.
        """
        try:
            # Build search patterns
            patterns = []
            if name_contain:
                patterns.append(name_contain)
            patterns.extend(['.mup', 'mindmup'])

            # Search and collect unique mindmup files
            found_files = {}  # Use dict for deduplication by file ID

            for pattern in patterns:
                query = SearchQuery(
                    max_result=1000,
                    name_contain=pattern,
                    include_trashed=False
                )

                result = await self.list_file(query=query)
                if result.is_success:
                    for f in result.detail.get('files', []):
                        if f.is_mindmup() and f.id not in found_files:
                            found_files[f.id] = f

            # Sort by modification time (newest first)
            mindmup_files = list(found_files.values())
            mindmup_files.sort(
                key=lambda x: x.modified_time or x.created_time or datetime.min,
                reverse=True,
            )

            logger.info(f'search_mindmup_file found {len(mindmup_files)} files')
            return mindmup_files

        except Exception as e:
            logger.error(f'search_mindmup_file error: {e}')
            return []

    async def get_file_metadata(self, file_id: str) -> Dict[str, Any]:
        """Get file metadata without downloading content."""
        try:
            file_metadata = await self.client.run_sync(
                lambda: self.client.service.files().get(
                    fileId=file_id,
                    fields='id,name,mimeType,size'
                ).execute()
            )
            return file_metadata
        except Exception as e:
            logger.error(f'get_file_metadata error: {file_id}, {e}')
            return {}

    async def fetch_file_content(self, file_id: str) -> OperationResult:
        """Download file from GDrive with module-level cache.

        Cache is keyed by (client_id, credential_hash, file_id) so entries are
        isolated per AI client and per service account. See src/core/gdrive_cache.py.
        """
        cache_key = (self.client_id, self.credential_hash, file_id)
        cached = gdrive_cache.get(cache_key)
        if cached is not None:
            return OperationResult.success(detail=cached)

        try:
            logger.info(f'fetch_file_content: {file_id}')

            file_metadata = await self.client.run_sync(
                lambda: self.client.service.files().get(
                    fileId=file_id,
                    fields='id,name,mimeType,size'
                ).execute()
            )

            # Since we now filter out Google Apps files in is_mindmup(),
            # we only need to handle regular file downloads
            file_content = await self.client.run_sync(
                lambda: self.client.service.files().get_media(fileId=file_id).execute()
            )

            if file_content is None:
                return OperationResult.fail(
                    detail=f'{file_id} cannot be downloaded.')

            if isinstance(file_content, bytes):
                try:
                    content_str = file_content.decode('utf-8')
                except UnicodeDecodeError:
                    content_str = file_content.decode('utf-8', errors='ignore')
            else:
                content_str = str(file_content)

            if not content_str:
                return OperationResult.fail(
                    detail=f'{file_id} empty or unreadable.')

            logger.info(
                f'fetch_file_content success: {file_metadata.get("name")} ({len(content_str)} characters)')

            result_data = {
                "file_id": file_id,
                "name": file_metadata.get('name'),
                "mime_type": file_metadata.get('mimeType'),
                "size": file_metadata.get('size'),
                "content_str": content_str
            }

            gdrive_cache.put(cache_key, result_data)
            return OperationResult.success(detail=result_data)

        except Exception as e:
            error_message = f'fetch_file_content error: {file_id}, {e}'
            logger.error(error_message)
            return OperationResult.fail(error_message)
