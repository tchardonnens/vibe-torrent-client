"""
Main MCP server setup and entry point.

This module initializes the FastMCP server and registers all tools and resources.
"""

import sys
from pathlib import Path

from fastmcp import FastMCP

from .resources import register_resources
from .tools import register_all_tools

# Add src to path for imports (needed for torrent_parser imports)
sys.path.insert(0, str(Path(__file__).parent.parent))

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
