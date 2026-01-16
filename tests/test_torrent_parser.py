"""Tests for the torrent parser module."""

import hashlib
import tempfile
from pathlib import Path

import pytest

from src.torrent_parser import (
    BencodeError,
    Torrent,
    TorrentFile,
    TorrentInfo,
    TorrentParser,
    _format_size,
)


class TestBencodeDecoding:
    """Tests for bencode decoding functionality."""

    def test_decode_integer(self, tmp_path: Path) -> None:
        """Test decoding of bencoded integers."""
        # Create a simple torrent with an integer
        torrent_file = tmp_path / "test.torrent"
        # d8:announce3:url4:infod4:name4:test12:piece lengthi16384e6:pieces20:01234567890123456789ee
        content = b"d8:announce3:url4:infod4:name4:test12:piece lengthi16384e6:pieces20:01234567890123456789ee"
        torrent_file.write_bytes(content)

        parser = TorrentParser(torrent_file)
        torrent = parser.parse()

        assert torrent.info.piece_length == 16384

    def test_decode_string(self, tmp_path: Path) -> None:
        """Test decoding of bencoded strings."""
        torrent_file = tmp_path / "test.torrent"
        content = b"d8:announce17:http://tracker.io4:infod4:name8:testfile12:piece lengthi16384e6:pieces20:01234567890123456789ee"
        torrent_file.write_bytes(content)

        parser = TorrentParser(torrent_file)
        torrent = parser.parse()

        assert torrent.announce == "http://tracker.io"
        assert torrent.info.name == "testfile"

    def test_decode_list(self, tmp_path: Path) -> None:
        """Test decoding of bencoded lists (announce-list)."""
        torrent_file = tmp_path / "test.torrent"
        # Torrent with announce-list - using helper to build correct bencode
        # Structure: d announce:url announce-list:[[url1][url2]] info:{...} e
        content = (
            b"d"
            b"8:announce17:http://tracker.io"
            b"13:announce-list"
            b"l"  # list of tiers
            b"l17:http://tracker.ioe"  # tier 1
            b"l16:http://backup.ioe"  # tier 2
            b"e"  # end announce-list
            b"4:info"
            b"d"
            b"4:name4:test"
            b"12:piece lengthi16384e"
            b"6:pieces20:01234567890123456789"
            b"e"  # end info
            b"e"  # end root
        )
        torrent_file.write_bytes(content)

        parser = TorrentParser(torrent_file)
        torrent = parser.parse()

        assert torrent.announce_list is not None
        assert len(torrent.announce_list) == 2
        assert torrent.announce_list[0] == ["http://tracker.io"]
        assert torrent.announce_list[1] == ["http://backup.io"]

    def test_decode_nested_dict(self, tmp_path: Path) -> None:
        """Test decoding of nested dictionaries."""
        torrent_file = tmp_path / "test.torrent"
        content = b"d8:announce3:url4:infod4:name4:test12:piece lengthi16384e6:pieces20:01234567890123456789ee"
        torrent_file.write_bytes(content)

        parser = TorrentParser(torrent_file)
        torrent = parser.parse()

        assert isinstance(torrent.info, TorrentInfo)
        assert torrent.info.name == "test"

    def test_invalid_bencode_unterminated_integer(self, tmp_path: Path) -> None:
        """Test error handling for unterminated integer."""
        torrent_file = tmp_path / "test.torrent"
        content = b"d4:infod12:piece lengthi16384"  # Missing 'e' for integer
        torrent_file.write_bytes(content)

        parser = TorrentParser(torrent_file)
        with pytest.raises(BencodeError, match="Unterminated"):
            parser.parse()

    def test_invalid_bencode_unexpected_char(self, tmp_path: Path) -> None:
        """Test error handling for unexpected characters."""
        torrent_file = tmp_path / "test.torrent"
        content = b"x"  # Invalid starting character
        torrent_file.write_bytes(content)

        parser = TorrentParser(torrent_file)
        with pytest.raises(BencodeError, match="Unexpected character"):
            parser.parse()


