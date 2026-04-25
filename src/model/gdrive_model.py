from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any

from src.utility.enum import MimeType, GOOGLE_APPS_MIME_TYPE


@dataclass
class SearchQuery:
    """Google Drive search query parameters."""

    name_contain: Optional[str] = None
    mime_type: List[str] = field(default_factory=list)
    max_result: int = 1000
    include_trashed: bool = False

    def to_drive_query(self) -> str:
        """Convert to Google Drive API query string."""
        conditions = []

        if not self.include_trashed:
            conditions.append('trashed=false')

        if self.name_contain:
            safe_name = self.name_contain.replace('"', '\\"')
            conditions.append(f'name contains "{safe_name}"')

        if self.mime_type:
            mime_conditions = [
                f'mimeType="{mt.value if hasattr(mt, "value") else str(mt)}"'
                for mt in self.mime_type
            ]
            conditions.append(f"({' or '.join(mime_conditions)})")

        return ' and '.join(conditions) if conditions else ''


@dataclass
class FileInfo:
    """Google Drive file metadata."""

    id: str
    name: str
    mime_type: str
    size: Optional[int] = None
    modified_time: Optional[datetime] = None
    created_time: Optional[datetime] = None
    parents: List[str] = field(default_factory=list)
    web_view_link: Optional[str] = None
    starred: bool = False
    shared: bool = False

    def is_folder(self) -> bool:
        return self.mime_type == MimeType.FOLDER

    def is_mindmup(self) -> bool:
        # Skip folders entirely - they can't be MindMup files
        if self.is_folder():
            return False

        # Skip all Google Apps types (Docs, Sheets, Scripts, etc.)
        if self.mime_type in GOOGLE_APPS_MIME_TYPE:
            return False

        # 1. Official MindMup MIME type (highest priority)
        if self.mime_type == MimeType.MINDMUP:
            return True

        # 2. Files with .mup extension (very high priority)
        if self.name.endswith('.mup'):
            return True

        # 3. For other file types, be more restrictive
        name_lower = self.name.lower()

        # Only consider JSON/text files if they explicitly mention mindmup or have .mup in name
        acceptable_mimes = [MimeType.JSON, MimeType.TEXT, MimeType.OCTET]
        if self.mime_type in acceptable_mimes:
            # Must have explicit MindMup indicators
            mindmup_indicators = ['.mup', 'mindmup', 'mindmap']
            if any(indicator in name_lower for indicator in mindmup_indicators):
                return True

        return False


def parse_drive_time(dt_str: Optional[str]) -> Optional[datetime]:
    """Parse Google Drive time string."""
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None


def create_file_info(data: Dict[str, Any]) -> FileInfo:
    return FileInfo(
        id=data['id'],
        name=data['name'],
        mime_type=data['mimeType'],
        size=data.get('size'),
        modified_time=parse_drive_time(data.get('modifiedTime')),
        created_time=parse_drive_time(data.get('createdTime')),
        parents=data.get('parents', []),
        web_view_link=data.get('webViewLink'),
        starred=data.get('starred', False),
        shared=data.get('shared', False)
    )
