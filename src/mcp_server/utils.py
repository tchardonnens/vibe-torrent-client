"""Utility functions for the MCP server."""

from pathlib import Path


def format_size(size_bytes: int) -> str:
    """Format bytes into human-readable size."""
    size = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def resolve_torrent_path(torrent_path: str, default_torrents_dir: Path) -> Path:
    """
    Resolve a torrent path, checking default directory if not absolute.

    Args:
        torrent_path: The provided torrent path.
        default_torrents_dir: Default directory to check for torrents.

    Returns:
        Resolved Path object.

    Raises:
        FileNotFoundError: If the torrent file doesn't exist.
    """
    path = Path(torrent_path)

    if not path.is_absolute() and not path.exists():
        path = default_torrents_dir / torrent_path

    if not path.exists():
        raise FileNotFoundError(f"Torrent file not found: {torrent_path}")

    return path
