"""
MCP Server package for the BitTorrent client.

Exposes torrent management functionality via the Model Context Protocol.
"""

from .server import mcp

__all__ = ["mcp"]
