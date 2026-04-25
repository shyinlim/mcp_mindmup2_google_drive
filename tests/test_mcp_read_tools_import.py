"""Smoke tests: verify mixin split didn't break imports or method resolution."""
from src.core.mcp_server import MCPServer
from src.core.mcp_read_tools import ReadToolsMixin


def test_read_tools_mixin_importable():
    """ReadToolsMixin can be imported without errors."""
    assert ReadToolsMixin is not None


def test_mcpserver_inherits_read_tools_mixin():
    """MCPServer inherits ReadToolsMixin."""
    assert issubclass(MCPServer, ReadToolsMixin)


def test_mcpserver_has_tool_methods():
    """MCPServer has all read tool methods from the mixin."""
    for method_name in ['list_files', 'read_mindmap', 'search_mindmap',
                        'get_mindmap_section', '_process_mindmup_content']:
        assert hasattr(MCPServer, method_name), f"Missing method: {method_name}"
