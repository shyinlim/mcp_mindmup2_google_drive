"""Tests for MCPServer._process_mindmup_content size-based branching.

Note: _process_mindmup_content does not use self, so we can call it directly
on a minimal MCPServer instance without invoking FastMCP lifecycle.
"""
import json
from unittest.mock import MagicMock

import pytest

from src.core.mcp_server import MCPServer
from src.core.mindmup_parser import MindmupParser


from tests.conftest import run_async


def _build_mindmup(num_children: int, title_chars: int = 5):
    """Build a parsed Mindmup with N top-level children. title_chars controls per-node size."""
    pad = "x" * title_chars
    ideas = {
        str(i + 1): {"id": f"c{i}", "title": f"Child{i}_{pad}", "ideas": {}}
        for i in range(num_children)
    }
    data = {
        "id": "root",
        "title": "Test Mindmap",
        "formatVersion": "2.0",
        "ideas": ideas,
    }
    return MindmupParser.parse_content(json.dumps(data))


@pytest.fixture
def server():
    """Create MCPServer without running FastMCP (bypass __init__)."""
    instance = MCPServer.__new__(MCPServer)
    instance.mcp = MagicMock()
    return instance


class TestProcessMindmupContent:

    def test_small_file_returns_full_with_root_node(self, server):
        """< 1000 nodes: content_type == 'full' with AI-friendly root_node + tree_outline.

        section_stats is intentionally NOT included for full mode (saves tokens;
        AI can derive same info from root_node directly).
        """
        mindmup = _build_mindmup(num_children=10)
        result = run_async(server._process_mindmup_content("fid", mindmup))

        assert result["content_type"] == "full"
        assert "root_node" in result
        assert "tree_outline" in result
        assert "section_stats" not in result

    def test_large_file_returns_outline_only(self, server):
        """ai_dict serialized > 100KB: content_type == 'outline_only', no root_node."""
        # 800 children x 200 char titles -> ai_dict well over 100KB
        mindmup = _build_mindmup(num_children=800, title_chars=200)
        result = run_async(server._process_mindmup_content("fid", mindmup))

        assert result["content_type"] == "outline_only"
        assert "root_node" not in result
        assert "get_mindmap_section" in result["message"]
        assert "tree_outline" in result
        assert "section_stats" in result

    def test_threshold_uses_actual_content_size_not_node_count(self, server):
        """A file with few but content-heavy nodes should also go outline_only."""
        # 100 children x 1500 char titles -> ~150KB ai_dict despite low node count
        mindmup = _build_mindmup(num_children=100, title_chars=1500)
        result = run_async(server._process_mindmup_content("fid", mindmup))

        assert result["content_type"] == "outline_only"

    def test_cjk_content_measured_in_bytes_not_chars(self, server):
        """CJK chars are 3 bytes each in UTF-8; size guard must use bytes."""
        # 50 children x 800 CJK chars = 50 * 800 * 3 = 120KB in bytes
        # but only 40KB in Python chars — without .encode('utf-8') this
        # would wrongly pass as "full" instead of "outline_only".
        cjk_char = "\u4e2d"  # '中', 3 bytes in UTF-8
        ideas = {
            str(i + 1): {"id": f"c{i}", "title": cjk_char * 800, "ideas": {}}
            for i in range(50)
        }
        data = {
            "id": "root",
            "title": "CJK Test",
            "formatVersion": "2.0",
            "ideas": ideas,
        }
        mindmup = MindmupParser.parse_content(json.dumps(data))
        result = run_async(server._process_mindmup_content("fid", mindmup))

        assert result["content_type"] == "outline_only"

    def test_large_file_section_stats_use_root_prefix(self, server):
        """section_stats from read_mindmap (root) should use default prefix '1.N'."""
        mindmup = _build_mindmup(num_children=800, title_chars=200)
        result = run_async(server._process_mindmup_content("fid", mindmup))

        assert result["content_type"] == "outline_only"
        stat_paths = [s["path"] for s in result["section_stats"]]
        assert len(stat_paths) > 0
        assert all(p.startswith("1.") for p in stat_paths)
        assert stat_paths[0] == "1.1"

    def test_section_stats_default_prefix_not_empty(self, server):
        """get_section_stats default path_prefix='1' should never produce empty paths."""
        mindmup = _build_mindmup(num_children=800, title_chars=200)
        result = run_async(server._process_mindmup_content("fid", mindmup))

        stat_paths = [s["path"] for s in result["section_stats"]]
        assert all(p and not p.startswith(".") for p in stat_paths)

    def test_result_includes_metadata_fields(self, server):
        """Result should include title, id, format_version, node_count, metadata."""
        mindmup = _build_mindmup(num_children=3)
        result = run_async(server._process_mindmup_content("fid", mindmup))

        assert result["title"] == "Test Mindmap"
        assert result["format_version"] == "2.0"
        assert result["node_count"] == 4  # root + 3 children
        assert "metadata" in result

    def test_large_file_exposes_suggested_start_paths(self, server):
        """Outline_only includes Top-K paths sorted by text_weight descending."""
        # 30 children with decreasing title sizes; total > 100KB to trigger outline_only
        ideas = {}
        for i in range(30):
            title_len = max(5000 - (i * 100), 100)
            ideas[str(i + 1)] = {
                "id": f"c{i}",
                "title": "A" * title_len,
                "ideas": {},
            }
        data = {
            "id": "root", "title": "Big", "formatVersion": "2.0",
            "ideas": ideas,
        }
        mindmup = MindmupParser.parse_content(json.dumps(data))
        result = run_async(server._process_mindmup_content("fid", mindmup))

        assert result["content_type"] == "outline_only"
        assert "suggested_start_paths" in result
        paths = result["suggested_start_paths"]
        assert len(paths) == 5

        stats_by_path = {s["path"]: s["text_weight"] for s in result["section_stats"]}
        weights = [stats_by_path[p] for p in paths]
        assert weights == sorted(weights, reverse=True)

        stat_paths = {s["path"] for s in result["section_stats"]}
        assert all(p in stat_paths for p in paths)

    def test_large_file_fewer_than_k_sections(self, server):
        """When < K sections exist, suggested_start_paths has all of them."""
        cjk_char = "\u4e2d"
        ideas = {
            str(i + 1): {"id": f"c{i}", "title": cjk_char * 12000, "ideas": {}}
            for i in range(3)
        }
        data = {
            "id": "root", "title": "Big", "formatVersion": "2.0",
            "ideas": ideas,
        }
        mindmup = MindmupParser.parse_content(json.dumps(data))
        result = run_async(server._process_mindmup_content("fid", mindmup))

        assert result["content_type"] == "outline_only"
        assert len(result["suggested_start_paths"]) == 3

    def test_small_file_has_no_suggested_start_paths(self, server):
        """Full-content mode must not include suggested_start_paths."""
        data = {
            "id": "root", "title": "Small", "formatVersion": "2.0",
            "ideas": {"1": {"id": "c1", "title": "short", "ideas": {}}},
        }
        mindmup = MindmupParser.parse_content(json.dumps(data))
        result = run_async(server._process_mindmup_content("fid", mindmup))

        assert result["content_type"] == "full"
        assert "suggested_start_paths" not in result
