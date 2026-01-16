"""
A .torrent file parser that decodes bencoded data and extracts torrent metadata.
Uses Pydantic for structured data validation and type safety.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, computed_field, model_validator


class BencodeError(Exception):
    """Exception raised for bencode parsing errors."""

    pass


class TorrentFile(BaseModel):
    """Represents a single file in a torrent."""

    length: int = Field(ge=0, description="File size in bytes")
    path: list[str] = Field(description="Path components for the file")

    @computed_field
    @property
    def full_path(self) -> str:
        """Get the full path as a string."""
        return "/".join(self.path)

    def format_size(self) -> str:
        """Format the file size as human-readable string."""
        return _format_size(self.length)


class TorrentInfo(BaseModel):
    """The 'info' dictionary from a torrent file."""

    name: str = Field(description="Name of the torrent (file or directory)")
    piece_length: int = Field(alias="piece length", ge=1, description="Size of each piece in bytes")
    pieces: bytes = Field(description="Concatenated SHA-1 hashes of all pieces")
    length: int | None = Field(default=None, ge=0, description="Total length for single-file torrents")
    files: list[TorrentFile] | None = Field(default=None, description="List of files for multi-file torrents")
    private: int | None = Field(default=None, description="Private torrent flag")

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def decode_bytes_fields(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Decode bytes fields to strings where appropriate."""
        if isinstance(data.get("name"), bytes):
            data["name"] = data["name"].decode("utf-8", errors="replace")

        # Handle files list - only process if they are raw dicts from bencode parsing
        if "files" in data and data["files"]:
            decoded_files = []
            for file_info in data["files"]:
                # Skip if already a TorrentFile instance
                if isinstance(file_info, TorrentFile):
                    decoded_files.append(file_info)
                    continue

                path = file_info.get("path", [])
                if isinstance(path, list):
                    path = [p.decode("utf-8", errors="replace") if isinstance(p, bytes) else str(p) for p in path]
                decoded_files.append({"length": file_info.get("length", 0), "path": path})
            data["files"] = decoded_files

        return data

    @computed_field
    @property
    def piece_count(self) -> int:
        """Get the number of pieces (each SHA-1 hash is 20 bytes)."""
        return len(self.pieces) // 20

    @computed_field
    @property
    def total_size(self) -> int:
        """Get the total size of all files."""
        if self.length is not None:
            return self.length
        if self.files:
            return sum(f.length for f in self.files)
        return 0

    @computed_field
    @property
    def is_single_file(self) -> bool:
        """Check if this is a single-file torrent."""
        return self.length is not None

    def get_files(self) -> list[TorrentFile]:
        """Get the list of files in the torrent."""
        if self.files:
            return self.files
        # Single file torrent
        return [TorrentFile(length=self.length or 0, path=[self.name])]

    def get_piece_hash(self, piece_index: int) -> bytes:
        """Get the SHA-1 hash for a specific piece."""
        if piece_index < 0 or piece_index >= self.piece_count:
            raise IndexError(f"Piece index {piece_index} out of range (0-{self.piece_count - 1})")
        start = piece_index * 20
        return self.pieces[start : start + 20]


