"""Tests for MCPServer.get_mindmap_section size threshold (recursive drill-down)."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.mcp_server import MCPServer
from src.model.mindmup_model import Mindmup, MindmupNode


from tests.conftest import run_async


@pytest.fixture
def server():
    instance = MCPServer.__new__(MCPServer)
    instance.mcp = MagicMock()
    return instance


def _build_subtree_mindmup(top_children: int, deep_children: int, title_chars: int = 5) -> str:
    """Mindmup whose section [1.1] holds a controllable amount of content.

    Top-level structure: root -> [1.1] -> deep_children leaves.
    [1.1]'s subtree size scales with (deep_children x title_chars).
    """
    pad = "x" * title_chars
    deep_ideas = {
        str(i + 1): {"id": f"d{i}", "title": f"Deep_{i}_{pad}", "ideas": {}}
        for i in range(deep_children)
    }
    top_ideas = {
        "1": {"id": "section1", "title": "Section One", "ideas": deep_ideas},
    }
    for i in range(2, top_children + 1):
        top_ideas[str(i)] = {"id": f"s{i}", "title": f"Section {i}", "ideas": {}}

    data = {
        "id": "root",
        "title": "Test",
        "formatVersion": "2.0",
        "ideas": top_ideas,
    }
    return json.dumps(data)


def _mock_gdrive_with_content(content: str):
    feature_mock = MagicMock()
    feature_mock.fetch_file_content = AsyncMock(return_value=MagicMock(
        is_success=True,
        detail={"content_str": content},
    ))
    return feature_mock


class TestGetMindmapSectionSizeGuard:

    def test_small_subtree_returns_full(self, server):
        """Drilled subtree under threshold -> content_type 'full' with subtree dict."""
        content = _build_subtree_mindmup(top_children=3, deep_children=5, title_chars=5)
        feature = _mock_gdrive_with_content(content)

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature)):
            result = run_async(server.get_mindmap_section("fid", "1.1"))

        assert result["content_type"] == "full"
        assert "subtree" in result
        assert result["node_path"] == "1.1"

    def test_large_subtree_returns_outline_only(self, server):
        """Drilled subtree over threshold -> outline + section_stats with deeper paths."""
        # 800 deep children x 200 char titles -> > 100KB ai_dict for [1.1] subtree
        content = _build_subtree_mindmup(top_children=2, deep_children=800, title_chars=200)
        feature = _mock_gdrive_with_content(content)

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature)):
            result = run_async(server.get_mindmap_section("fid", "1.1"))

        assert result["content_type"] == "outline_only"
        assert "subtree" not in result
        assert "tree_outline" in result
        assert "section_stats" in result
        # outline should use the drilled path as prefix, not "1"
        assert "[1.1]" in result["tree_outline"]
        assert "[1.1.1]" in result["tree_outline"]
        assert "Section One" in result["tree_outline"]
        # message should hint to drill deeper
        assert "1.1.N" in result["message"]
        # section_stats paths must use the drilled prefix, not root "1"
        stat_paths = [s["path"] for s in result["section_stats"]]
        assert len(stat_paths) > 0
        assert all(p.startswith("1.1.") for p in stat_paths)

    def test_cjk_subtree_measured_in_bytes_not_chars(self, server):
        """get_mindmap_section must also measure size in bytes, not chars."""
        cjk_char = "\u4e2d"  # '中', 3 bytes in UTF-8
        # Build a subtree that's small in chars (~40KB) but large in bytes (~120KB)
        children = [
            MindmupNode(id=f"c{i}", title=cjk_char * 800, children=[], attribute={})
            for i in range(50)
        ]
        root = MindmupNode(id="root", title="Root", children=children, attribute={})
        mindmup = Mindmup(title="CJK", root_node=root)

        feature = _mock_gdrive_with_content("{}")
        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature)), \
             patch.object(server, '_fetch_and_parse_mindmup',
                          AsyncMock(return_value=(mindmup, "{}", {}))):
            result = run_async(server.get_mindmap_section(file_id="fid", node_path="1"))

        assert result["content_type"] == "outline_only"


class TestGetMindmapSectionMaxDepth:

    def test_default_max_depth_unchanged(self, server):
        """max_depth=None (default) still returns outline_only with OUTLINE_ONLY_MAX_DEPTH."""
        content = _build_subtree_mindmup(top_children=2, deep_children=800, title_chars=200)
        feature = _mock_gdrive_with_content(content)

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature)):
            result = run_async(server.get_mindmap_section("fid", "1.1"))

        assert result["content_type"] == "outline_only"
        assert result["tree_outline"]
        assert "outline depth = 3" in result["message"]

    def test_max_depth_1_shallower_than_default(self, server):
        """max_depth=1 produces fewer outline lines than the default depth=3."""
        # Build a deep tree: root -> [1.1] -> 20 children -> 10 grandchildren -> 5 leaves
        # 20 + 200 + 1000 = 1220 nodes × 500 chars ≈ 610KB ai_dict → outline_only
        nested_ideas = {}
        for i in range(20):
            grandchildren = {}
            for j in range(10):
                leaves = {
                    str(k + 1): {"id": f"l{i}_{j}_{k}", "title": "L" * 500, "ideas": {}}
                    for k in range(5)
                }
                grandchildren[str(j + 1)] = {
                    "id": f"g{i}_{j}", "title": "G" * 500, "ideas": leaves
                }
            nested_ideas[str(i + 1)] = {
                "id": f"c{i}", "title": "C" * 500, "ideas": grandchildren
            }
        data = {
            "id": "root", "title": "Test", "formatVersion": "2.0",
            "ideas": {"1": {"id": "s1", "title": "Section One", "ideas": nested_ideas}},
        }
        content = json.dumps(data)
        feature = _mock_gdrive_with_content(content)

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature)):
            default_result = run_async(server.get_mindmap_section("fid", "1.1"))
            shallow_result = run_async(server.get_mindmap_section(
                "fid", "1.1", max_depth=1
            ))

        assert default_result["content_type"] == "outline_only"
        assert shallow_result["content_type"] == "outline_only"
        default_lines = default_result["tree_outline"].count("\n")
        shallow_lines = shallow_result["tree_outline"].count("\n")
        assert shallow_lines < default_lines
        assert "outline depth = 1" in shallow_result["message"]

    def test_max_depth_clamped_to_limit(self, server):
        """max_depth=999 is silently clamped to MAX_DEPTH_LIMIT, not rejected."""
        content = _build_subtree_mindmup(top_children=2, deep_children=800, title_chars=200)
        feature = _mock_gdrive_with_content(content)

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature)):
            result = run_async(server.get_mindmap_section("fid", "1.1", max_depth=999))

        assert result["content_type"] == "outline_only"
        assert "outline depth = 10" in result["message"]

    def test_max_depth_invalid_rejected(self, server):
        """max_depth < 1 returns error without calling gdrive."""
        result = run_async(server.get_mindmap_section("fid", "1.1", max_depth=0))
        assert "error" in result
        assert "max_depth" in result["error"]


class TestGetMindmapSectionPagination:

    def test_pagination_returns_children_slice(self, server):
        """limit>0 on large subtree returns only the requested slice."""
        content = _build_subtree_mindmup(top_children=2, deep_children=800, title_chars=200)
        feature = _mock_gdrive_with_content(content)

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature)):
            result = run_async(server.get_mindmap_section(
                "fid", "1.1", offset=0, limit=10
            ))

        assert result["content_type"] == "paginated"
        assert len(result["children"]) == 10
        assert result["children"][0]["path"] == "1.1.1"
        assert result["children"][9]["path"] == "1.1.10"
        assert result["pagination"]["total_children"] == 800
        assert result["pagination"]["has_more"] is True
        assert result["pagination"]["next_offset"] == 10

    def test_pagination_last_page(self, server):
        """Last page: has_more=False, next_offset=None."""
        cjk_char = "\u4e2d"
        deep_ideas = {
            str(i + 1): {"id": f"d{i}", "title": cjk_char * 2000, "ideas": {}}
            for i in range(20)
        }
        data = {
            "id": "root", "title": "Test", "formatVersion": "2.0",
            "ideas": {"1": {"id": "s1", "title": "Big", "ideas": deep_ideas}},
        }
        content = json.dumps(data)
        feature = _mock_gdrive_with_content(content)

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature)):
            result = run_async(server.get_mindmap_section(
                "fid", "1.1", offset=10, limit=20
            ))

        assert result["content_type"] == "paginated"
        assert len(result["children"]) == 10
        assert result["pagination"]["has_more"] is False
        assert result["pagination"]["next_offset"] is None

    def test_truncation_for_heavy_leaf_node(self, server):
        """Leaf node over limit: content_type='truncated' with partial content."""
        cjk_char = "\u4e2d"
        data = {
            "id": "root", "title": "Test", "formatVersion": "2.0",
            "ideas": {
                "1": {"id": "s1", "title": cjk_char * 50000, "ideas": {}},
            },
        }
        content = json.dumps(data)
        feature = _mock_gdrive_with_content(content)

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature)):
            result = run_async(server.get_mindmap_section("fid", "1.1"))

        assert result["content_type"] == "truncated"
        assert "subtree_text" in result
        assert result["truncation"]["is_complete"] is False
        assert len(result["subtree_text"]) < result["truncation"]["original_bytes"]

    def test_outline_only_message_suggests_pagination(self, server):
        """Default outline_only message now mentions offset/limit option."""
        content = _build_subtree_mindmup(top_children=2, deep_children=800, title_chars=200)
        feature = _mock_gdrive_with_content(content)

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature)):
            result = run_async(server.get_mindmap_section("fid", "1.1"))

        assert result["content_type"] == "outline_only"
        assert "offset=0, limit=20" in result["message"]

    def test_pagination_oversized_suggests_drill_deeper(self, server):
        """When each child individually exceeds limit, message says drill deeper."""
        cjk_char = "\u4e2d"
        # 5 children each with 40000 CJK chars ≈ 120KB per child (> 100KB limit)
        deep_ideas = {
            str(i + 1): {"id": f"d{i}", "title": cjk_char * 40000, "ideas": {}}
            for i in range(5)
        }
        data = {
            "id": "root", "title": "Test", "formatVersion": "2.0",
            "ideas": {"1": {"id": "s1", "title": "Big", "ideas": deep_ideas}},
        }
        content = json.dumps(data)
        feature = _mock_gdrive_with_content(content)

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature)):
            result = run_async(server.get_mindmap_section(
                "fid", "1.1", offset=0, limit=2
            ))

        assert result["content_type"] == "outline_only"
        assert "Drill deeper" in result["message"]
        assert "limit=1" not in result["message"]
        assert "children" not in result

    def test_pagination_oversized_suggests_limit1_when_viable(self, server):
        """When total slice is too large but individual children are small enough, suggest limit=1."""
        # 10 children × 15KB each = 150KB total (> 100KB), but each child < 100KB
        deep_ideas = {
            str(i + 1): {"id": f"d{i}", "title": "x" * 15000, "ideas": {}}
            for i in range(10)
        }
        data = {
            "id": "root", "title": "Test", "formatVersion": "2.0",
            "ideas": {"1": {"id": "s1", "title": "Big", "ideas": deep_ideas}},
        }
        content = json.dumps(data)
        feature = _mock_gdrive_with_content(content)

        with patch.object(server, '_get_gdrive_feature_from_header',
                          AsyncMock(return_value=feature)):
            result = run_async(server.get_mindmap_section(
                "fid", "1.1", offset=0, limit=10
            ))

        assert result["content_type"] == "outline_only"
        assert "limit=1" in result["message"]

    def test_pagination_offset_limit_validation(self, server):
        """Negative offset or limit returns error."""
        result = run_async(server.get_mindmap_section("fid", "1.1", offset=-1))
        assert "error" in result

        result = run_async(server.get_mindmap_section("fid", "1.1", limit=-1))
        assert "error" in result
