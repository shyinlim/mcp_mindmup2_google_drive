from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime


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
        return {
            "id": self.id,
            "title": self.title,
            "children": [child.to_dict() for child in self.children],
            "attribute": self.attribute,
            "position": self.position
        }


@dataclass
class Mindmup:
    title: str
    root_node: MindmupNode
    version: str = '1.0'
    created_time: Optional[datetime] = None
    modified_time: Optional[datetime] = None
    author: Optional[str] = None
    description: Optional[str] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)

    @property
    def format_version(self) -> str:
        return self.version

    @property
    def id(self) -> str:
        return self.root_node.id

    def __post_init__(self):
        if self.created_time is None:
            self.created_time = datetime.now()
        if self.modified_time is None:
            self.modified_time = datetime.now()

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

    def get_max_depth(self) -> int:
        return self.root_node.get_depth()

    def extract_text_content(self) -> List[str]:
        """Extract all text content from nodes."""
        text = []

        def collect_text(node: MindmupNode):
            text.append(node.title)
            for child in node.children:
                collect_text(node=child)

        collect_text(self.root_node)
        return text
