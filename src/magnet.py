"""
Magnet link parser and metadata fetcher.
Supports BEP 9 (Extension for Peers to Send Metadata Files).
"""

from __future__ import annotations

import hashlib
import re
import urllib.parse
from typing import Any

from pydantic import BaseModel, Field, computed_field


class MagnetError(Exception):
    """Exception raised for magnet link errors."""

    pass


class MagnetLink(BaseModel):
    """Parsed magnet link data."""

    info_hash: bytes = Field(description="20-byte info hash")
    display_name: str | None = Field(default=None, description="Display name of the torrent")
    trackers: list[str] = Field(default_factory=list, description="List of tracker URLs")
    exact_length: int | None = Field(default=None, description="Exact file length if known")
    web_seeds: list[str] = Field(default_factory=list, description="Web seed URLs")

    model_config = {"arbitrary_types_allowed": True}

    @computed_field
    @property
    def info_hash_hex(self) -> str:
        """Get info hash as hex string."""
        return self.info_hash.hex()

    @classmethod
    def parse(cls, magnet_uri: str) -> "MagnetLink":
        """
        Parse a magnet URI.

        Args:
            magnet_uri: The magnet URI to parse

        Returns:
            MagnetLink object with parsed data

        Raises:
            MagnetError: If the URI is invalid
        """
        if not magnet_uri.startswith("magnet:?"):
            raise MagnetError("Invalid magnet URI: must start with 'magnet:?'")

        # Parse query parameters
        query = magnet_uri[8:]  # Remove "magnet:?"
        params = urllib.parse.parse_qs(query)

        # Extract info hash (required)
        xt_list = params.get("xt", [])
        info_hash: bytes | None = None

        for xt in xt_list:
            if xt.startswith("urn:btih:"):
                hash_str = xt[9:]  # Remove "urn:btih:"

                # Handle both hex (40 chars) and base32 (32 chars) encoding
                if len(hash_str) == 40:
                    # Hex encoded
                    try:
                        info_hash = bytes.fromhex(hash_str)
                    except ValueError as e:
                        raise MagnetError(f"Invalid hex info hash: {hash_str}") from e
                elif len(hash_str) == 32:
                    # Base32 encoded
                    import base64

                    try:
                        info_hash = base64.b32decode(hash_str.upper())
                    except Exception as e:
                        raise MagnetError(f"Invalid base32 info hash: {hash_str}") from e
                else:
                    raise MagnetError(f"Invalid info hash length: {len(hash_str)}")
                break

        if info_hash is None:
            raise MagnetError("Magnet URI missing info hash (xt=urn:btih:...)")

        if len(info_hash) != 20:
            raise MagnetError(f"Info hash must be 20 bytes, got {len(info_hash)}")

        # Extract display name (optional)
        dn_list = params.get("dn", [])
        display_name = urllib.parse.unquote(dn_list[0]) if dn_list else None

        # Extract trackers (optional, can be multiple)
        trackers = [urllib.parse.unquote(tr) for tr in params.get("tr", [])]

        # Extract exact length (optional)
        xl_list = params.get("xl", [])
        exact_length = int(xl_list[0]) if xl_list else None

        # Extract web seeds (optional)
        web_seeds = [urllib.parse.unquote(ws) for ws in params.get("ws", [])]

        return cls(
            info_hash=info_hash,
            display_name=display_name,
            trackers=trackers,
            exact_length=exact_length,
            web_seeds=web_seeds,
        )

    def to_uri(self) -> str:
        """
        Convert back to a magnet URI.

        Returns:
            Magnet URI string
        """
        params = [f"xt=urn:btih:{self.info_hash_hex}"]

        if self.display_name:
            params.append(f"dn={urllib.parse.quote(self.display_name)}")

        for tracker in self.trackers:
            params.append(f"tr={urllib.parse.quote(tracker)}")

        if self.exact_length:
            params.append(f"xl={self.exact_length}")

        for ws in self.web_seeds:
            params.append(f"ws={urllib.parse.quote(ws)}")

        return "magnet:?" + "&".join(params)


def is_magnet_link(uri: str) -> bool:
    """
    Check if a string is a magnet link.

    Args:
        uri: String to check

    Returns:
        True if it's a magnet link
    """
    return uri.startswith("magnet:?")


def bencode_encode(value: Any) -> bytes:
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
            result += bencode_encode(item)
        result += b"e"
        return result
    elif isinstance(value, dict):
        result = b"d"
        # Bencode requires keys to be sorted
        for original_key in sorted(value.keys()):
            key_to_encode = original_key
            if isinstance(key_to_encode, str):
                key_to_encode = key_to_encode.encode("utf-8")
            result += bencode_encode(key_to_encode)
            result += bencode_encode(value[original_key])
        result += b"e"
        return result
    else:
        raise ValueError(f"Cannot encode type: {type(value)}")


def bencode_decode(data: bytes, index: int = 0) -> tuple[Any, int]:
    """
    Decode bencoded data.

    Args:
        data: The raw bytes to decode
        index: Current position in the data

    Returns:
        Tuple of (decoded_value, new_index)
    """
    if index >= len(data):
        raise ValueError(f"Unexpected end of data at index {index}")

    char = data[index : index + 1]

    # Integer: i<number>e
    if char == b"i":
        end_index = data.find(b"e", index + 1)
        if end_index == -1:
            raise ValueError(f"Unterminated integer at index {index}")
        value = int(data[index + 1 : end_index])
        return value, end_index + 1

    # List: l<elements>e
    elif char == b"l":
        index += 1
        result: list[Any] = []
        while index < len(data) and data[index : index + 1] != b"e":
            value, index = bencode_decode(data, index)
            result.append(value)
        if index >= len(data):
            raise ValueError(f"Unterminated list at index {index}")
        return result, index + 1

    # Dictionary: d<key-value pairs>e
    elif char == b"d":
        index += 1
        result_dict: dict[Any, Any] = {}
        while index < len(data) and data[index : index + 1] != b"e":
            key, index = bencode_decode(data, index)
            value, index = bencode_decode(data, index)
            # Keep keys as bytes for binary safety
            if isinstance(key, bytes):
                key = key.decode("utf-8", errors="replace")
            result_dict[key] = value
        if index >= len(data):
            raise ValueError(f"Unterminated dictionary at index {index}")
        return result_dict, index + 1

    # String: <length>:<data>
    elif char.isdigit():
        colon_index = data.find(b":", index)
        if colon_index == -1:
            raise ValueError(f"No colon found for string at index {index}")
        length = int(data[index:colon_index])
        start_index = colon_index + 1
        end_index = start_index + length
        if end_index > len(data):
            raise ValueError(f"String length exceeds data at index {index}")
        value = data[start_index:end_index]
        return value, end_index

    else:
        raise ValueError(f"Unexpected character '{char.decode('latin-1', errors='replace')}' at index {index}")
