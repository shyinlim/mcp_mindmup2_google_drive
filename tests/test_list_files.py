"""Tests for MCPServer.list_files URL output."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.mcp_server import MCPServer
from src.model.gdrive_model import FileInfo


from tests.conftest import run_async


@pytest.fixture
def server():
    instance = MCPServer.__new__(MCPServer)
    instance.mcp = MagicMock()
    return instance


def _make_op_result(files):
    """Build a successful OperationResult-like mock."""
    op = MagicMock()
    op.is_success = True
    op.detail = {
        "files": files,
        "files_total_count": len(files),
        "next_page_token": None,
    }
    return op


class TestListFilesUrl:

    def test_folder_url_built_from_parent_id(self, server):
        """list_files should expose parent folder URL as 'folder_url'."""
        file_info = FileInfo(
            id="abc123",
            name="my_mindmap.mup",
            mime_type="application/json",
            parents=["folder_xyz"],
        )
        feature_mock = MagicMock()
        feature_mock.list_file = AsyncMock(return_value=_make_op_result([file_info]))

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature_mock)):
            result = run_async(server.list_files())

        assert result["files_total_count"] == 1
        assert result["files"][0]["folder_url"] == "https://drive.google.com/drive/folders/folder_xyz"
        assert result["files"][0]["id"] == "abc123"
        assert result["files"][0]["name"] == "my_mindmap.mup"

    def test_folder_url_is_none_when_no_parent(self, server):
        """File at Drive root has no parents -> folder_url should be None."""
        file_info = FileInfo(
            id="root_file",
            name="orphan.mup",
            mime_type="application/json",
            parents=[],
        )
        feature_mock = MagicMock()
        feature_mock.list_file = AsyncMock(return_value=_make_op_result([file_info]))

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature_mock)):
            result = run_async(server.list_files())

        assert result["files"][0]["folder_url"] is None

    def test_empty_file_list(self, server):
        feature_mock = MagicMock()
        feature_mock.list_file = AsyncMock(return_value=_make_op_result([]))

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature_mock)):
            result = run_async(server.list_files())

        assert result["files"] == []
        assert result["files_total_count"] == 0

    def test_excludes_folders_and_non_mindmup_by_default(self, server):
        """Default mindmup_only=True should exclude folders and non-mindmup files."""
        folder = FileInfo(id="f1", name="My Folder", mime_type="application/vnd.google-apps.folder")
        doc = FileInfo(id="d1", name="Spec.gdoc", mime_type="application/vnd.google-apps.document")
        mindmup = FileInfo(id="m1", name="real.mup", mime_type="application/json")

        feature_mock = MagicMock()
        feature_mock.list_file = AsyncMock(return_value=_make_op_result([folder, doc, mindmup]))

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature_mock)):
            result = run_async(server.list_files())

        assert result["files_total_count"] == 1
        assert result["files"][0]["id"] == "m1"

    def test_mindmup_only_false_includes_everything(self, server):
        """Setting mindmup_only=False returns all files including folders."""
        folder = FileInfo(id="f1", name="My Folder", mime_type="application/vnd.google-apps.folder")
        mindmup = FileInfo(id="m1", name="real.mup", mime_type="application/json")

        feature_mock = MagicMock()
        feature_mock.list_file = AsyncMock(return_value=_make_op_result([folder, mindmup]))

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature_mock)):
            result = run_async(server.list_files(mindmup_only=False))

        assert result["files_total_count"] == 2
