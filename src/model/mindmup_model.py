from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime


STICKER_LABELS = {
    "emoji:2705": "done",       # done
    "emoji:274C": "failed",     # failed
    "emoji:26A0": "warning",    # warning
    "emoji:2757": "important",  # important
    "emoji:1F534": "blocked",   # blocked
    "emoji:1F7E2": "active",    # active
    "emoji:1F7E1": "pending",   # pending
}


@dataclass
class MindmupNode:
    """A node in MindMup tree structure."""

    id: str
    title: str
    children: List['MindmupNode'] = field(default_factory=list)
    attribute: Dict[str, Any] = field(default_factory=dict)
    position: Optional[Dict[str, float]] = None

    def get_depth(self) -> int:
        """Get the depth of node (include all child node)."""
        if not self.children:
            return 1

        return 1 + max(child.get_depth() for child in self.children)

    def to_dict(self) -> Dict[str, Any]:
        """Full serialization including styling. Used by Phase 2b write tools (Plan 02).

        For AI-facing output, prefer to_ai_dict() which strips styling noise.
        """
        return {
            "id": self.id,
            "title": self.title,
            "children": [child.to_dict() for child in self.children],
            "attribute": self.attribute,
            "position": self.position
        }

    def to_outline_line(self, max_title_length: int = 80) -> str:
        """Single line representation for tree outline."""
        title = self.title[:max_title_length]
        if len(self.title) > max_title_length:
            title += "..."
        return title

    def get_text_weight(self) -> int:
        """Total text characters in this subtree."""
        weight = len(self.title)
        for child in self.children:
            weight += child.get_text_weight()
        return weight

    def to_ai_dict(self) -> Dict[str, Any]:
        """AI-friendly output: only meaningful fields, no styling noise.

        Strips: backgroundColor, width, fontMultiplier, position, text.color, id
        Keeps: title, children hierarchy, notes, semantic status from stickers

        Note: `id` (MindMup internal UUID, ~34 bytes/node) is stripped because
        AI navigates via node_path ("1.2.3"), not id. Removing it cuts roughly
        30-40% of the payload on large subtrees. Write operations should use
        to_dict() which keeps id.
        """
        result: Dict[str, Any] = {
            "title": self.title,
        }

        note = self.attribute.get('note') or {}
        note_text = note.get('text', '')
        if note_text:
            result["notes"] = note_text

        stickers = self.attribute.get('stickers') or []
        status_labels = []
        for s in stickers:
            label = STICKER_LABELS.get(s)
            if label:
                status_labels.append(label)
        if status_labels:
            result["status"] = status_labels if len(status_labels) > 1 else status_labels[0]

        if self.children:
            result["children"] = [c.to_ai_dict() for c in self.children]

        return result


@dataclass
class Mindmup:
    title: str
    root_node: MindmupNode
    version: str = '1.0'
    created_time: Optional[datetime] = None
    modified_time: Optional[datetime] = None
    author: Optional[str] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)

    @property
    def format_version(self) -> str:
        return self.version

    @property
    def id(self) -> str:
        return self.root_node.id

    def get_all_nodes(self) -> List[MindmupNode]:
        """Get all nodes in the mindmup (flattened list)."""
        nodes = []

        def collect_all_node(node: MindmupNode):
            """collect all node."""
            nodes.append(node)
            for child in node.children:
                collect_all_node(node=child)

        collect_all_node(self.root_node)
        return nodes

    def get_node_count(self) -> int:
        return len(self.get_all_nodes())
