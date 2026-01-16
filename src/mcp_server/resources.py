"""MCP resources for browsing torrents and downloads."""

from .models import DownloadStatus
from .state import DEFAULT_DOWNLOADS_DIR, DEFAULT_TORRENTS_DIR, active_downloads
from .utils import format_size


def register_resources(mcp) -> None:
    """Register all MCP resources with the server."""

    @mcp.resource("torrents://list")
    def resource_list_torrents() -> str:
        """List all available torrent files."""
        torrents_dir = DEFAULT_TORRENTS_DIR

        if not torrents_dir.exists():
            return "No torrent files found in the torrents directory."

        torrent_files = []
        for file_path in torrents_dir.glob("*.torrent"):
            torrent_files.append(
                {
                    "path": str(file_path.absolute()),
                    "name": file_path.name,
                }
            )

        if not torrent_files:
            return "No torrent files found in the torrents directory."

        lines = ["# Available Torrent Files\n"]
        for t in torrent_files:
            lines.append(f"- **{t['name']}**")
            lines.append(f"  Path: `{t['path']}`\n")

        return "\n".join(lines)

    @mcp.resource("downloads://list")
    def resource_list_downloads() -> str:
        """List all downloaded files."""
        downloads_dir = DEFAULT_DOWNLOADS_DIR

        if not downloads_dir.exists():
            return "No downloaded files found."

        files = []
        for item in downloads_dir.iterdir():
            if item.is_file():
                size = item.stat().st_size
                files.append(
                    {
                        "name": item.name,
                        "path": str(item.absolute()),
                        "size_bytes": size,
                        "size_formatted": format_size(size),
                    }
                )
            elif item.is_dir():
                total_size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                files.append(
                    {
                        "name": item.name,
                        "path": str(item.absolute()),
                        "type": "directory",
                        "size_bytes": total_size,
                        "size_formatted": format_size(total_size),
                    }
                )

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
        results = []

        for hash_id, download_info in active_downloads.items():
            client = download_info.get("client")
            status = download_info.get("status", "unknown")

            if client and client.piece_manager:
                completed, total, percentage = client.piece_manager.get_progress()
                completed_bytes = await client.piece_manager.get_completed_bytes()
                total_bytes = client.parser.get_total_size() if client.parser else 0

                results.append(
                    DownloadStatus(
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
                    )
                )
            else:
                results.append(
                    DownloadStatus(
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
                    )
                )

        if not results:
            return "No active downloads."

        lines = ["# Active Downloads\n"]
        for d in results:
            lines.append(f"## {d.torrent_name}")
            lines.append(f"- **Status**: {d.status}")
            lines.append(f"- **Progress**: {d.progress_percent:.1f}%")
            lines.append(f"- **Pieces**: {d.completed_pieces}/{d.total_pieces}")
            lines.append(f"- **Downloaded**: {format_size(d.downloaded_bytes)}/{format_size(d.total_bytes)}")
            lines.append(f"- **Peers**: {d.active_peers} active / {d.total_peers} total")
            if d.download_speed:
                lines.append(f"- **Speed**: {d.download_speed}")
            if d.error_message:
                lines.append(f"- **Error**: {d.error_message}")
            lines.append("")

        return "\n".join(lines)
