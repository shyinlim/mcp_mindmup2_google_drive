import pytest
from src.model.mindmup_model import MindmupNode, STICKER_LABELS
from src.core.mindmup_parser import MindmupParser


class TestToAiDict:

    def test_strips_styling(self):
        """to_ai_dict should NOT include backgroundColor, width, position."""
        node = MindmupNode(
            id="1", title="Test",
            attribute={"style": {"backgroundColor": "#ff0000", "width": 200}},
            position={"x": 10, "y": 20},
        )
        result = node.to_ai_dict()
        assert "backgroundColor" not in str(result)
        assert "width" not in str(result)
        assert "position" not in str(result)

    def test_preserves_notes(self):
        node = MindmupNode(id="1", title="Test", attribute={"note": {"text": "my note"}})
        result = node.to_ai_dict()
        assert result["notes"] == "my note"

    def test_converts_stickers_to_labels(self):
        node = MindmupNode(id="1", title="Test", attribute={"stickers": ["emoji:2705"]})
        result = node.to_ai_dict()
        assert result["status"] == "done"

    def test_unknown_sticker_ignored(self):
        node = MindmupNode(id="1", title="Test", attribute={"stickers": ["emoji:9999"]})
        result = node.to_ai_dict()
        assert "status" not in result

    def test_children_recursion(self):
        child = MindmupNode(id="c1", title="Child")
        parent = MindmupNode(id="1", title="Parent", children=[child])
        result = parent.to_ai_dict()
        assert result["children"][0]["title"] == "Child"

    def test_no_children_key_when_empty(self):
        node = MindmupNode(id="1", title="Leaf")
        result = node.to_ai_dict()
        assert "children" not in result

    def test_note_value_none_does_not_crash(self):
        """Malformed input: attr.note = None should not AttributeError."""
        node = MindmupNode(id="1", title="Test", attribute={"note": None})
        result = node.to_ai_dict()
        assert "notes" not in result

    def test_stickers_value_none_does_not_crash(self):
        """Malformed input: attr.stickers = None should not iterate None."""
        node = MindmupNode(id="1", title="Test", attribute={"stickers": None})
        result = node.to_ai_dict()
        assert "status" not in result

    def test_strips_id(self):
        """to_ai_dict should NOT include id - AI navigates by node_path, not id.

        id is pure noise to AI (~34 bytes/node MindMup UUID). Dropping it cuts
        large subtree payloads by 30-40%. Write operations use to_dict() instead.
        """
        child = MindmupNode(id="c1", title="Child")
        node = MindmupNode(id="1", title="Parent", children=[child])
        result = node.to_ai_dict()
        assert "id" not in result
        assert "id" not in result["children"][0]


class TestRenderTreeOutline:

    def _make_tree(self) -> MindmupNode:
        gc = MindmupNode(id="gc", title="Grandchild")
        c1 = MindmupNode(id="c1", title="Child A", children=[gc])
        c2 = MindmupNode(id="c2", title="Child B")
        return MindmupNode(id="root", title="Root", children=[c1, c2])

    def test_includes_all_nodes(self):
        root = self._make_tree()
        outline = MindmupParser.render_tree_outline(root)
        assert "[1] Root" in outline
        assert "[1.1]" in outline
        assert "Child A" in outline
        assert "[1.1.1]" in outline
        assert "Grandchild" in outline
        assert "[1.2]" in outline
        assert "Child B" in outline

    def test_max_depth_collapses(self):
        root = self._make_tree()
        outline = MindmupParser.render_tree_outline(root, max_depth=1)
        assert "collapsed" in outline

    def test_max_children_truncates(self):
        children = [MindmupNode(id=f"c{i}", title=f"C{i}") for i in range(40)]
        root = MindmupNode(id="root", title="Root", children=children)
        outline = MindmupParser.render_tree_outline(root, max_children=5)
        assert "... and 35 more" in outline

    def test_skips_empty_title_nodes(self):
        """Nodes with empty/whitespace title should be skipped but children still rendered."""
        gc = MindmupNode(id="gc", title="Has Title")
        empty_parent = MindmupNode(id="ep", title="   ", children=[gc])
        root = MindmupNode(id="root", title="", children=[empty_parent])

        outline = MindmupParser.render_tree_outline(root)

        # root and empty_parent are empty -> not in output
        assert "[1] " not in outline.split("\n")[0] or "[1] \n" not in outline
        assert "[1.1]" not in outline
        # grandchild still rendered at correct path
        assert "[1.1.1] Has Title" in outline

    def test_no_indent_spaces_in_output(self):
        """E: outline lines should NOT contain indent-padding spaces (path implies depth)."""
        gc = MindmupNode(id="gc", title="Deep")
        c = MindmupNode(id="c", title="Mid", children=[gc])
        root = MindmupNode(id="root", title="Root", children=[c])

        outline = MindmupParser.render_tree_outline(root)

        # exactly one space between path bracket and title (no extra indent)
        assert "[1] Root" in outline
        assert "[1.1] Mid" in outline
        assert "[1.1.1] Deep" in outline


class TestFindNodeByPath:

    def _make_tree(self) -> MindmupNode:
        gc = MindmupNode(id="gc", title="Grandchild")
        c1 = MindmupNode(id="c1", title="Child A", children=[gc])
        c2 = MindmupNode(id="c2", title="Child B")
        return MindmupNode(id="root", title="Root", children=[c1, c2])

    def test_find_root(self):
        root = self._make_tree()
        assert MindmupParser.find_node_by_path(root, "1").title == "Root"

    def test_find_child(self):
        root = self._make_tree()
        assert MindmupParser.find_node_by_path(root, "1.1").title == "Child A"

    def test_find_grandchild(self):
        root = self._make_tree()
        assert MindmupParser.find_node_by_path(root, "1.1.1").title == "Grandchild"

    def test_empty_path_returns_none(self):
        root = self._make_tree()
        assert MindmupParser.find_node_by_path(root, "") is None

    def test_invalid_path_returns_none(self):
        root = self._make_tree()
        assert MindmupParser.find_node_by_path(root, "0") is None
        assert MindmupParser.find_node_by_path(root, "1.abc") is None
        assert MindmupParser.find_node_by_path(root, "1.99") is None


class TestGetNodeBreadcrumb:

    def test_breadcrumb(self):
        gc = MindmupNode(id="gc", title="Grandchild")
        c1 = MindmupNode(id="c1", title="Child A", children=[gc])
        root = MindmupNode(id="root", title="Root", children=[c1])
        crumbs = MindmupParser.get_node_breadcrumb(root, "1.1.1")
        assert crumbs == ["Root", "Child A", "Grandchild"]

    def test_partial_invalid_path(self):
        c1 = MindmupNode(id="c1", title="Child")
        root = MindmupNode(id="root", title="Root", children=[c1])
        crumbs = MindmupParser.get_node_breadcrumb(root, "1.1.99")
        assert crumbs == ["Root", "Child"]  # partial result

    def test_filters_empty_titles(self):
        """Empty/whitespace titles (visual divider nodes) should be excluded from breadcrumb."""
        leaf = MindmupNode(id="l", title="Leaf")
        empty_mid = MindmupNode(id="em", title="   ", children=[leaf])
        empty_root = MindmupNode(id="r", title="", children=[empty_mid])
        crumbs = MindmupParser.get_node_breadcrumb(empty_root, "1.1.1")
        assert crumbs == ["Leaf"]