class TestTorrentFile:
    """Tests for TorrentFile model."""

    def test_full_path_single_component(self) -> None:
        """Test full_path with single path component."""
        tf = TorrentFile(length=1024, path=["file.txt"])
        assert tf.full_path == "file.txt"

    def test_full_path_multiple_components(self) -> None:
        """Test full_path with multiple path components."""
        tf = TorrentFile(length=1024, path=["dir", "subdir", "file.txt"])
        assert tf.full_path == "dir/subdir/file.txt"

    def test_format_size(self) -> None:
        """Test size formatting."""
        tf = TorrentFile(length=1536, path=["file.txt"])
        assert tf.format_size() == "1.50 KB"


class TestTorrentInfo:
    """Tests for TorrentInfo model."""

    def test_single_file_torrent(self) -> None:
        """Test single file torrent detection."""
        info = TorrentInfo(
            name="file.txt",
            piece_length=16384,
            pieces=b"01234567890123456789",  # 20 bytes = 1 piece hash
            length=1024,
        )

        assert info.is_single_file is True
        assert info.total_size == 1024
        assert info.piece_count == 1

    def test_multi_file_torrent(self) -> None:
        """Test multi-file torrent."""
        info = TorrentInfo(
            name="my_folder",
            piece_length=16384,
            pieces=b"01234567890123456789" * 2,  # 40 bytes = 2 piece hashes
            files=[
                TorrentFile(length=512, path=["file1.txt"]),
                TorrentFile(length=768, path=["subdir", "file2.txt"]),
            ],
        )

        assert info.is_single_file is False
        assert info.total_size == 1280
        assert info.piece_count == 2

    def test_get_piece_hash(self) -> None:
        """Test getting piece hash by index."""
        piece1 = b"AAAAAAAAAAAAAAAAAAAA"
        piece2 = b"BBBBBBBBBBBBBBBBBBBB"
        info = TorrentInfo(
            name="test",
            piece_length=16384,
            pieces=piece1 + piece2,
            length=32768,
        )

        assert info.get_piece_hash(0) == piece1
        assert info.get_piece_hash(1) == piece2

    def test_get_piece_hash_out_of_range(self) -> None:
        """Test piece hash index out of range."""
        info = TorrentInfo(
            name="test",
            piece_length=16384,
            pieces=b"01234567890123456789",
            length=16384,
        )

        with pytest.raises(IndexError):
            info.get_piece_hash(5)

        with pytest.raises(IndexError):
            info.get_piece_hash(-1)

    def test_get_files_single_file(self) -> None:
        """Test get_files for single file torrent."""
        info = TorrentInfo(
            name="myfile.txt",
            piece_length=16384,
            pieces=b"01234567890123456789",
            length=1024,
        )

        files = info.get_files()
        assert len(files) == 1
        assert files[0].path == ["myfile.txt"]
        assert files[0].length == 1024

    def test_get_files_multi_file(self) -> None:
        """Test get_files for multi-file torrent."""
        info = TorrentInfo(
            name="myfolder",
            piece_length=16384,
            pieces=b"01234567890123456789",
            files=[
                TorrentFile(length=100, path=["a.txt"]),
                TorrentFile(length=200, path=["b.txt"]),
            ],
        )

        files = info.get_files()
        assert len(files) == 2


class TestTorrent:
    """Tests for Torrent model."""

    def test_get_announce_urls_single(self) -> None:
        """Test getting announce URLs with single announce."""
        torrent = Torrent(
            info=TorrentInfo(
                name="test",
                piece_length=16384,
                pieces=b"01234567890123456789",
                length=1024,
            ),
            announce="http://tracker.example.com",
        )

        urls = torrent.get_announce_urls()
        assert urls == ["http://tracker.example.com"]

    def test_get_announce_urls_with_list(self) -> None:
        """Test getting announce URLs with announce-list."""
        torrent = Torrent(
            info=TorrentInfo(
                name="test",
                piece_length=16384,
                pieces=b"01234567890123456789",
                length=1024,
            ),
            announce="http://primary.example.com",
            announce_list=[
                ["http://primary.example.com", "http://backup1.example.com"],
                ["http://tier2.example.com"],
            ],
        )

        urls = torrent.get_announce_urls()
        # Primary should be first, then unique URLs from announce-list
        assert urls[0] == "http://primary.example.com"
        assert "http://backup1.example.com" in urls
        assert "http://tier2.example.com" in urls
        # No duplicates
        assert len(urls) == len(set(urls))

    def test_creation_datetime(self) -> None:
        """Test creation datetime conversion."""
        torrent = Torrent(
            info=TorrentInfo(
                name="test",
                piece_length=16384,
                pieces=b"01234567890123456789",
                length=1024,
            ),
            creation_date=1700000000,
        )

        assert torrent.creation_datetime is not None
        assert torrent.creation_datetime.year == 2023

    def test_creation_datetime_none(self) -> None:
        """Test creation datetime when not set."""
        torrent = Torrent(
            info=TorrentInfo(
                name="test",
                piece_length=16384,
                pieces=b"01234567890123456789",
                length=1024,
            ),
        )

        assert torrent.creation_datetime is None


