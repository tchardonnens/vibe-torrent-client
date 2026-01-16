# Vibe Torrent Client

A complete BitTorrent implementation in Python, including a `.torrent` file parser, **magnet link support**, and a full-featured BitTorrent client.

## Features

- **Torrent File Parsing**: Full bencode decoder with metadata extraction
- **Magnet Link Support**: Parse magnet URIs and fetch metadata from peers (BEP 9)
- **Tracker Communication**: HTTP/HTTPS and UDP tracker protocols
- **Peer Protocol**: Complete BitTorrent peer wire protocol
- **Extension Protocol**: BEP 10 extension handshake for magnet links
- **Concurrent Downloads**: Download from multiple peers simultaneously
- **Piece Verification**: SHA-1 hash verification for data integrity
- **TUI**: Real-time terminal UI showing download progress

## Quick Start

```bash
# Install dependencies
uv sync  # or: pip install -r requirements.txt

# Download from a torrent file
uv run python src/cli.py torrents/ubuntu.torrent -o ./downloads

# Download from a magnet link
uv run python src/cli.py "magnet:?xt=urn:btih:dd8255ecdc7ca55fb0bbf81323d87062db1f6d1c&dn=Ubuntu&tr=udp://tracker.example.com:6969"
```

## Components

### 1. Torrent Parser (`torrent_parser.py`)

A Python library for parsing `.torrent` files that decodes bencoded data and extracts torrent metadata.

#### Features

- Decodes bencoded data (strings, integers, lists, dictionaries)
- Extracts torrent metadata:
  - Info hash (SHA-1)
  - File list with sizes
  - Total size
  - Piece length and count
  - Announce URLs
  - Creation date
  - Comments
- Human-readable summary output

#### Python API

```python
from torrent_parser import TorrentParser

# Create parser instance
parser = TorrentParser("path/to/file.torrent")

# Parse the torrent file
data = parser.parse()

# Get specific information
info_hash = parser.get_info_hash()
files = parser.get_files()
total_size = parser.get_total_size()
announce_urls = parser.get_announce_urls()

# Print human-readable summary
parser.print_summary()
```

### 2. Magnet Link Parser (`magnet.py`)

Parse and handle magnet URIs for trackerless torrent downloads.

#### Features

- Parse magnet URIs with info hash extraction
- Support for both hex (40 char) and base32 (32 char) info hashes
- Extract display name, trackers, web seeds, and exact length
- Convert back to magnet URI format

#### Python API

```python
from magnet import MagnetLink, is_magnet_link

# Check if string is a magnet link
if is_magnet_link(uri):
    # Parse the magnet link
    magnet = MagnetLink.parse(uri)
    
    print(f"Info Hash: {magnet.info_hash_hex}")
    print(f"Name: {magnet.display_name}")
    print(f"Trackers: {magnet.trackers}")
```

### 3. BitTorrent Client

See [README_CLIENT.md](README_CLIENT.md) for detailed client documentation.

## API Methods

### TorrentParser

- `parse()` - Parse the torrent file and return decoded data
- `parse_from_metadata()` - Parse from raw metadata bytes (for magnet links)
- `get_info_hash()` - Get SHA-1 hash of the info dictionary
- `get_announce_urls()` - Get list of all announce URLs
- `get_files()` - Get list of files with paths and sizes
- `get_total_size()` - Get total size of all files in bytes
- `get_piece_length()` - Get piece length (chunk size) in bytes
- `get_piece_count()` - Get number of pieces
- `get_name()` - Get torrent name
- `get_creation_date()` - Get creation date (Unix timestamp)
- `get_comment()` - Get comment string
- `get_created_by()` - Get "created by" field
- `print_summary()` - Print human-readable summary

### MagnetLink

- `MagnetLink.parse(uri)` - Parse a magnet URI
- `magnet.info_hash` - 20-byte info hash
- `magnet.info_hash_hex` - Hex-encoded info hash
- `magnet.display_name` - Display name (optional)
- `magnet.trackers` - List of tracker URLs
- `magnet.to_uri()` - Convert back to magnet URI

## Bencode Format

The parser supports the full bencode specification:
- **Integers**: `i<number>e` (e.g., `i42e`)
- **Strings**: `<length>:<data>` (e.g., `5:hello`)
- **Lists**: `l<elements>e` (e.g., `li1ei2ee`)
- **Dictionaries**: `d<key-value pairs>e` (e.g., `d3:key5:valuee`)

## Requirements

- Python 3.10+
- `aiohttp>=3.8.0` - For HTTP tracker communication
- `pydantic>=2.0.0` - For data validation
- `rich>=13.0.0` - For terminal UI

## Installation

```bash
# Using uv (recommended)
uv sync

# Or using pip
pip install -r requirements.txt
```

## Testing

```bash
uv run pytest tests/ -v
```

