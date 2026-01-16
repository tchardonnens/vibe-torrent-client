# BitTorrent Client

A complete BitTorrent client implementation in Python that can download torrents.

## Features

- **Torrent Parsing**: Reads and parses .torrent files
- **Tracker Communication**: Supports both HTTP/HTTPS and UDP trackers
- **Peer Protocol**: Full BitTorrent peer protocol implementation
- **Piece Management**: Downloads and verifies pieces using SHA-1
- **File Management**: Writes downloaded pieces to disk
- **Concurrent Downloads**: Downloads from multiple peers simultaneously
- **Progress Tracking**: Shows download progress

## Architecture

The client is organized into several modules:

- **`torrent_parser.py`**: Parses .torrent files (bencode decoder)
- **`tracker.py`**: Communicates with trackers to get peer lists
- **`peer.py`**: Handles BitTorrent peer protocol (handshake, messages)
- **`piece_manager.py`**: Manages piece downloads and verification
- **`file_manager.py`**: Writes downloaded pieces to files
- **`client.py`**: Main orchestrator that coordinates all components
- **`cli.py`**: Command-line interface

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

### Command Line

```bash
python cli.py <torrent_file> [-o output_dir] [-v]
```

Examples:
```bash
# Download torrent to default ./downloads directory
python cli.py Skyfall.2012.2160p.UHD.BluRay.X265-IAMABLE.torrent

# Download to specific directory
python cli.py torrent.torrent -o /path/to/downloads

# Verbose logging
python cli.py torrent.torrent -v
```

### Python API

```python
import asyncio
from client import TorrentClient

async def download():
    client = TorrentClient("torrent.torrent", output_dir="./downloads")
    await client.start()

asyncio.run(download())
```

## BitTorrent Protocol

The client implements the BitTorrent protocol:

### Tracker Protocol
- HTTP/HTTPS tracker announce
- UDP tracker announce (BEP 15)

### Peer Protocol
- Handshake
- Message types:
  - CHOKE / UNCHOKE
  - INTERESTED / NOT_INTERESTED
  - HAVE
  - BITFIELD
  - REQUEST
  - PIECE
  - CANCEL
  - KEEP_ALIVE

### Piece Management
- Downloads pieces in 16KB blocks
- Verifies pieces using SHA-1 hashes
- Assembles pieces into files

## Limitations

This is a basic implementation. Some features not included:

- DHT (Distributed Hash Table)
- Peer Exchange (PEX)
- Magnet links
- Seeding (uploading to other peers)
- Resume downloads
- Encryption/obfuscation
- Multi-tracker support (only uses first successful tracker)

## Notes

- The client connects to up to 50 peers simultaneously
- Pieces are verified before writing to disk
- Download progress is logged periodically
- Press Ctrl+C to stop the client gracefully