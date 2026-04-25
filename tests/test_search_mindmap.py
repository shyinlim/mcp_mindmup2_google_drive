"""Tests for MCPServer.search_mindmap title truncation."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.mcp_server import MCPServer


from tests.conftest import run_async


@pytest.fixture
def server():
    instance = MCPServer.__new__(MCPServer)
    instance.mcp = MagicMock()
    return instance


def _build_content_with_long_title(long_title: str) -> str:
    """Build mindmup with one node holding a very long title (e.g. embedded JSON)."""
    data = {
        "id": "root",
        "title": "Test",
        "formatVersion": "2.0",
        "ideas": {
            "1": {"id": "section", "title": "Section", "ideas": {
                "1": {"id": "leaf", "title": long_title, "ideas": {}},
            }},
        },
    }
    return json.dumps(data)


def _mock_gdrive_with_content(content: str):
    feature_mock = MagicMock()
    feature_mock.fetch_file_content = AsyncMock(return_value=MagicMock(
        is_success=True,
        detail={"content_str": content},
    ))
    return feature_mock


class TestSearchMindmapTitlePreview:

    def test_title_preview_truncated_when_long(self, server):
        """Long titles (multi-line JSON / SQL stored in MindMup title) must be truncated."""
        long_title = "occupy " + "x" * 500  # 507 chars total, contains keyword
        content = _build_content_with_long_title(long_title)
        feature = _mock_gdrive_with_content(content)

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature)):
            result = run_async(server.search_mindmap("fid", "occupy"))

        assert result["total_found"] == 1
        preview = result["results"][0]["title_preview"]
        assert preview.endswith("...")
        assert len(preview) <= 110  # 100 char limit + "..." marker

    def test_short_title_not_truncated(self, server):
        """Titles under the limit should not have ellipsis."""
        content = _build_content_with_long_title("short occupy title")
        feature = _mock_gdrive_with_content(content)

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature)):
            result = run_async(server.search_mindmap("fid", "occupy"))

        assert result["results"][0]["title_preview"] == "short occupy title"
        assert not result["results"][0]["title_preview"].endswith("...")

    def test_node_path_and_hint_intact(self, server):
        """node_path and drill-down hint must always be present."""
        content = _build_content_with_long_title("occupy here")
        feature = _mock_gdrive_with_content(content)

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature)):
            result = run_async(server.search_mindmap("fid", "occupy"))

        assert result["results"][0]["node_path"] == "1.1.1"
        assert "get_mindmap_section" in result["hint"]

    def test_search_whitespace_insensitive_by_default(self, server):
        """'N 類' should match 'N類' when normalize_whitespace=True (default)."""
        content = _build_content_with_long_title("N類 轉出")
        feature = _mock_gdrive_with_content(content)

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature)):
            result = run_async(server.search_mindmap("fid", "N 類"))

        assert result["total_found"] == 1
        assert result["results"][0]["node_path"] == "1.1.1"

    def test_search_whitespace_exact_when_disabled(self, server):
        """normalize_whitespace=False must respect literal whitespace."""
        content = _build_content_with_long_title("N類 轉出")
        feature = _mock_gdrive_with_content(content)

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature)):
            result = run_async(server.search_mindmap(
                "fid", "N 類", normalize_whitespace=False
            ))

        assert result["total_found"] == 0

    def test_search_result_includes_breadcrumb(self, server):
        """Each search result must include ancestor titles for disambiguation."""
        data = {
            "id": "root",
            "title": "TestCase: [BE]",
            "formatVersion": "2.0",
            "ideas": {
                "1": {"id": "mid", "title": "BE API", "ideas": {
                    "1": {"id": "leaf", "title": "N類 轉出", "ideas": {}},
                }},
            },
        }
        content = json.dumps(data)
        feature = _mock_gdrive_with_content(content)

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature)):
            result = run_async(server.search_mindmap("fid", "N類"))

        assert result["total_found"] == 1
        hit = result["results"][0]
        assert hit["node_path"] == "1.1.1"
        assert hit["breadcrumb"] == ["TestCase: [BE]", "BE API"]


class TestSearchMindmapScopedSearch:

    def _build_scoped_tree(self) -> str:
        """Tree: root -> [A -> [A1(keyword), A2], B -> [B1(keyword)]]"""
        data = {
            "id": "root", "title": "Root", "formatVersion": "2.0",
            "ideas": {
                "1": {"id": "a", "title": "Section A", "ideas": {
                    "1": {"id": "a1", "title": "find target here", "ideas": {}},
                    "2": {"id": "a2", "title": "no match", "ideas": {}},
                }},
                "2": {"id": "b", "title": "Section B", "ideas": {
                    "1": {"id": "b1", "title": "find target also", "ideas": {}},
                }},
            },
        }
        return json.dumps(data)

    def test_scoped_search_only_returns_matches_in_subtree(self, server):
        """search with node_path='1.1' (Section A) finds A1 but NOT B1."""
        content = self._build_scoped_tree()
        feature = _mock_gdrive_with_content(content)

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature)):
            result = run_async(server.search_mindmap(
                "fid", "target", node_path="1.1"
            ))

        assert result["total_found"] == 1
        assert result["results"][0]["node_path"] == "1.1.1"
        assert result["search_scope"] == "1.1"

    def test_unscoped_search_finds_all_matches(self, server):
        """Without node_path, search returns matches from entire tree."""
        content = self._build_scoped_tree()
        feature = _mock_gdrive_with_content(content)

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature)):
            result = run_async(server.search_mindmap("fid", "target"))

        assert result["total_found"] == 2
        assert result["search_scope"] is None

    def test_scoped_search_paths_are_absolute(self, server):
        """Matched paths are absolute (usable with get_mindmap_section)."""
        content = self._build_scoped_tree()
        feature = _mock_gdrive_with_content(content)

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature)):
            result = run_async(server.search_mindmap(
                "fid", "target", node_path="1.1"
            ))

        assert result["results"][0]["node_path"].startswith("1.1.")

    def test_scoped_search_invalid_path_returns_error(self, server):
        """Non-existent node_path returns error with clear message."""
        content = self._build_scoped_tree()
        feature = _mock_gdrive_with_content(content)

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature)):
            result = run_async(server.search_mindmap(
                "fid", "target", node_path="9.9.9"
            ))

        assert "error" in result
        assert "9.9.9" in result["error"]

    def test_scoped_search_malformed_path_rejected(self, server):
        """node_path with non-integer segments returns error before fetching."""
        result = run_async(server.search_mindmap(
            "fid", "target", node_path="abc.def"
        ))
        assert "error" in result
        assert "dotted integer" in result["error"]

    def test_scoped_search_breadcrumb_starts_from_scope(self, server):
        """Breadcrumb under scoped search starts from scope root, not mindmap root."""
        content = self._build_scoped_tree()
        feature = _mock_gdrive_with_content(content)

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature)):
            result = run_async(server.search_mindmap(
                "fid", "target", node_path="1.1"
            ))

        hit = result["results"][0]
        assert any("Section A" in b for b in hit["breadcrumb"])
        assert not any("Root" in b for b in hit["breadcrumb"])

    def test_scope_root_itself_matches(self, server):
        """If keyword matches the scope root node's title, it should be included."""
        content = self._build_scoped_tree()
        feature = _mock_gdrive_with_content(content)

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature)):
            result = run_async(server.search_mindmap(
                "fid", "Section A", node_path="1.1"
            ))

        assert result["total_found"] == 1
        assert result["results"][0]["node_path"] == "1.1"
