"""Shared state for the MCP server."""

from pathlib import Path
from typing import Any

# Default directories
DEFAULT_TORRENTS_DIR = Path(__file__).parent.parent.parent / "torrents"
DEFAULT_DOWNLOADS_DIR = Path(__file__).parent.parent.parent / "downloads"

# Active downloads tracking
# Key: info_hash, Value: dict with client, status, name, path, output_dir, started_at, error
active_downloads: dict[str, dict[str, Any]] = {}
