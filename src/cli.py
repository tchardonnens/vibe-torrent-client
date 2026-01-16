"""
Command-line interface for the BitTorrent client.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from client import TorrentClient
from magnet import is_magnet_link
from magnet_client import create_parser_from_magnet


async def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="BitTorrent client for downloading torrents")
    parser.add_argument("torrent", type=str, help="Path to .torrent file or magnet link")
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="./downloads",
        help="Output directory for downloaded files (default: ./downloads)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    # Set logging level (no handlers - TUI will handle display)
    import logging

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
        handlers=[],  # No console output - TUI handles logs
    )

    # Check if input is a magnet link or torrent file
    if is_magnet_link(args.torrent):
        # Handle magnet link
        print(f"Magnet link detected, fetching metadata...")

        # Enable console logging temporarily for metadata fetch
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger().addHandler(console_handler)

        result = await create_parser_from_magnet(args.torrent)

        if result is None:
            print("Error: Failed to fetch torrent metadata from peers", file=sys.stderr)
            sys.exit(1)

        torrent_parser, info_hash = result

        # Remove console handler before starting TUI
        logging.getLogger().removeHandler(console_handler)

        # Create client from parser
        client = TorrentClient(parser=torrent_parser, output_dir=args.output, info_hash=info_hash)
    else:
        # Handle torrent file
        torrent_path = Path(args.torrent)
        if not torrent_path.exists():
            print(f"Error: Torrent file not found: {args.torrent}", file=sys.stderr)
            sys.exit(1)

        # Create client
        client = TorrentClient(torrent_path=str(torrent_path), output_dir=args.output)

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
