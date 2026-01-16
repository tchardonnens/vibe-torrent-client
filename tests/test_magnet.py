"""Tests for magnet link parsing."""

import sys
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from magnet import MagnetError, MagnetLink, bencode_decode, bencode_encode, is_magnet_link


class TestMagnetLinkParsing:
    """Tests for MagnetLink.parse()."""

    def test_parse_simple_magnet(self) -> None:
        """Test parsing a simple magnet link with just info hash."""
        uri = "magnet:?xt=urn:btih:dd8255ecdc7ca55fb0bbf81323d87062db1f6d1c"
        magnet = MagnetLink.parse(uri)

        assert magnet.info_hash_hex == "dd8255ecdc7ca55fb0bbf81323d87062db1f6d1c"
        assert len(magnet.info_hash) == 20
        assert magnet.display_name is None
        assert magnet.trackers == []

    def test_parse_magnet_with_display_name(self) -> None:
        """Test parsing magnet with display name."""
        uri = "magnet:?xt=urn:btih:dd8255ecdc7ca55fb0bbf81323d87062db1f6d1c&dn=Ubuntu+25.10"
        magnet = MagnetLink.parse(uri)

        assert magnet.info_hash_hex == "dd8255ecdc7ca55fb0bbf81323d87062db1f6d1c"
        assert magnet.display_name == "Ubuntu 25.10"

    def test_parse_magnet_with_trackers(self) -> None:
        """Test parsing magnet with tracker URLs."""
        uri = (
            "magnet:?xt=urn:btih:dd8255ecdc7ca55fb0bbf81323d87062db1f6d1c"
            "&tr=udp://tracker1.example.com:6969"
            "&tr=udp://tracker2.example.com:6969"
        )
        magnet = MagnetLink.parse(uri)

        assert len(magnet.trackers) == 2
        assert "udp://tracker1.example.com:6969" in magnet.trackers
        assert "udp://tracker2.example.com:6969" in magnet.trackers

    def test_parse_magnet_with_all_fields(self) -> None:
        """Test parsing magnet with all common fields."""
        uri = (
            "magnet:?xt=urn:btih:dd8255ecdc7ca55fb0bbf81323d87062db1f6d1c"
            "&dn=Ubuntu+25.10+Desktop+ISO"
            "&xl=4000000000"
            "&tr=udp://tracker.example.com:6969"
            "&ws=http://example.com/file.iso"
        )
        magnet = MagnetLink.parse(uri)

        assert magnet.info_hash_hex == "dd8255ecdc7ca55fb0bbf81323d87062db1f6d1c"
        assert magnet.display_name == "Ubuntu 25.10 Desktop ISO"
        assert magnet.exact_length == 4000000000
        assert len(magnet.trackers) == 1
        assert len(magnet.web_seeds) == 1

    def test_parse_base32_info_hash(self) -> None:
        """Test parsing magnet with base32 encoded info hash."""
        # Base32 encoding of a 20-byte hash
        uri = "magnet:?xt=urn:btih:3WBIF3K4R4FVPHMZEYYWZQZQ4KNBPXB4"
        magnet = MagnetLink.parse(uri)

        assert len(magnet.info_hash) == 20
        assert len(magnet.info_hash_hex) == 40

    def test_parse_invalid_uri_format(self) -> None:
        """Test that invalid URI format raises error."""
        with pytest.raises(MagnetError, match="must start with"):
            MagnetLink.parse("http://example.com/file.torrent")

    def test_parse_missing_info_hash(self) -> None:
        """Test that missing info hash raises error."""
        with pytest.raises(MagnetError, match="missing info hash"):
            MagnetLink.parse("magnet:?dn=SomeTorrent")

    def test_parse_invalid_hex_hash(self) -> None:
        """Test that invalid hex info hash raises error."""
        # 40-char string that isn't valid hex
        with pytest.raises(MagnetError, match="Invalid hex info hash"):
            MagnetLink.parse("magnet:?xt=urn:btih:zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz")

    def test_parse_invalid_hash_length(self) -> None:
        """Test that invalid hash length raises error."""
        with pytest.raises(MagnetError, match="Invalid info hash length"):
            MagnetLink.parse("magnet:?xt=urn:btih:abc123")


class TestMagnetLinkToUri:
    """Tests for MagnetLink.to_uri()."""

    def test_to_uri_simple(self) -> None:
        """Test converting back to URI."""
        original = "magnet:?xt=urn:btih:dd8255ecdc7ca55fb0bbf81323d87062db1f6d1c"
        magnet = MagnetLink.parse(original)
        result = magnet.to_uri()

        assert "xt=urn:btih:dd8255ecdc7ca55fb0bbf81323d87062db1f6d1c" in result
        assert result.startswith("magnet:?")

    def test_to_uri_with_name(self) -> None:
        """Test converting with display name."""
        uri = "magnet:?xt=urn:btih:dd8255ecdc7ca55fb0bbf81323d87062db1f6d1c&dn=Test"
        magnet = MagnetLink.parse(uri)
        result = magnet.to_uri()

        assert "dn=Test" in result


class TestIsMagnetLink:
    """Tests for is_magnet_link()."""

    def test_valid_magnet(self) -> None:
        """Test that valid magnet links are detected."""
        assert is_magnet_link("magnet:?xt=urn:btih:abc123") is True

    def test_torrent_file(self) -> None:
        """Test that torrent files are not magnet links."""
        assert is_magnet_link("/path/to/file.torrent") is False
        assert is_magnet_link("file.torrent") is False

    def test_http_url(self) -> None:
        """Test that HTTP URLs are not magnet links."""
        assert is_magnet_link("http://example.com/file.torrent") is False


class TestBencodeRoundtrip:
    """Tests for bencode encode/decode functions."""

    def test_encode_decode_integer(self) -> None:
        """Test encoding and decoding integers."""
        value = 42
        encoded = bencode_encode(value)
        decoded, _ = bencode_decode(encoded)
        assert decoded == value

    def test_encode_decode_string(self) -> None:
        """Test encoding and decoding strings."""
        value = b"hello world"
        encoded = bencode_encode(value)
        decoded, _ = bencode_decode(encoded)
        assert decoded == value

    def test_encode_decode_list(self) -> None:
        """Test encoding and decoding lists."""
        value = [1, 2, b"three"]
        encoded = bencode_encode(value)
        decoded, _ = bencode_decode(encoded)
        assert decoded == value

    def test_encode_decode_dict(self) -> None:
        """Test encoding and decoding dicts."""
        value = {"key": b"value", "number": 123}
        encoded = bencode_encode(value)
        decoded, _ = bencode_decode(encoded)
        assert decoded["key"] == b"value"
        assert decoded["number"] == 123

    def test_encode_decode_nested(self) -> None:
        """Test encoding and decoding nested structures."""
        value = {
            "list": [1, 2, 3],
            "dict": {"nested": b"value"},
        }
        encoded = bencode_encode(value)
        decoded, _ = bencode_decode(encoded)
        assert decoded["list"] == [1, 2, 3]
        assert decoded["dict"]["nested"] == b"value"
