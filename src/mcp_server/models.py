"""Pydantic models for the MCP server."""

from datetime import datetime

from pydantic import BaseModel


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


class MagnetInfo(BaseModel):
    """Information parsed from a magnet link."""

    info_hash: str
    display_name: str | None = None
    trackers: list[str] = []
    exact_length: int | None = None
    web_seeds: list[str] = []
