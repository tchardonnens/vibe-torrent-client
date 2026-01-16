"""
Main MCP server setup and entry point.

This module initializes the FastMCP server and registers all tools and resources.
"""

import sys
from pathlib import Path

# Add src to path for imports (needed for torrent_parser and mcp_server imports)
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastmcp import FastMCP  # noqa: E402

from mcp_server.resources import register_resources  # noqa: E402
from mcp_server.tools import register_all_tools  # noqa: E402

# Initialize FastMCP server
mcp = FastMCP(
    "Vibe Torrent Client",
    instructions="A BitTorrent client MCP server for managing torrent downloads. "
    "Use the available tools to parse torrent files, start downloads, monitor progress, and manage downloads.",
)

# Register all tools and resources
register_all_tools(mcp)
register_resources(mcp)


def main() -> None:
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
