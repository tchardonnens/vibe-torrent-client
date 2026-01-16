"""
MCP Server for the BitTorrent client.

Exposes torrent management functionality via the Model Context Protocol.
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from pydantic import BaseModel

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from torrent_parser import TorrentParser, BencodeError

# Initialize FastMCP server
mcp = FastMCP(
    "Vibe Torrent Client",
    instructions="A BitTorrent client MCP server for managing torrent downloads. "
    "Use the available tools to parse torrent files, start downloads, monitor progress, and manage downloads.",
)

# Default directories
DEFAULT_TORRENTS_DIR = Path(__file__).parent.parent / "torrents"
DEFAULT_DOWNLOADS_DIR = Path(__file__).parent.parent / "downloads"

# Active downloads tracking
active_downloads: dict[str, dict[str, Any]] = {}


class TorrentFileInfo(BaseModel):
    """Information about a file in a torrent."""

    path: str
    size_bytes: int
    size_formatted: str


class TorrentMetadata(BaseModel):
    """Metadata extracted from a torrent file."""

    name: str
    info_hash: str
    total_size_bytes: int
    total_size_formatted: str
    piece_length: int
    piece_count: int
    files: list[TorrentFileInfo]
    announce_urls: list[str]
    creation_date: datetime | None = None
    created_by: str | None = None
    comment: str | None = None


class DownloadStatus(BaseModel):
    """Status of an active download."""

    torrent_name: str
    info_hash: str
    status: str  # "downloading", "completed", "paused", "error"
    progress_percent: float
    completed_pieces: int
    total_pieces: int
    downloaded_bytes: int
    total_bytes: int
    active_peers: int
    total_peers: int
    download_speed: str | None = None
    error_message: str | None = None


def _format_size(size_bytes: int) -> str:
    """Format bytes into human-readable size."""
    size = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


@mcp.tool()
def list_torrent_files(
    directory: str | None = None,
) -> list[dict[str, str]]:
    """
    List all .torrent files in a directory.

    Args:
        directory: Path to directory containing .torrent files.
                   Defaults to the 'torrents' folder in the project.

    Returns:
        List of torrent files with their paths and names.
    """
    torrents_dir = Path(directory) if directory else DEFAULT_TORRENTS_DIR

    if not torrents_dir.exists():
        return []

    torrent_files = []
    for file_path in torrents_dir.glob("*.torrent"):
        torrent_files.append({
            "path": str(file_path.absolute()),
            "name": file_path.name,
        })

    return torrent_files


@mcp.tool()
def parse_torrent(
    torrent_path: str,
) -> TorrentMetadata:
    """
    Parse a .torrent file and extract its metadata.

    Args:
        torrent_path: Path to the .torrent file to parse.

    Returns:
        Detailed metadata about the torrent including name, size, files, trackers, etc.
    """
    path = Path(torrent_path)

    # Try to resolve relative to torrents dir if not absolute
    if not path.is_absolute() and not path.exists():
        path = DEFAULT_TORRENTS_DIR / torrent_path

    if not path.exists():
        raise FileNotFoundError(f"Torrent file not found: {torrent_path}")

    try:
        parser = TorrentParser(str(path))
        torrent = parser.parse()

        files = [
            TorrentFileInfo(
                path=f.full_path,
                size_bytes=f.length,
                size_formatted=f.format_size(),
            )
            for f in torrent.get_files()
        ]

        return TorrentMetadata(
            name=torrent.name,
            info_hash=parser.get_info_hash(),
            total_size_bytes=torrent.total_size,
            total_size_formatted=torrent.format_size(),
            piece_length=torrent.piece_length,
            piece_count=torrent.piece_count,
            files=files,
            announce_urls=torrent.get_announce_urls(),
            creation_date=torrent.creation_datetime,
            created_by=torrent.created_by,
            comment=torrent.comment,
        )
    except BencodeError as e:
        raise ValueError(f"Failed to parse torrent file: {e}") from e


@mcp.tool()
def get_torrent_info_hash(
    torrent_path: str,
) -> str:
    """
    Get the info hash of a torrent file.

    The info hash is a unique identifier for the torrent, used by trackers
    and peers to identify the content.

    Args:
        torrent_path: Path to the .torrent file.

    Returns:
        The SHA-1 info hash as a hexadecimal string.
    """
    path = Path(torrent_path)

    if not path.is_absolute() and not path.exists():
        path = DEFAULT_TORRENTS_DIR / torrent_path

    if not path.exists():
        raise FileNotFoundError(f"Torrent file not found: {torrent_path}")

    parser = TorrentParser(str(path))
    parser.parse()
    return parser.get_info_hash()


@mcp.tool()
def get_torrent_files(
    torrent_path: str,
) -> list[TorrentFileInfo]:
    """
    Get the list of files contained in a torrent.

    Args:
        torrent_path: Path to the .torrent file.

    Returns:
        List of files with their paths and sizes.
    """
    path = Path(torrent_path)

    if not path.is_absolute() and not path.exists():
        path = DEFAULT_TORRENTS_DIR / torrent_path

    if not path.exists():
        raise FileNotFoundError(f"Torrent file not found: {torrent_path}")

    parser = TorrentParser(str(path))
    torrent = parser.parse()

    return [
        TorrentFileInfo(
            path=f.full_path,
            size_bytes=f.length,
            size_formatted=f.format_size(),
        )
        for f in torrent.get_files()
    ]


@mcp.tool()
def get_torrent_trackers(
    torrent_path: str,
) -> list[str]:
    """
    Get the list of tracker URLs from a torrent file.

    Trackers are servers that help peers find each other to share the torrent.

    Args:
        torrent_path: Path to the .torrent file.

    Returns:
        List of tracker announce URLs.
    """
    path = Path(torrent_path)

    if not path.is_absolute() and not path.exists():
        path = DEFAULT_TORRENTS_DIR / torrent_path

    if not path.exists():
        raise FileNotFoundError(f"Torrent file not found: {torrent_path}")

    parser = TorrentParser(str(path))
    torrent = parser.parse()
    return torrent.get_announce_urls()


@mcp.tool()
async def start_download(
    torrent_path: str,
    output_dir: str | None = None,
) -> dict[str, str]:
    """
    Start downloading a torrent in the background.

    Args:
        torrent_path: Path to the .torrent file to download.
        output_dir: Directory to save downloaded files.
                    Defaults to 'downloads' folder in the project.

    Returns:
        Information about the started download including the info hash for tracking.
    """
    from client import TorrentClient

    path = Path(torrent_path)

    if not path.is_absolute() and not path.exists():
        path = DEFAULT_TORRENTS_DIR / torrent_path

    if not path.exists():
        raise FileNotFoundError(f"Torrent file not found: {torrent_path}")

    output = Path(output_dir) if output_dir else DEFAULT_DOWNLOADS_DIR
    output.mkdir(parents=True, exist_ok=True)

    # Parse to get info hash
    parser = TorrentParser(str(path))
    torrent = parser.parse()
    info_hash = parser.get_info_hash()

    # Check if already downloading
    if info_hash in active_downloads:
        status = active_downloads[info_hash].get("status", "unknown")
        if status == "downloading":
            return {
                "status": "already_downloading",
                "info_hash": info_hash,
                "name": torrent.name,
                "message": "This torrent is already being downloaded",
            }

    # Create client
    client = TorrentClient(str(path), str(output))

    # Track the download
    active_downloads[info_hash] = {
        "client": client,
        "status": "starting",
        "name": torrent.name,
        "path": str(path),
        "output_dir": str(output),
        "started_at": datetime.now().isoformat(),
    }

    # Start download in background
    async def run_download() -> None:
        try:
            active_downloads[info_hash]["status"] = "downloading"
            await client.start()
            active_downloads[info_hash]["status"] = "completed"
        except Exception as e:
            active_downloads[info_hash]["status"] = "error"
            active_downloads[info_hash]["error"] = str(e)

    asyncio.create_task(run_download())

    return {
        "status": "started",
        "info_hash": info_hash,
        "name": torrent.name,
        "output_dir": str(output),
        "message": f"Started downloading {torrent.name}",
    }


@mcp.tool()
async def get_download_status(
    info_hash: str | None = None,
) -> list[DownloadStatus]:
    """
    Get the status of active downloads.

    Args:
        info_hash: Specific info hash to check. If None, returns all active downloads.

    Returns:
        List of download status information.
    """
    results = []

    downloads_to_check = (
        {info_hash: active_downloads[info_hash]}
        if info_hash and info_hash in active_downloads
        else active_downloads
    )

    for hash_id, download_info in downloads_to_check.items():
        client = download_info.get("client")
        status = download_info.get("status", "unknown")

        if client and client.piece_manager:
            completed, total, percentage = client.piece_manager.get_progress()
            completed_bytes = await client.piece_manager.get_completed_bytes()

            total_bytes = client.parser.get_total_size() if client.parser else 0

            results.append(DownloadStatus(
                torrent_name=download_info.get("name", "Unknown"),
                info_hash=hash_id,
                status=status,
                progress_percent=percentage,
                completed_pieces=completed,
                total_pieces=total,
                downloaded_bytes=completed_bytes,
                total_bytes=total_bytes,
                active_peers=len(client.active_peers) if client else 0,
                total_peers=len(client.peers) if client else 0,
                download_speed=f"{client._calculate_pieces_per_second():.2f} pieces/s" if client else None,
                error_message=download_info.get("error"),
            ))
        else:
            results.append(DownloadStatus(
                torrent_name=download_info.get("name", "Unknown"),
                info_hash=hash_id,
                status=status,
                progress_percent=0.0,
                completed_pieces=0,
                total_pieces=0,
                downloaded_bytes=0,
                total_bytes=0,
                active_peers=0,
                total_peers=0,
                error_message=download_info.get("error"),
            ))

    return results


@mcp.tool()
def stop_download(
    info_hash: str,
) -> dict[str, str]:
    """
    Stop an active download.

    Args:
        info_hash: The info hash of the torrent to stop.

    Returns:
        Status of the stop operation.
    """
    if info_hash not in active_downloads:
        return {
            "status": "error",
            "message": f"No active download found with info hash: {info_hash}",
        }

    download_info = active_downloads[info_hash]
    client = download_info.get("client")

    if client:
        client.stop()
        active_downloads[info_hash]["status"] = "stopped"

    return {
        "status": "stopped",
        "info_hash": info_hash,
        "name": download_info.get("name", "Unknown"),
        "message": "Download stopped successfully",
    }


@mcp.tool()
def list_active_downloads() -> list[dict[str, Any]]:
    """
    List all active and recent downloads.

    Returns:
        List of downloads with their basic information and status.
    """
    return [
        {
            "info_hash": hash_id,
            "name": info.get("name", "Unknown"),
            "status": info.get("status", "unknown"),
            "started_at": info.get("started_at"),
            "output_dir": info.get("output_dir"),
            "error": info.get("error"),
        }
        for hash_id, info in active_downloads.items()
    ]


@mcp.tool()
def list_downloaded_files(
    directory: str | None = None,
) -> list[dict[str, Any]]:
    """
    List files in the downloads directory.

    Args:
        directory: Path to check. Defaults to the 'downloads' folder.

    Returns:
        List of downloaded files with their sizes.
    """
    downloads_dir = Path(directory) if directory else DEFAULT_DOWNLOADS_DIR

    if not downloads_dir.exists():
        return []

    files = []
    for item in downloads_dir.iterdir():
        if item.is_file():
            size = item.stat().st_size
            files.append({
                "name": item.name,
                "path": str(item.absolute()),
                "size_bytes": size,
                "size_formatted": _format_size(size),
            })
        elif item.is_dir():
            # Calculate total size of directory
            total_size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
            files.append({
                "name": item.name,
                "path": str(item.absolute()),
                "type": "directory",
                "size_bytes": total_size,
                "size_formatted": _format_size(total_size),
            })

    return files


# Resources for browsing torrents and downloads

@mcp.resource("torrents://list")
def resource_list_torrents() -> str:
    """List all available torrent files."""
    torrents = list_torrent_files()
    if not torrents:
        return "No torrent files found in the torrents directory."

    lines = ["# Available Torrent Files\n"]
    for t in torrents:
        lines.append(f"- **{t['name']}**")
        lines.append(f"  Path: `{t['path']}`\n")

    return "\n".join(lines)


@mcp.resource("downloads://list")
def resource_list_downloads() -> str:
    """List all downloaded files."""
    files = list_downloaded_files()
    if not files:
        return "No downloaded files found."

    lines = ["# Downloaded Files\n"]
    for f in files:
        file_type = f.get("type", "file")
        lines.append(f"- **{f['name']}** ({file_type})")
        lines.append(f"  Size: {f['size_formatted']}")
        lines.append(f"  Path: `{f['path']}`\n")

    return "\n".join(lines)


@mcp.resource("downloads://active")
async def resource_active_downloads() -> str:
    """Show status of all active downloads."""
    downloads = await get_download_status()
    if not downloads:
        return "No active downloads."

    lines = ["# Active Downloads\n"]
    for d in downloads:
        lines.append(f"## {d.torrent_name}")
        lines.append(f"- **Status**: {d.status}")
        lines.append(f"- **Progress**: {d.progress_percent:.1f}%")
        lines.append(f"- **Pieces**: {d.completed_pieces}/{d.total_pieces}")
        lines.append(f"- **Downloaded**: {_format_size(d.downloaded_bytes)}/{_format_size(d.total_bytes)}")
        lines.append(f"- **Peers**: {d.active_peers} active / {d.total_peers} total")
        if d.download_speed:
            lines.append(f"- **Speed**: {d.download_speed}")
        if d.error_message:
            lines.append(f"- **Error**: {d.error_message}")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
