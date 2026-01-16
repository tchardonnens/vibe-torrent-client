"""
MCP Server package for the BitTorrent client.

Exposes torrent management functionality via the Model Context Protocol.
"""

import sys
from pathlib import Path

# Add src to path for imports when used as a package
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.server import mcp  # noqa: E402

__all__ = ["mcp"]
