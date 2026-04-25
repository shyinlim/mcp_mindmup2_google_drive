import json
from typing import Dict, Any, List, Optional

from src.model.mindmup_model import MindmupNode, Mindmup
from src.utility.logger import get_logger

logger = get_logger(__name__)


class MindmupParser:

    @staticmethod
    def _parse_node(node_data: Dict[str, Any]) -> MindmupNode:
        """Parsing mindmup all node, and process tree structure (root and child)."""

        node_id = node_data.get('id', 'root')
        title = node_data.get('title', 'Untitled')

        children = []
        ideas = node_data.get('ideas', {})

        # Child node - mindmup's 'ideas'
        for key, child_data in ideas.items():
            if isinstance(child_data, dict):
                child_node = MindmupParser._parse_node(node_data=child_data)
                children.append(child_node)

        return MindmupNode(
            id=node_id,
            title=title,
            children=children,
            attribute=node_data.get('attr', {}),
            position=node_data.get('position', None)
        )

    @staticmethod
    def _parse_title_and_root_node(data: Dict[str, Any]) -> Mindmup:
        """Parse mindmup title and root node structure"""

        if 'title' in data:
            title = data['title']
        else:
            title = 'An untitled mindmap'

        root_node = MindmupParser._parse_node(data)

        return Mindmup(
            title=title,
            root_node=root_node,
            version=data.get('formatVersion', '1.0'),
            raw_data=data
        )

    @staticmethod
    def parse_content(content: str) -> Mindmup:
        """Parsing mindmup's all contents."""
        try:
            data = json.loads(content)
            return MindmupParser._parse_title_and_root_node(data=data)
        except json.JSONDecodeError as e:
            error_message = f'parse_content error: {e}'
            logger.error(error_message)
            raise ValueError(error_message)

    @staticmethod
    def render_tree_outline(
            node: MindmupNode,
            max_depth: int = 99,
            max_title_length: int = 80,
            max_children: int = 30,
            max_lines: int = 2000,
            path_prefix: str = "1",
    ) -> str:
        """Render full tree as indented text with node paths for navigation.

        Args:
            node: Root node to render.
            max_depth: Max depth to expand (deeper nodes shown as collapsed).
            max_title_length: Max chars per title line (truncated if longer).
            max_children: Max children per node to show before truncating.
            max_lines: Max total lines to render before truncating.
            path_prefix: Starting path label for the root of this render
                (e.g. "1" for whole tree, "1.2.3" when rendering a subtree
                at that path so children continue numbering correctly).
        """
        lines = []

        def _render(current: MindmupNode, prefix: str, indent: int) -> None:
            if len(lines) >= max_lines:
                return

            title_line = current.to_outline_line(max_title_length)

            # Skip empty-title nodes (visual dividers in MindMup) but still recurse into children
            if title_line.strip():
                if indent >= max_depth and current.children:
                    title_line += f" ({len(current.children)} children, collapsed)"
                lines.append(f"[{prefix}] {title_line}")

            if indent < max_depth:
                children_to_show = current.children[:max_children]
                for i, child in enumerate(children_to_show, start=1):
                    if len(lines) >= max_lines:
                        lines.append(f"[...] (output truncated at {max_lines} lines)")
                        return
                    _render(child, f"{prefix}.{i}", indent + 1)

                remaining = len(current.children) - len(children_to_show)
                if remaining > 0:
                    lines.append(f"[...] ... and {remaining} more")

        _render(node, path_prefix, 0)
        return "\n".join(lines)

    @staticmethod
    def find_node_by_path(root: MindmupNode, path: str) -> Optional[MindmupNode]:
        """Find node by path string, e.g. '1.2.3'.

        Path must start with '1' (root). Returns None for invalid paths.
        """
        if not path or not path.strip():
            return None

        parts = path.strip().split(".")
        if not parts or parts[0] != "1":
            return None

        current = root
        for part in parts[1:]:
            try:
                idx = int(part) - 1  # path is 1-based
            except ValueError:
                return None
            if idx < 0 or idx >= len(current.children):
                return None
            current = current.children[idx]

        return current

    @staticmethod
    def get_node_breadcrumb(root: MindmupNode, path: str) -> List[str]:
        """Get ancestor titles as context breadcrumb.

        Returns partial breadcrumb if path is partially valid.
        Empty/whitespace titles are filtered out (e.g. visual divider nodes).
        """
        if not path or not path.strip():
            return []

        parts = path.strip().split(".")
        if not parts or parts[0] != "1":
            return []

        titles = [root.to_outline_line()]
        current = root
        for part in parts[1:]:
            try:
                idx = int(part) - 1
            except ValueError:
                break
            if idx < 0 or idx >= len(current.children):
                break
            current = current.children[idx]
            titles.append(current.to_outline_line())

        return [t for t in titles if t.strip()]

    @staticmethod
    def get_section_stats(root: MindmupNode, path_prefix: str = "1") -> List[Dict[str, Any]]:
        """Stats for each top-level section.

        Returns list of dicts with keys:
        - path: node path like "1.2" for drill-down with get_mindmap_section
        - title: truncated title preview
        - node_count: total descendants + self
        - depth: max tree depth from this node
        - text_weight: sum of all title character counts (Python str len, not bytes/tokens).
                       Use relative comparison between sections to decide drill priority.
        """
        stats = []
        for i, child in enumerate(root.children, start=1):
            stats.append({
                "path": f"{path_prefix}.{i}",
                "title": child.to_outline_line(max_title_length=80),
                "node_count": 1 + sum(1 for _ in _iter_descendants(child)),
                "depth": child.get_depth(),
                "text_weight": child.get_text_weight(),
            })
        return stats

    @staticmethod
    def render_subtree_detail(
            node: MindmupNode,
            path_prefix: str = "1",
            ai_dict: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Detailed subtree for drill-down.

        Args:
            node: The MindmupNode at path_prefix.
            path_prefix: The path label (e.g. "1.2.3") matching node's location in the full tree.
            ai_dict: Optionally pass a pre-computed to_ai_dict() result to avoid recomputing.
                If None, computes fresh.
        """
        return {
            "path": path_prefix,
            "node": ai_dict if ai_dict is not None else node.to_ai_dict(),
            "node_count": 1 + sum(1 for _ in _iter_descendants(node)),
        }


def _iter_descendants(node: MindmupNode):
    """Yield all descendants of a node. Module-level helper, NOT inside MindmupParser."""
    for child in node.children:
        yield child
        yield from _iter_descendants(child)
