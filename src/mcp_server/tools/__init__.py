"""MCP tools for the BitTorrent client."""

from .download_tools import register_download_tools
from .file_tools import register_file_tools
from .torrent_tools import register_torrent_tools


def register_all_tools(mcp) -> None:
    """Register all MCP tools with the server."""
    register_torrent_tools(mcp)
    register_download_tools(mcp)
    register_file_tools(mcp)
