"""Torrent parsing and listing tools."""

from pathlib import Path

from torrent_parser import BencodeError, TorrentParser

from ..models import TorrentFileInfo, TorrentMetadata
from ..state import DEFAULT_TORRENTS_DIR
from ..utils import resolve_torrent_path


def register_torrent_tools(mcp) -> None:
    """Register torrent-related tools with the MCP server."""

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
            torrent_files.append(
                {
                    "path": str(file_path.absolute()),
                    "name": file_path.name,
                }
            )

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
        path = resolve_torrent_path(torrent_path, DEFAULT_TORRENTS_DIR)

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
        path = resolve_torrent_path(torrent_path, DEFAULT_TORRENTS_DIR)

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
        path = resolve_torrent_path(torrent_path, DEFAULT_TORRENTS_DIR)

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
        path = resolve_torrent_path(torrent_path, DEFAULT_TORRENTS_DIR)

        parser = TorrentParser(str(path))
        torrent = parser.parse()
        return torrent.get_announce_urls()
