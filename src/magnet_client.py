"""
Magnet link client implementation.
Fetches metadata from peers before starting download.
"""

import asyncio
import logging
from pathlib import Path

from magnet import MagnetLink, is_magnet_link
from peer import Peer
from torrent_parser import TorrentParser
from tracker import Tracker, generate_peer_id

logger = logging.getLogger(__name__)


class MetadataFetcher:
    """Fetches torrent metadata from peers using BEP 9."""

    def __init__(self, magnet: MagnetLink, max_peers: int = 50) -> None:
        """
        Initialize the metadata fetcher.

        Args:
            magnet: Parsed magnet link
            max_peers: Maximum number of peers to try
        """
        self.magnet = magnet
        self.max_peers = max_peers
        self.peer_id = generate_peer_id()
        self.port = 6881
        self.peers: dict[str, Peer] = {}
        self.metadata: bytes | None = None

    async def fetch(self) -> bytes | None:
        """
        Fetch metadata from peers.

        Returns:
            Metadata bytes if successful, None otherwise
        """
        logger.info(f"Fetching metadata for: {self.magnet.display_name or self.magnet.info_hash_hex}")

        # Get peers from trackers
        await self._discover_peers()

        if not self.peers:
            logger.warning("No peers found from trackers")
            return None

        logger.info(f"Found {len(self.peers)} peers, attempting to fetch metadata...")

        # Try to fetch metadata from peers
        metadata = await self._fetch_from_peers()

        return metadata

    async def _discover_peers(self) -> None:
        """Discover peers from trackers."""
        if not self.magnet.trackers:
            logger.warning("Magnet link has no trackers")
            return

        for tracker_url in self.magnet.trackers:
            try:
                tracker = Tracker(
                    announce_url=tracker_url,
                    info_hash=self.magnet.info_hash,
                    peer_id=self.peer_id,
                    port=self.port,
                    downloaded=0,
                    left=0,  # Unknown at this point
                    event="started",
                    numwant=self.max_peers,
                )

                response = await tracker.announce()
                peers = response.get("peers", [])

                logger.info(f"Got {len(peers)} peers from {tracker_url}")

                for peer_info in peers:
                    peer_key = f"{peer_info['ip']}:{peer_info['port']}"
                    if peer_key not in self.peers and len(self.peers) < self.max_peers:
                        peer = Peer(
                            ip=peer_info["ip"],
                            port=peer_info["port"],
                            info_hash=self.magnet.info_hash,
                            peer_id=self.peer_id,
                        )
                        self.peers[peer_key] = peer

            except Exception as e:
                logger.debug(f"Failed to get peers from {tracker_url}: {e}")
                continue

    async def _fetch_from_peers(self) -> bytes | None:
        """Try to fetch metadata from discovered peers."""
        # Create tasks for concurrent connection attempts
        tasks = []
        for peer_key, peer in list(self.peers.items())[:20]:  # Try first 20 peers
            tasks.append(self._try_fetch_from_peer(peer_key, peer))

        # Run concurrently with timeout
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, bytes):
                return result

        return None

    async def _try_fetch_from_peer(self, peer_key: str, peer: Peer) -> bytes | None:
        """
        Try to fetch metadata from a single peer.

        Args:
            peer_key: Peer identifier
            peer: Peer object

        Returns:
            Metadata bytes if successful, None otherwise
        """
        try:
            # Connect with extension support
            if not await peer.connect_for_metadata(timeout=10.0):
                logger.debug(f"Peer {peer_key} doesn't support metadata exchange")
                await peer.disconnect()
                return None

            logger.info(f"Connected to {peer_key}, metadata size: {peer.metadata_size}")

            # Fetch metadata
            metadata = await peer.fetch_metadata()

            if metadata:
                logger.info(f"Successfully fetched metadata from {peer_key}")
                return metadata

            await peer.disconnect()
            return None

        except Exception as e:
            logger.debug(f"Failed to fetch metadata from {peer_key}: {e}")
            await peer.disconnect()
            return None


async def create_parser_from_magnet(magnet_uri: str) -> tuple[TorrentParser, bytes] | None:
    """
    Create a TorrentParser from a magnet link by fetching metadata.

    Args:
        magnet_uri: The magnet URI

    Returns:
        Tuple of (TorrentParser, info_hash_bytes) if successful, None otherwise
    """
    # Parse magnet link
    magnet = MagnetLink.parse(magnet_uri)

    logger.info(f"Magnet link info hash: {magnet.info_hash_hex}")
    if magnet.display_name:
        logger.info(f"Display name: {magnet.display_name}")
    logger.info(f"Trackers: {len(magnet.trackers)}")

    # Fetch metadata
    fetcher = MetadataFetcher(magnet)
    metadata = await fetcher.fetch()

    if not metadata:
        logger.error("Failed to fetch metadata from any peer")
        return None

    # Create parser from metadata
    parser = TorrentParser()
    parser.parse_from_metadata(metadata, trackers=magnet.trackers, info_hash=magnet.info_hash)

    return (parser, magnet.info_hash)


def get_input_type(input_str: str) -> str:
    """
    Determine if input is a magnet link or torrent file path.

    Args:
        input_str: Input string (magnet URI or file path)

    Returns:
        'magnet' or 'file'
    """
    if is_magnet_link(input_str):
        return "magnet"
    return "file"