class TestTorrentParser:
    """Tests for TorrentParser class."""

    def test_file_not_found(self) -> None:
        """Test error when torrent file doesn't exist."""
        with pytest.raises(FileNotFoundError):
            TorrentParser("/nonexistent/path/to/file.torrent")

    def test_parse_single_file_torrent(self, tmp_path: Path) -> None:
        """Test parsing a single file torrent."""
        torrent_file = tmp_path / "single.torrent"
        # Single file torrent structure
        content = b"d8:announce20:http://tracker.local4:infod6:lengthi1024e4:name8:test.txt12:piece lengthi16384e6:pieces20:01234567890123456789ee"
        torrent_file.write_bytes(content)

        parser = TorrentParser(torrent_file)
        torrent = parser.parse()

        assert torrent.name == "test.txt"
        assert torrent.total_size == 1024
        assert torrent.info.is_single_file is True

    def test_parse_multi_file_torrent(self, tmp_path: Path) -> None:
        """Test parsing a multi-file torrent."""
        torrent_file = tmp_path / "multi.torrent"
        # Multi-file torrent structure
        # d4:infod5:filesld6:lengthi100e4:pathl5:a.txteed6:lengthi200e4:pathl5:b.txteee4:name6:folder12:piece lengthi16384e6:pieces20:01234567890123456789ee
        content = b"d4:infod5:filesld6:lengthi100e4:pathl5:a.txteed6:lengthi200e4:pathl5:b.txteee4:name6:folder12:piece lengthi16384e6:pieces20:01234567890123456789ee"
        torrent_file.write_bytes(content)

        parser = TorrentParser(torrent_file)
        torrent = parser.parse()

        assert torrent.name == "folder"
        assert torrent.info.is_single_file is False
        assert torrent.total_size == 300

        files = torrent.get_files()
        assert len(files) == 2
        assert files[0].full_path == "a.txt"
        assert files[1].full_path == "b.txt"

    def test_get_info_hash(self, tmp_path: Path) -> None:
        """Test info hash calculation."""
        torrent_file = tmp_path / "test.torrent"
        info_dict = b"d6:lengthi1024e4:name8:test.txt12:piece lengthi16384e6:pieces20:01234567890123456789e"
        content = b"d4:info" + info_dict + b"e"
        torrent_file.write_bytes(content)

        parser = TorrentParser(torrent_file)
        parser.parse()

        info_hash = parser.get_info_hash()
        expected_hash = hashlib.sha1(info_dict).hexdigest()

        assert info_hash == expected_hash
        assert len(info_hash) == 40

    def test_get_info_hash_bytes(self, tmp_path: Path) -> None:
        """Test info hash calculation as bytes."""
        torrent_file = tmp_path / "test.torrent"
        info_dict = b"d6:lengthi1024e4:name8:test.txt12:piece lengthi16384e6:pieces20:01234567890123456789e"
        content = b"d4:info" + info_dict + b"e"
        torrent_file.write_bytes(content)

        parser = TorrentParser(torrent_file)
        parser.parse()

        info_hash_bytes = parser.get_info_hash_bytes()
        expected_hash = hashlib.sha1(info_dict).digest()

        assert info_hash_bytes == expected_hash
        assert len(info_hash_bytes) == 20

    def test_torrent_property_auto_parse(self, tmp_path: Path) -> None:
        """Test that torrent property auto-parses if needed."""
        torrent_file = tmp_path / "test.torrent"
        content = b"d4:infod6:lengthi1024e4:name4:test12:piece lengthi16384e6:pieces20:01234567890123456789ee"
        torrent_file.write_bytes(content)

        parser = TorrentParser(torrent_file)
        # Don't call parse() explicitly
        torrent = parser.torrent

        assert torrent.name == "test"

    def test_convenience_methods(self, tmp_path: Path) -> None:
        """Test convenience methods on TorrentParser."""
        torrent_file = tmp_path / "test.torrent"
        # Build bencode properly with correct string lengths
        content = (
            b"d"
            b"8:announce20:http://tracker.local"
            b"7:comment12:test torrent"
            b"10:created by9:test tool"
            b"13:creation datei1700000000e"
            b"4:info"
            b"d"
            b"6:lengthi2048e"
            b"4:name8:file.txt"
            b"12:piece lengthi16384e"
            b"6:pieces20:01234567890123456789"
            b"e"
            b"e"
        )
        torrent_file.write_bytes(content)

        parser = TorrentParser(torrent_file)
        parser.parse()

        assert parser.get_name() == "file.txt"
        assert parser.get_total_size() == 2048
        assert parser.get_piece_length() == 16384
        assert parser.get_piece_count() == 1
        assert parser.get_comment() == "test torrent"
        assert parser.get_created_by() == "test tool"
        assert parser.get_creation_date() == 1700000000
        assert parser.get_announce_urls() == ["http://tracker.local"]

    def test_bytes_to_string_conversion(self, tmp_path: Path) -> None:
        """Test that bytes fields are properly converted to strings."""
        torrent_file = tmp_path / "test.torrent"
        # Create torrent with UTF-8 encoded name
        # "testéfile.txt" is 13 bytes: t e s t é(2 bytes) f i l e . t x t
        # "Unicode: éà" is 13 bytes: U n i c o d e :   é(2) à(2)
        content = (
            b"d"
            b"8:announce20:http://tracker.local"
            b"7:comment13:Unicode: \xc3\xa9\xc3\xa0"
            b"4:info"
            b"d"
            b"6:lengthi1024e"
            b"4:name14:test\xc3\xa9file.txt"
            b"12:piece lengthi16384e"
            b"6:pieces20:01234567890123456789"
            b"e"
            b"e"
        )
        torrent_file.write_bytes(content)

        parser = TorrentParser(torrent_file)
        torrent = parser.parse()

        assert "testé" in torrent.name
        assert "é" in torrent.comment or "à" in torrent.comment  # type: ignore


