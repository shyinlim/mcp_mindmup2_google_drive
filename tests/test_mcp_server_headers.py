"""Tests for MCPServer._get_gdrive_feature_from_header: X-Client-Id handling."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.mcp_server import MCPServer


from tests.conftest import run_async


@pytest.fixture
def server():
    instance = MCPServer.__new__(MCPServer)
    instance.mcp = MagicMock()
    return instance


def _success_auth_mock():
    mock_client = MagicMock()
    mock_client.authenticate_from_base64 = AsyncMock(
        return_value=MagicMock(is_success=True)
    )
    return mock_client


class TestClientIdHandling:

    def test_missing_client_id_uses_default(self, server):
        """When X-Client-Id header is absent, fallback to 'default'."""
        headers = {"x-google-credential": "dGVzdA=="}

        with patch("src.core.mcp_server.get_http_headers", return_value=headers), \
             patch("src.core.mcp_server.GoogleDriveClient", return_value=_success_auth_mock()):
            feature = run_async(server._get_gdrive_feature_from_header())

        assert feature.client_id == "default"

    def test_custom_client_id_used(self, server):
        """X-Client-Id header value is passed to GoogleDriveFeature."""
        headers = {"x-google-credential": "dGVzdA==", "x-client-id": "shyin-cc"}

        with patch("src.core.mcp_server.get_http_headers", return_value=headers), \
             patch("src.core.mcp_server.GoogleDriveClient", return_value=_success_auth_mock()):
            feature = run_async(server._get_gdrive_feature_from_header())

        assert feature.client_id == "shyin-cc"

    def test_credential_hash_deterministic(self, server):
        """Same credential -> same credential_hash (cache key stable across calls)."""
        headers = {"x-google-credential": "dGVzdA==", "x-client-id": "shyin-cc"}

        with patch("src.core.mcp_server.get_http_headers", return_value=headers), \
             patch("src.core.mcp_server.GoogleDriveClient", return_value=_success_auth_mock()):
            f1 = run_async(server._get_gdrive_feature_from_header())
            f2 = run_async(server._get_gdrive_feature_from_header())

        assert f1.credential_hash == f2.credential_hash
        assert len(f1.credential_hash) == 16  # truncated sha256

    def test_different_credential_different_hash(self, server):
        """Different credential -> different credential_hash."""
        with patch("src.core.mcp_server.GoogleDriveClient", return_value=_success_auth_mock()):
            with patch("src.core.mcp_server.get_http_headers",
                       return_value={"x-google-credential": "QUFB", "x-client-id": "cc"}):
                f1 = run_async(server._get_gdrive_feature_from_header())
            with patch("src.core.mcp_server.get_http_headers",
                       return_value={"x-google-credential": "QkJC", "x-client-id": "cc"}):
                f2 = run_async(server._get_gdrive_feature_from_header())

        assert f1.credential_hash != f2.credential_hash

    def test_missing_credential_raises(self, server):
        with patch("src.core.mcp_server.get_http_headers", return_value={}):
            with pytest.raises(ValueError, match="Missing X-Google-Credential"):
                run_async(server._get_gdrive_feature_from_header())
