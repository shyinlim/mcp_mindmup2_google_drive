import os
import sys

from src.core.mcp_server import MCPServer
from src.utility.logger import get_logger

logger = get_logger(__name__)


# Module-level instances. Two reasons to construct them here (not inside main):
# 1. `fastmcp run run.py:mcp --reload` (used by docker-compose-dev) imports this
#    module and looks up `mcp` to start the server.
# 2. `python3 run.py` (used by prod) goes through main() below.
mcp_server = MCPServer(
    name='TestCase MCP Server',
    host='0.0.0.0',
    port=9805,
)
mcp = mcp_server.mcp  # FastMCP instance for `fastmcp run` CLI


def main():
    """Starting the server (used by `python3 run.py`, e.g. prod).

    Google Drive credential is now provided per-request via X-Google-Credential header.
    Each user sets their own base64 encoded service account JSON in mcp.json headers.
    """
    try:
        # MCP Client mode | stdio, sse, streamable-http
        transport = os.getenv('MCP_TRANSPORT', 'sse')
        logger.info(f'Starting server in {transport} mode.')
        logger.info('Credential is provided per-request via X-Google-Credential header.')
        mcp_server.start(transport=transport)

    except KeyboardInterrupt:
        logger.info('Server stopped by user.')
    except Exception as e:
        logger.error(f'Server error: {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()