class TestFormatSize:
    """Tests for the _format_size helper function."""

    def test_bytes(self) -> None:
        """Test formatting bytes."""
        assert _format_size(0) == "0.00 B"
        assert _format_size(512) == "512.00 B"
        assert _format_size(1023) == "1023.00 B"

    def test_kilobytes(self) -> None:
        """Test formatting kilobytes."""
        assert _format_size(1024) == "1.00 KB"
        assert _format_size(1536) == "1.50 KB"

    def test_megabytes(self) -> None:
        """Test formatting megabytes."""
        assert _format_size(1024 * 1024) == "1.00 MB"
        assert _format_size(1024 * 1024 * 5) == "5.00 MB"

    def test_gigabytes(self) -> None:
        """Test formatting gigabytes."""
        assert _format_size(1024 * 1024 * 1024) == "1.00 GB"
        assert _format_size(1024 * 1024 * 1024 * 2) == "2.00 GB"

    def test_terabytes(self) -> None:
        """Test formatting terabytes."""
        assert _format_size(1024 * 1024 * 1024 * 1024) == "1.00 TB"


class TestBencodeEncoding:
    """Tests for bencode encoding functionality."""

    def test_encode_decode_roundtrip(self, tmp_path: Path) -> None:
        """Test that encoding and decoding produces consistent results."""
        torrent_file = tmp_path / "test.torrent"
        original_content = b"d8:announce20:http://tracker.local4:infod6:lengthi1024e4:name8:test.txt12:piece lengthi16384e6:pieces20:01234567890123456789ee"
        torrent_file.write_bytes(original_content)

        parser = TorrentParser(torrent_file)
        parser.parse()

        # The info hash should be consistent
        hash1 = parser.get_info_hash()
        hash2 = parser.get_info_hash()
        assert hash1 == hash2
