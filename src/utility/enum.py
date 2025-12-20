from enum import Enum


class MimeType(str, Enum):
    """MIME types used for file detection."""

    JSON = 'application/json'
    TEXT = 'text/plain'
    FOLDER = 'application/vnd.google-apps.folder'
    MINDMUP = 'application/vnd.mindmup'
    OCTET = 'application/octet-stream'


# Google Apps MIME types that cannot be directly downloaded
GOOGLE_APPS_MIME_TYPE = [
    'application/vnd.google-apps.document',
    'application/vnd.google-apps.spreadsheet',
    'application/vnd.google-apps.presentation',
    'application/vnd.google-apps.form',
    'application/vnd.google-apps.drawing',
    'application/vnd.google-apps.script',
    'application/vnd.google-apps.folder'
]