class Torrent(BaseModel):
    """Complete torrent metadata."""

    info: TorrentInfo = Field(description="The info dictionary")
    announce: str | None = Field(default=None, description="Primary tracker URL")
    announce_list: list[list[str]] | None = Field(
        default=None, alias="announce-list", description="Tiered list of tracker URLs"
    )
    creation_date: int | None = Field(default=None, alias="creation date", description="Creation timestamp")
    comment: str | None = Field(default=None, description="Optional comment")
    created_by: str | None = Field(default=None, alias="created by", description="Creator software")
    encoding: str | None = Field(default=None, description="String encoding used")

    # Store raw info dict for hash calculation
    _raw_info: dict[str, Any] | None = None

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def decode_bytes_fields(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Decode bytes fields to strings where appropriate."""
        if isinstance(data.get("announce"), bytes):
            data["announce"] = data["announce"].decode("utf-8", errors="replace")

        if isinstance(data.get("comment"), bytes):
            data["comment"] = data["comment"].decode("utf-8", errors="replace")

        if isinstance(data.get("created by"), bytes):
            data["created by"] = data["created by"].decode("utf-8", errors="replace")

        if isinstance(data.get("encoding"), bytes):
            data["encoding"] = data["encoding"].decode("utf-8", errors="replace")

        # Handle announce-list (list of lists of bytes)
        if "announce-list" in data and data["announce-list"]:
            decoded_list = []
            for tier in data["announce-list"]:
                if isinstance(tier, list):
                    decoded_tier = []
                    for url in tier:
                        if isinstance(url, bytes):
                            decoded_tier.append(url.decode("utf-8", errors="replace"))
                        else:
                            decoded_tier.append(str(url))
                    decoded_list.append(decoded_tier)
            data["announce-list"] = decoded_list

        return data

    @computed_field
    @property
    def name(self) -> str:
        """Get the torrent name."""
        return self.info.name

    @computed_field
    @property
    def total_size(self) -> int:
        """Get total size in bytes."""
        return self.info.total_size

    @computed_field
    @property
    def piece_length(self) -> int:
        """Get piece length in bytes."""
        return self.info.piece_length

    @computed_field
    @property
    def piece_count(self) -> int:
        """Get number of pieces."""
        return self.info.piece_count

    @computed_field
    @property
    def creation_datetime(self) -> datetime | None:
        """Get creation date as datetime object."""
        if self.creation_date:
            return datetime.fromtimestamp(self.creation_date)
        return None

    def get_announce_urls(self) -> list[str]:
        """Get all unique announce URLs."""
        urls: list[str] = []

        if self.announce:
            urls.append(self.announce)

        if self.announce_list:
            for tier in self.announce_list:
                for url in tier:
                    if url not in urls:
                        urls.append(url)

        return urls

    def get_files(self) -> list[TorrentFile]:
        """Get the list of files."""
        return self.info.get_files()

    def format_size(self) -> str:
        """Format total size as human-readable string."""
        return _format_size(self.total_size)

    def print_summary(self) -> None:
        """Print a human-readable summary of the torrent."""
        print(f"Torrent: {self.name}")
        print(f"Total Size: {self.format_size()}")
        print(f"Piece Length: {_format_size(self.piece_length)}")
        print(f"Number of Pieces: {self.piece_count}")

        if self.creation_datetime:
            print(f"Creation Date: {self.creation_datetime}")

        if self.created_by:
            print(f"Created By: {self.created_by}")

        if self.comment:
            print(f"Comment: {self.comment}")

        urls = self.get_announce_urls()
        print(f"\nAnnounce URLs ({len(urls)}):")
        for url in urls:
            print(f"  - {url}")

        files = self.get_files()
        print(f"\nFiles ({len(files)}):")
        for i, file in enumerate(files, 1):
            print(f"  {i}. {file.full_path} ({file.format_size()})")


class TorrentParser:
    """Parser for .torrent files using bencode format."""

    def __init__(self, torrent_path: str | Path | None = None) -> None:
        """
        Initialize the parser with a torrent file path.

        Args:
            torrent_path: Path to the .torrent file (optional for magnet links)
        """
        self.torrent_path = Path(torrent_path) if torrent_path else None
        if self.torrent_path and not self.torrent_path.exists():
            raise FileNotFoundError(f"Torrent file not found: {torrent_path}")

        self._raw_data: bytes = b""
        self._raw_dict: dict[str, Any] | None = None
        self._torrent: Torrent | None = None
        self._info_hash_override: bytes | None = None

    def parse(self) -> Torrent:
        """
        Parse the torrent file and return a Torrent model.

        Returns:
            Torrent model containing all parsed data
        """
        if self.torrent_path is None:
            raise BencodeError("No torrent file path specified")

        with open(self.torrent_path, "rb") as f:
            self._raw_data = f.read()

        data, _ = self._decode_bencode(self._raw_data, 0)
        if not isinstance(data, dict):
            raise BencodeError("Torrent file must start with a dictionary")

        self._raw_dict = data
        self._torrent = Torrent.model_validate(data)
        return self._torrent

    def parse_from_metadata(
        self, metadata: bytes, trackers: list[str] | None = None, info_hash: bytes | None = None
    ) -> Torrent:
        """
        Parse torrent metadata from bytes (used for magnet links).

        Args:
            metadata: Bencoded info dictionary bytes
            trackers: Optional list of tracker URLs
            info_hash: Optional pre-computed info hash for verification

        Returns:
            Torrent model containing parsed data
        """
        # Decode the info dictionary
        info_dict, _ = self._decode_bencode(metadata, 0)
        if not isinstance(info_dict, dict):
            raise BencodeError("Metadata must be a dictionary")

        # Verify hash if provided
        if info_hash:
            computed_hash = hashlib.sha1(metadata).digest()
            if computed_hash != info_hash:
                raise BencodeError("Info hash verification failed")
            self._info_hash_override = info_hash

        # Build a complete torrent dict
        torrent_dict: dict[str, Any] = {"info": info_dict}

        # Add trackers
        if trackers:
            torrent_dict["announce"] = trackers[0]
            if len(trackers) > 1:
                torrent_dict["announce-list"] = [[tr] for tr in trackers]

        self._raw_dict = torrent_dict
        self._torrent = Torrent.model_validate(torrent_dict)
        return self._torrent

    @property
    def torrent(self) -> Torrent:
        """Get the parsed Torrent model, parsing if needed."""
        if self._torrent is None:
            self.parse()
        return self._torrent  # type: ignore

    def _decode_bencode(self, data: bytes, index: int) -> tuple[Any, int]:
        """
        Decode bencoded data recursively.

        Args:
            data: The raw bytes to decode
            index: Current position in the data

        Returns:
            Tuple of (decoded_value, new_index)
        """
        if index >= len(data):
            raise BencodeError(f"Unexpected end of data at index {index}")

        char = data[index : index + 1]

        # Integer: i<number>e
        if char == b"i":
            end_index = data.find(b"e", index + 1)
            if end_index == -1:
                raise BencodeError(f"Unterminated integer at index {index}")
            try:
                value = int(data[index + 1 : end_index])
                return value, end_index + 1
            except ValueError as e:
                raise BencodeError(f"Invalid integer at index {index}") from e

        # List: l<elements>e
        elif char == b"l":
            index += 1
            result: list[Any] = []
            while index < len(data) and data[index : index + 1] != b"e":
                value, index = self._decode_bencode(data, index)
                result.append(value)
            if index >= len(data):
                raise BencodeError(f"Unterminated list at index {index}")
            return result, index + 1

        # Dictionary: d<key-value pairs>e
        elif char == b"d":
            index += 1
            result_dict: dict[Any, Any] = {}
            while index < len(data) and data[index : index + 1] != b"e":
                key, index = self._decode_bencode(data, index)
                value, index = self._decode_bencode(data, index)
                # Convert dictionary keys from bytes to strings (bencode spec)
                if isinstance(key, bytes):
                    key = key.decode("utf-8", errors="replace")
                result_dict[key] = value
            if index >= len(data):
                raise BencodeError(f"Unterminated dictionary at index {index}")
            return result_dict, index + 1

        # String: <length>:<data>
        elif char.isdigit():
            colon_index = data.find(b":", index)
            if colon_index == -1:
                raise BencodeError(f"No colon found for string at index {index}")
            try:
                length = int(data[index:colon_index])
            except ValueError as e:
                raise BencodeError(f"Invalid string length at index {index}") from e

            start_index = colon_index + 1
            end_index = start_index + length
            if end_index > len(data):
                raise BencodeError(f"String length exceeds data at index {index}")

            value = data[start_index:end_index]
            return value, end_index

        else:
            raise BencodeError(f"Unexpected character '{char.decode('latin-1', errors='replace')}' at index {index}")

    def _encode_bencode(self, value: Any) -> bytes:
        """
        Encode a Python value to bencode format.

        Args:
            value: The value to encode

        Returns:
            Bencoded bytes
        """
        if isinstance(value, int):
            return f"i{value}e".encode()
        elif isinstance(value, bytes):
            return f"{len(value)}:".encode() + value
        elif isinstance(value, str):
            value_bytes = value.encode("utf-8")
            return f"{len(value_bytes)}:".encode() + value_bytes
        elif isinstance(value, list):
            result = b"l"
            for item in value:
                result += self._encode_bencode(item)
            result += b"e"
            return result
        elif isinstance(value, dict):
            result = b"d"
            # Bencode requires keys to be sorted
            for key in sorted(value.keys()):
                result += self._encode_bencode(key)
                result += self._encode_bencode(value[key])
            result += b"e"
            return result
        else:
            raise BencodeError(f"Cannot encode type: {type(value)}")

    def get_info_hash(self) -> str:
        """
        Calculate and return the SHA-1 hash of the 'info' dictionary.

        Returns:
            Hexadecimal string of the info hash
        """
        if self._info_hash_override:
            return self._info_hash_override.hex()

        if self._raw_dict is None:
            self.parse()

        if "info" not in self._raw_dict:  # type: ignore
            raise ValueError("Torrent file missing 'info' dictionary")

        # Re-encode the info dictionary to calculate its hash
        info_bytes = self._encode_bencode(self._raw_dict["info"])  # type: ignore
        return hashlib.sha1(info_bytes).hexdigest()

    def get_info_hash_bytes(self) -> bytes:
        """
        Calculate and return the SHA-1 hash of the 'info' dictionary as bytes.

        Returns:
            Raw bytes of the info hash (20 bytes)
        """
        if self._info_hash_override:
            return self._info_hash_override

        if self._raw_dict is None:
            self.parse()

        if "info" not in self._raw_dict:  # type: ignore
            raise ValueError("Torrent file missing 'info' dictionary")

        info_bytes = self._encode_bencode(self._raw_dict["info"])  # type: ignore
        return hashlib.sha1(info_bytes).digest()

    # Convenience methods that delegate to the Torrent model
    def get_announce_urls(self) -> list[str]:
        """Get all announce URLs from the torrent."""
        return self.torrent.get_announce_urls()

    def get_files(self) -> list[TorrentFile]:
        """Get list of files in the torrent."""
        return self.torrent.get_files()

    def get_total_size(self) -> int:
        """Get the total size of all files in the torrent."""
        return self.torrent.total_size

    def get_piece_length(self) -> int:
        """Get the piece length (chunk size) for the torrent."""
        return self.torrent.piece_length

    def get_piece_count(self) -> int:
        """Get the number of pieces in the torrent."""
        return self.torrent.piece_count

    def get_name(self) -> str:
        """Get the name of the torrent."""
        return self.torrent.name

    def get_creation_date(self) -> int | None:
        """Get the creation date of the torrent (Unix timestamp)."""
        return self.torrent.creation_date

    def get_comment(self) -> str | None:
        """Get the comment from the torrent."""
        return self.torrent.comment

    def get_created_by(self) -> str | None:
        """Get the 'created by' field from the torrent."""
        return self.torrent.created_by

    def print_summary(self) -> None:
        """Print a human-readable summary of the torrent."""
        print(f"Info Hash: {self.get_info_hash()}")
        self.torrent.print_summary()


def _format_size(size_bytes: int) -> str:
    """
    Format bytes into human-readable size.

    Args:
        size_bytes: Size in bytes

    Returns:
        Formatted size string
    """
    size = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def main() -> None:
    """Example usage of the torrent parser."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python torrent_parser.py <torrent_file>")
        sys.exit(1)

    torrent_file = sys.argv[1]

    try:
        parser = TorrentParser(torrent_file)
        parser.parse()
        parser.print_summary()

        # Example of accessing structured data
        print("\n--- Accessing structured data ---")
        torrent = parser.torrent
        print(f"Is single file: {torrent.info.is_single_file}")
        print(f"First file: {torrent.get_files()[0].full_path}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
