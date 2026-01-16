# Torrent Study

A complete BitTorrent implementation in Python, including a `.torrent` file parser and a full-featured BitTorrent client.

## Components

### 1. Torrent Parser (`torrent_parser.py`)

A Python library for parsing `.torrent` files that decodes bencoded data and extracts torrent metadata.

## Features

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

## Usage

### Command Line

```bash
python torrent_parser.py <torrent_file>
```

Example:
```bash
python torrent_parser.py Skyfall.2012.2160p.UHD.BluRay.X265-IAMABLE.torrent
```

### Python API

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

## API Methods

- `parse()` - Parse the torrent file and return decoded data
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

## Bencode Format

The parser supports the full bencode specification:
- **Integers**: `i<number>e` (e.g., `i42e`)
- **Strings**: `<length>:<data>` (e.g., `5:hello`)
- **Lists**: `l<elements>e` (e.g., `li1ei2ee`)
- **Dictionaries**: `d<key-value pairs>e` (e.g., `d3:key5:valuee`)

## Requirements

- Python 3.7+
- For parser only: No external dependencies (uses only standard library)
- For client: `aiohttp>=3.8.0` (see `requirements.txt`)

## BitTorrent Client

This project also includes a complete BitTorrent client implementation. See [README_CLIENT.md](README_CLIENT.md) for details.

### Quick Start (Client)

```bash
# Install dependencies
pip install -r requirements.txt

# Download a torrent
python cli.py torrent.torrent -o ./downloads
```

The client includes:
- Tracker communication (HTTP/HTTPS/UDP)
- Peer protocol implementation
- Piece downloading and verification
- File writing
- Concurrent downloads from multiple peers

