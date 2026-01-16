# BitTorrent Client

A complete BitTorrent client implementation in Python that can download torrents from both `.torrent` files and **magnet links**.

## Features

- **Torrent Parsing**: Reads and parses .torrent files
- **Magnet Link Support**: Download using magnet URIs with metadata fetching (BEP 9)
- **Tracker Communication**: Supports both HTTP/HTTPS and UDP trackers
- **Peer Protocol**: Full BitTorrent peer protocol implementation
- **Extension Protocol**: BEP 10 extension handshake for ut_metadata
- **Piece Management**: Downloads and verifies pieces using SHA-1
- **File Management**: Writes downloaded pieces to disk
- **Concurrent Downloads**: Downloads from multiple peers simultaneously
- **Real-time TUI**: Terminal UI with progress, speed, and peer stats

## Architecture

The client is organized into several modules:

- **`torrent_parser.py`**: Parses .torrent files (bencode decoder)
- **`magnet.py`**: Parses magnet URIs and extracts info hash/trackers
- **`magnet_client.py`**: Fetches metadata from peers for magnet links
- **`tracker.py`**: Communicates with trackers to get peer lists
- **`peer.py`**: Handles BitTorrent peer protocol (handshake, messages, extensions)
- **`piece_manager.py`**: Manages piece downloads and verification
- **`file_manager.py`**: Writes downloaded pieces to files
- **`client.py`**: Main orchestrator that coordinates all components
- **`cli.py`**: Command-line interface
- **`tui/`**: Terminal user interface components

## Installation

```bash
# Using uv (recommended)
uv sync

# Or using pip
pip install -r requirements.txt
```

## Usage

### Command Line

```bash
# From project root
uv run python src/cli.py <torrent_file_or_magnet> [-o output_dir] [-v]
```

### Examples

```bash
# Download from torrent file to default ./downloads directory
uv run python src/cli.py torrents/ubuntu.torrent

# Download from magnet link
uv run python src/cli.py "magnet:?xt=urn:btih:dd8255ecdc7ca55fb0bbf81323d87062db1f6d1c&dn=Ubuntu&tr=udp://tracker.opentrackr.org:1337"

# Download to specific directory
uv run python src/cli.py torrent.torrent -o /path/to/downloads

# Verbose logging
uv run python src/cli.py torrent.torrent -v
```

### Python API

```python
import asyncio
from client import TorrentClient

# Download from torrent file
async def download_from_file():
    client = TorrentClient(torrent_path="torrent.torrent", output_dir="./downloads")
    await client.start()

asyncio.run(download_from_file())
```

```python
import asyncio
from magnet_client import create_parser_from_magnet
from client import TorrentClient

# Download from magnet link
async def download_from_magnet():
    magnet_uri = "magnet:?xt=urn:btih:..."
    
    # Fetch metadata from peers
    result = await create_parser_from_magnet(magnet_uri)
    if result:
        parser, info_hash = result
        client = TorrentClient(parser=parser, output_dir="./downloads", info_hash=info_hash)
        await client.start()

asyncio.run(download_from_magnet())
```

## BitTorrent Protocol

The client implements the BitTorrent protocol:

### Tracker Protocol
- HTTP/HTTPS tracker announce
- UDP tracker announce (BEP 15)

### Peer Protocol
- Handshake (with extension bit for BEP 10)
- Message types:
  - CHOKE / UNCHOKE
  - INTERESTED / NOT_INTERESTED
  - HAVE
  - BITFIELD
  - REQUEST
  - PIECE
  - CANCEL
  - KEEP_ALIVE
  - EXTENDED (BEP 10)

### Extension Protocol (BEP 10)
- Extension handshake with capability advertisement
- ut_metadata extension for metadata exchange (BEP 9)

### Metadata Exchange (BEP 9)
- Request metadata pieces from peers
- Assemble and verify metadata using info hash
- Used for magnet link downloads

### Piece Management
- Downloads pieces in 16KB blocks
- Pipelined block requests for speed
- Rarest-first piece selection
- Verifies pieces using SHA-1 hashes
- Assembles pieces into files

## Magnet Link Format

The client supports magnet URIs with the following parameters:

- `xt=urn:btih:<hash>` - Info hash (hex or base32 encoded) **[required]**
- `dn=<name>` - Display name
- `tr=<url>` - Tracker URL (can have multiple)
- `xl=<size>` - Exact length in bytes
- `ws=<url>` - Web seed URL

Example:
```
magnet:?xt=urn:btih:dd8255ecdc7ca55fb0bbf81323d87062db1f6d1c&dn=Ubuntu+25.10&tr=udp://tracker.opentrackr.org:1337&tr=udp://tracker.openbittorrent.com:6969
```

## Limitations

Current limitations:

- DHT (Distributed Hash Table) - not implemented
- Peer Exchange (PEX) - not implemented  
- Seeding (uploading to other peers) - not implemented
- Resume downloads - not implemented
- Encryption/obfuscation - not implemented

## Configuration

Default settings:

- Maximum peers: 120 concurrent connections
- Block size: 16KB
- Pipeline depth: 64 blocks per piece
- Concurrent pieces per peer: 8
- Tracker update interval: 30 seconds

## Notes

- The client connects to up to 120 peers simultaneously
- Pieces are verified before writing to disk
- Real-time TUI shows progress, speed, and peer statistics
- Press Ctrl+C to stop the client gracefully
- For magnet links, metadata is fetched from peers before download starts