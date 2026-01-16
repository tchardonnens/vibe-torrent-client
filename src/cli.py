"""
Command-line interface for the BitTorrent client.
"""

import asyncio
import argparse
import sys
from pathlib import Path

from client import TorrentClient


async def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="BitTorrent client for downloading torrents"
    )
    parser.add_argument(
        'torrent',
        type=str,
        help='Path to .torrent file'
    )
    parser.add_argument(
        '-o', '--output',
        type=str,
        default='./downloads',
        help='Output directory for downloaded files (default: ./downloads)'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    # Set logging level
    import logging
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)
    
    # Check if torrent file exists
    torrent_path = Path(args.torrent)
    if not torrent_path.exists():
        print(f"Error: Torrent file not found: {args.torrent}", file=sys.stderr)
        sys.exit(1)
    
    # Create client
    client = TorrentClient(str(torrent_path), args.output)
    
    try:
        # Start client
        await client.start()
    except KeyboardInterrupt:
        print("\nStopping client...")
        client.stop()
        await client._cleanup()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

