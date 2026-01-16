"""Download management tools."""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from magnet import MagnetLink, is_magnet_link
from magnet_client import MetadataFetcher
from torrent_parser import TorrentParser

from ..models import DownloadStatus
from ..state import DEFAULT_DOWNLOADS_DIR, DEFAULT_TORRENTS_DIR, active_downloads
from ..utils import resolve_torrent_path


def register_download_tools(mcp) -> None:
    """Register download-related tools with the MCP server."""

    @mcp.tool()
    async def start_download(
        torrent_path: str,
        output_dir: str | None = None,
    ) -> dict[str, str]:
        """
        Start downloading a torrent in the background.

        Supports both .torrent file paths and magnet links.

        Args:
            torrent_path: Path to the .torrent file or a magnet link URI.
            output_dir: Directory to save downloaded files.
                        Defaults to 'downloads' folder in the project.

        Returns:
            Information about the started download including the info hash for tracking.
        """
        from client import TorrentClient

        output = Path(output_dir) if output_dir else DEFAULT_DOWNLOADS_DIR
        output.mkdir(parents=True, exist_ok=True)

        # Check if it's a magnet link
        if is_magnet_link(torrent_path):
            return await _start_magnet_download(torrent_path, output)

        # Handle regular torrent file
        path = resolve_torrent_path(torrent_path, DEFAULT_TORRENTS_DIR)

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
        client = TorrentClient(torrent_path=str(path), output_dir=str(output))

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

    async def _start_magnet_download(magnet_uri: str, output: Path) -> dict[str, str]:
        """
        Start downloading from a magnet link.

        Args:
            magnet_uri: The magnet URI
            output: Output directory

        Returns:
            Status information
        """
        from client import TorrentClient

        # Parse magnet link
        try:
            magnet = MagnetLink.parse(magnet_uri)
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to parse magnet link: {e}",
            }

        info_hash = magnet.info_hash_hex
        display_name = magnet.display_name or info_hash[:16]

        # Check if already downloading
        if info_hash in active_downloads:
            status = active_downloads[info_hash].get("status", "unknown")
            if status == "downloading":
                return {
                    "status": "already_downloading",
                    "info_hash": info_hash,
                    "name": display_name,
                    "message": "This torrent is already being downloaded",
                }

        # Track as fetching metadata
        active_downloads[info_hash] = {
            "client": None,
            "status": "fetching_metadata",
            "name": display_name,
            "magnet_uri": magnet_uri,
            "output_dir": str(output),
            "started_at": datetime.now().isoformat(),
        }

        # Start metadata fetch and download in background
        async def run_magnet_download() -> None:
            try:
                # Fetch metadata
                fetcher = MetadataFetcher(magnet)
                metadata = await fetcher.fetch()

                if not metadata:
                    active_downloads[info_hash]["status"] = "error"
                    active_downloads[info_hash]["error"] = "Failed to fetch metadata from peers"
                    return

                # Create parser from metadata
                parser = TorrentParser()
                parser.parse_from_metadata(metadata, trackers=magnet.trackers, info_hash=magnet.info_hash)

                # Update name if we got it from metadata
                if parser._torrent:
                    active_downloads[info_hash]["name"] = parser._torrent.name

                # Create client
                client = TorrentClient(parser=parser, output_dir=str(output), info_hash=magnet.info_hash)
                active_downloads[info_hash]["client"] = client
                active_downloads[info_hash]["status"] = "downloading"

                await client.start()
                active_downloads[info_hash]["status"] = "completed"

            except Exception as e:
                active_downloads[info_hash]["status"] = "error"
                active_downloads[info_hash]["error"] = str(e)

        asyncio.create_task(run_magnet_download())

        return {
            "status": "started",
            "info_hash": info_hash,
            "name": display_name,
            "output_dir": str(output),
            "message": f"Started fetching metadata for {display_name}",
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
