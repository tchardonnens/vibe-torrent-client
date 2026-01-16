"""
Main BitTorrent client implementation.
"""

import asyncio
import hashlib
import time
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional, Set, Deque
import logging

from torrent_parser import TorrentParser
from tracker import Tracker, generate_peer_id
from peer import Peer, MessageType
from piece_manager import PieceManager, PieceStatus, Block
from file_manager import FileManager
from tui import TorrentTUI


logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


class TorrentClient:
    """Main BitTorrent client."""
    
    def __init__(self, torrent_path: str, output_dir: str = "./downloads") -> None:
        """
        Initialize torrent client.
        
        Args:
            torrent_path: Path to .torrent file
            output_dir: Directory to save downloaded files
        """
        self.torrent_path = torrent_path
        self.output_dir = Path(output_dir)
        self.parser = TorrentParser(torrent_path)
        self.torrent_data: Optional[Dict] = None
        self.info_hash: bytes = b''
        self.peer_id: bytes = generate_peer_id()
        self.port = 6881
        
        # Components
        self.piece_manager: Optional[PieceManager] = None
        self.file_manager: Optional[FileManager] = None
        
        # Peer management
        self.peers: Dict[str, Peer] = {}
        self.max_peers = 120
        self.active_peers: Set[str] = set()
        self.failed_peers: Dict[str, float] = {}  # peer_key -> timestamp of last failure
        self.failed_peer_backoff = 60.0  # Wait 60 seconds before retrying failed peers
        
        # Download state
        self.downloading = False
        self.completed = False
        
        # Tracker update throttling
        self.last_tracker_update: float = 0.0
        self.tracker_update_interval = 30.0  # Update tracker every 30 seconds
        
        # Parallel download settings
        self.max_pipeline_blocks = 64  # Number of blocks to request in parallel per piece
        self.max_concurrent_pieces_per_peer = 8  # Number of pieces to download in parallel per peer

        # Availability tracking for rarest-first selection
        self.piece_availability: List[int] = []
        
        # Speed tracking
        self.piece_completion_times: Deque[float] = deque(maxlen=100)  # Track last 100 piece completions
        self.block_completion_times: Deque[float] = deque(maxlen=500)  # Track last 500 block completions
        self.start_time: Optional[float] = None
        self.tui: Optional[TorrentTUI] = None
        
    async def start(self) -> None:
        """Start the torrent client."""
        logger.info("Starting torrent client...")
        
        # Parse torrent file
        self.torrent_data = self.parser.parse()
        self.info_hash = bytes.fromhex(self.parser.get_info_hash())
        
        logger.info(f"Torrent: {self.parser.get_name()}")
        logger.info(f"Info Hash: {self.parser.get_info_hash()}")
        logger.info(f"Total Size: {self._format_size(self.parser.get_total_size())}")
        
        # Initialize piece manager
        pieces = self._extract_pieces()
        total_pieces = self.parser.get_piece_count()
        self.piece_manager = PieceManager(pieces, total_pieces)
        self.piece_availability = [0] * total_pieces
        
        # Initialize file manager
        files = self.parser.get_files()
        piece_length = self.parser.get_piece_length()
        self.file_manager = FileManager(self.output_dir, files, piece_length)
        
        logger.info(f"Pieces: {total_pieces}")
        logger.info(f"Piece Length: {self._format_size(piece_length)}")
        
        # Initialize TUI
        total_size = self.parser.get_total_size()
        self.tui = TorrentTUI(self.parser.get_name(), total_pieces, total_size)
        self.tui.start()
        
        # Start downloading
        self.downloading = True
        self.start_time = time.time()
        await self._download_loop()
    
    def _extract_pieces(self) -> List[tuple]:
        """
        Extract piece information from torrent.
        
        Returns:
            List of (index, length, hash) tuples
        """
        if 'info' not in self.torrent_data:
            return []
        
        info = self.torrent_data['info']
        pieces_data = info.get('pieces', b'')
        piece_length = info.get('piece length', 0)
        total_size = self.parser.get_total_size()
        
        if not isinstance(pieces_data, bytes):
            return []
        
        pieces = []
        total_pieces = len(pieces_data) // 20  # Each hash is 20 bytes
        
        for i in range(total_pieces):
            piece_hash = pieces_data[i * 20:(i + 1) * 20]
            
            # Calculate actual piece length (last piece may be shorter)
            if i == total_pieces - 1:
                actual_length = total_size - (i * piece_length)
            else:
                actual_length = piece_length
            
            pieces.append((i, actual_length, piece_hash))
        
        return pieces

    def _update_piece_availability(self, peer: Peer, pieces: Set[int]) -> None:
        """Track availability counts for rarest-first selection."""
        if not self.piece_availability:
            return

        new_pieces = pieces - peer.counted_pieces
        if not new_pieces:
            return

        for piece_index in new_pieces:
            if 0 <= piece_index < len(self.piece_availability):
                self.piece_availability[piece_index] += 1
        peer.counted_pieces.update(new_pieces)

    def _decrement_peer_availability(self, peer: Peer) -> None:
        """Remove a peer's contribution from availability counts."""
        if not self.piece_availability or not peer.counted_pieces:
            return

        for piece_index in peer.counted_pieces:
            if 0 <= piece_index < len(self.piece_availability):
                self.piece_availability[piece_index] = max(
                    0,
                    self.piece_availability[piece_index] - 1
                )
        peer.counted_pieces.clear()
    
    async def _download_loop(self) -> None:
        """Main download loop."""
        last_update_time = time.time()
        
        while self.downloading and not self.completed:
            try:
                # Get peers from tracker (throttled)
                current_time = time.time()
                if current_time - self.last_tracker_update >= self.tracker_update_interval:
                    await self._update_peers()
                    self.last_tracker_update = current_time
                
                # Connect to new peers
                await self._connect_to_peers()
                
                # Download pieces from peers
                await self._download_from_peers()
                
                # Check if download is complete
                completed, total, percentage = self.piece_manager.get_progress()
                
                # Update TUI
                if self.tui:
                    pieces_per_sec = self._calculate_pieces_per_second()
                    chunks_per_sec = self._calculate_chunks_per_second()
                    downloaded_bytes = await self.piece_manager.get_completed_bytes()
                    self.tui.update(
                        completed_pieces=completed,
                        pieces_per_sec=pieces_per_sec,
                        chunks_per_sec=chunks_per_sec,
                        active_peers=len(self.active_peers),
                        total_peers=len(self.peers),
                        downloaded_bytes=downloaded_bytes
                    )
                
                if completed == total:
                    logger.info("Download complete!")
                    self.completed = True
                    break
                
                # Wait before next iteration (shorter for more responsive updates)
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"Error in download loop: {e}")
                await asyncio.sleep(1)
        
        # Cleanup
        await self._cleanup()
    
    async def _update_peers(self) -> None:
        """Update peer list from tracker."""
        announce_urls = self.parser.get_announce_urls()
        max_total_peers = self.max_peers * 4
        total_added = 0

        for url in announce_urls[:5]:  # Query multiple trackers for a broader peer set
            try:
                tracker = Tracker(
                    announce_url=url,
                    info_hash=self.info_hash,
                    peer_id=self.peer_id,
                    port=self.port,
                    downloaded=0,  # TODO: Track actual downloaded bytes
                    left=self.parser.get_total_size(),
                    event="started",
                    numwant=max_total_peers
                )
                
                response = await tracker.announce()
                peers = response.get('peers', [])
                
                logger.info(f"Got {len(peers)} peers from {url}")
                
                # Add new peers
                for peer_info in peers:
                    if len(self.peers) >= max_total_peers:
                        break
                    peer_key = f"{peer_info['ip']}:{peer_info['port']}"
                    if peer_key not in self.peers:
                        peer = Peer(
                            ip=peer_info['ip'],
                            port=peer_info['port'],
                            info_hash=self.info_hash,
                            peer_id=self.peer_id
                        )
                        self.peers[peer_key] = peer
                        total_added += 1

                if len(self.peers) >= max_total_peers:
                    break
                
            except Exception as e:
                logger.warning(f"Failed to get peers from {url}: {e}")
                continue
    
    async def _connect_to_peers(self) -> None:
        """Connect to available peers."""
        tasks = []
        current_time = time.time()
        
        for peer_key, peer in list(self.peers.items()):
            if peer_key in self.active_peers:
                continue
            
            # Skip peers that failed recently (backoff)
            if peer_key in self.failed_peers:
                last_failure = self.failed_peers[peer_key]
                if current_time - last_failure < self.failed_peer_backoff:
                    continue
                # Backoff period expired, remove from failed list
                del self.failed_peers[peer_key]
            
            if len(self.active_peers) >= self.max_peers:
                break
            
            tasks.append(self._connect_and_handshake(peer_key, peer))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _connect_and_handshake(self, peer_key: str, peer: Peer) -> None:
        """Connect to a peer and perform handshake."""
        try:
            connected = await peer.connect()
            if connected:
                self.active_peers.add(peer_key)
                # Remove from failed list if it was there
                self.failed_peers.pop(peer_key, None)
                logger.info(f"Connected to {peer_key}")
                
                # Start peer handler
                asyncio.create_task(self._handle_peer(peer_key, peer))
            else:
                # Connection failed, add to failed list
                self.failed_peers[peer_key] = time.time()
        except Exception as e:
            logger.debug(f"Failed to connect to {peer_key}: {e}")
            # Connection failed, add to failed list
            self.failed_peers[peer_key] = time.time()
    
    async def _handle_peer(self, peer_key: str, peer: Peer) -> None:
        """Handle communication with a peer."""
        # Message queue for routing PIECE messages to piece downloaders
        message_queue: asyncio.Queue = asyncio.Queue()
        piece_waiters: Dict[tuple[int, int], asyncio.Future] = {}  # (piece_index, block_offset) -> Future
        
        try:
            # Send interested message
            await peer.send_interested()
            
            # Receive initial bitfield/have (best-effort)
            try:
                msg_type, payload = await asyncio.wait_for(
                    peer.receive_message(),
                    timeout=10.0
                )
                
                if msg_type == MessageType.BITFIELD:
                    await peer.handle_bitfield(payload)
                    self._update_piece_availability(peer, peer.bitfield or set())
                elif msg_type == MessageType.HAVE:
                    await peer.handle_have(payload)
                    self._update_piece_availability(peer, peer.pieces_have)
                elif msg_type == MessageType.UNCHOKE:
                    await peer.handle_unchoke()
                elif msg_type == MessageType.CHOKE:
                    await peer.handle_choke()
            except asyncio.TimeoutError:
                logger.debug(f"Timeout waiting for initial message from {peer_key}")
            
            # Start message receiver task (stays alive across chokes)
            receiver_task = asyncio.create_task(
                self._message_receiver(peer, message_queue, piece_waiters)
            )
            
            try:
                # Wait for unchoke before downloading
                while peer.remote_choked and self.downloading:
                    await asyncio.sleep(0.5)
                
                # Start downloading from this peer
                await self._download_from_peer(peer, message_queue, piece_waiters)
            finally:
                receiver_task.cancel()
                try:
                    await receiver_task
                except asyncio.CancelledError:
                    pass
        
        finally:
            # Mark as failed before disconnecting (so we don't immediately reconnect)
            was_active = peer_key in self.active_peers
            await peer.disconnect()
            self._decrement_peer_availability(peer)
            self.active_peers.discard(peer_key)
            # Mark as failed if it was an active connection that dropped
            if was_active:
                self.failed_peers[peer_key] = time.time()
    
    async def _message_receiver(
        self,
        peer: Peer,
        message_queue: asyncio.Queue,
        piece_waiters: Dict[tuple[int, int], asyncio.Future]
    ) -> None:
        """Background task to receive and route messages from peer."""
        while self.downloading and peer.connected:
            try:
                msg_type, payload = await asyncio.wait_for(
                    peer.receive_message(),
                    timeout=1.0
                )
                
                if msg_type == MessageType.PIECE:
                    # Parse piece message: <index><begin><block>
                    if len(payload) >= 8:
                        piece_index = int.from_bytes(payload[0:4], 'big')
                        begin = int.from_bytes(payload[4:8], 'big')
                        block_data = payload[8:]
                        
                        # Route to waiting piece downloader
                        key = (piece_index, begin)
                        if key in piece_waiters:
                            future = piece_waiters.pop(key)
                            if not future.done():
                                future.set_result(block_data)
                        else:
                            # Store in queue for later pickup
                            await message_queue.put((piece_index, begin, block_data))
                
                elif msg_type == MessageType.CHOKE:
                    await peer.handle_choke()
                    # Cancel all waiting futures
                    for future in piece_waiters.values():
                        if not future.done():
                            future.cancel()
                    piece_waiters.clear()
                    continue
                
                elif msg_type == MessageType.UNCHOKE:
                    await peer.handle_unchoke()
                
                elif msg_type == MessageType.HAVE:
                    await peer.handle_have(payload)
                    self._update_piece_availability(peer, peer.pieces_have)
                
                elif msg_type == MessageType.BITFIELD:
                    await peer.handle_bitfield(payload)
                    self._update_piece_availability(peer, peer.bitfield or set())
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.debug(f"Error in message receiver: {e}")
                peer.connected = False
                break
    
    async def _download_from_peer(
        self,
        peer: Peer,
        message_queue: asyncio.Queue,
        piece_waiters: Dict[tuple[int, int], asyncio.Future]
    ) -> None:
        """Download pieces from a specific peer in parallel."""
        # Download multiple pieces in parallel
        download_tasks: List[asyncio.Task] = []
        
        while self.downloading and peer.connected:
            # Clean up completed tasks
            download_tasks = [t for t in download_tasks if not t.done()]
            
            if peer.remote_choked:
                await asyncio.sleep(0.5)
                continue
            
            # Refresh pieces peer has
            if peer.bitfield:
                peer_pieces = peer.bitfield
            else:
                peer_pieces = peer.pieces_have
            
            if not peer_pieces:
                await asyncio.sleep(0.5)
                continue
            
            # Start new piece downloads up to max concurrent
            while len(download_tasks) < self.max_concurrent_pieces_per_peer:
                piece = self.piece_manager.get_next_piece_to_download(
                    peer_pieces,
                    availability=self.piece_availability
                )
                if not piece:
                    break
                
                # Mark as downloading
                if not await self.piece_manager.mark_piece_downloading(piece.index):
                    continue
                
                # Start downloading this piece
                task = asyncio.create_task(
                    self._download_piece(peer, piece, message_queue, piece_waiters)
                )
                task.piece_index = piece.index
                download_tasks.append(task)
            
            if not download_tasks:
                break
            
            # Wait for at least one task to complete
            done, pending = await asyncio.wait(
                download_tasks,
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # Process completed tasks
            for task in done:
                try:
                    success, piece_index = await task
                    if success:
                        await self.piece_manager.mark_piece_complete(piece_index)
                        # Track piece completion time
                        self.piece_completion_times.append(time.time())
                    else:
                        await self.piece_manager.mark_piece_failed(piece_index)
                except Exception as e:
                    logger.debug(f"Error in piece download task: {e}")
                    # Try to get piece_index from task if possible
                    if hasattr(task, 'piece_index'):
                        await self.piece_manager.mark_piece_failed(task.piece_index)
        
        # Wait for remaining tasks
        if download_tasks:
            results = await asyncio.gather(*download_tasks, return_exceptions=True)
            for task, result in zip(download_tasks, results):
                if isinstance(result, Exception):
                    logger.debug(f"Error in piece download task: {result}")
                    if hasattr(task, 'piece_index'):
                        await self.piece_manager.mark_piece_failed(task.piece_index)
                    continue
                success, piece_index = result
                if success:
                    await self.piece_manager.mark_piece_complete(piece_index)
                    self.piece_completion_times.append(time.time())
                else:
                    await self.piece_manager.mark_piece_failed(piece_index)
    
    async def _download_piece(
        self,
        peer: Peer,
        piece,
        message_queue: asyncio.Queue,
        piece_waiters: Dict[tuple[int, int], asyncio.Future]
    ) -> tuple[bool, int]:
        """
        Download a single piece from a peer with pipelined block requests.
        
        Returns:
            Tuple of (success, piece_index)
        """
        pending_blocks: Dict[tuple[int, int], Block] = {}  # (piece_index, offset) -> Block
        block_futures: Dict[asyncio.Future, tuple[int, int]] = {}  # future -> (piece_index, offset)
        timeout_count = 0

        async def drain_message_queue_for_piece() -> None:
            """Consume queued blocks for this piece without starving other pieces."""
            if message_queue.empty():
                return
            leftovers: List[tuple[int, int, bytes]] = []
            while True:
                try:
                    queued_piece_index, block_offset, block_data = message_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if queued_piece_index != piece.index:
                    leftovers.append((queued_piece_index, block_offset, block_data))
                    continue

                key = (queued_piece_index, block_offset)
                future = piece_waiters.pop(key, None)
                if future and not future.done():
                    future.set_result(block_data)
                    continue

                if key in pending_blocks:
                    pending_blocks.pop(key)
                await self.piece_manager.add_block_data(
                    queued_piece_index,
                    block_offset,
                    block_data
                )
                await self.piece_manager.mark_block_received(queued_piece_index, block_offset)
                self.block_completion_times.append(time.time())

            for item in leftovers:
                await message_queue.put(item)
        
        try:
            # Pipeline: request multiple blocks in parallel
            while True:
                # Check if piece is complete
                if await self.piece_manager.is_piece_complete(piece.index):
                    break

                await drain_message_queue_for_piece()
                
                # Request blocks up to pipeline limit
                sent_requests = 0
                while len(pending_blocks) < self.max_pipeline_blocks:
                    block = await self.piece_manager.get_next_block_to_request(piece.index)
                    if not block:
                        break
                    
                    # Check if piece is complete
                    if await self.piece_manager.is_piece_complete(piece.index):
                        break
                    
                    key = (piece.index, block.offset)
                    future = asyncio.Future()
                    piece_waiters[key] = future
                    block_futures[future] = key
                    key = (piece.index, block.offset)
                    pending_blocks[key] = block

                    # Mark and request block
                    await self.piece_manager.mark_block_requested(piece.index, block.offset)
                    await peer.send_request(piece.index, block.offset, block.length, drain=False)
                    sent_requests += 1

                if sent_requests:
                    await peer.flush()
                
                if not pending_blocks:
                    break
                
                await drain_message_queue_for_piece()

                # Wait for at least one block to arrive
                wait_futures = [future for future, key in block_futures.items() if key in pending_blocks]
                if not wait_futures:
                    await asyncio.sleep(0)
                    continue
                done, pending = await asyncio.wait(
                    wait_futures,
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=30.0
                )
                
                if not done:
                    # Timeout - mark pending blocks as failed and retry
                    logger.debug(f"Timeout waiting for blocks for piece {piece.index}")
                    timeout_count += 1
                    for key in list(pending_blocks.keys()):
                        if key in piece_waiters:
                            future = piece_waiters.pop(key)
                            if not future.done():
                                future.cancel()
                            block_futures.pop(future, None)
                        await self.piece_manager.mark_block_received(key[0], key[1])
                        pending_blocks.pop(key)
                    if timeout_count >= 3:
                        break
                    await asyncio.sleep(0.5)
                    continue
                
                # Process received blocks
                for future in done:
                    try:
                        block_data = await future
                        # Find which block this is for using our mapping
                        key = block_futures.get(future)
                        if key and key in pending_blocks:
                            piece_index, block_offset = key
                            
                            # Add block data
                            await self.piece_manager.add_block_data(
                                piece_index,
                                block_offset,
                                block_data
                            )
                            await self.piece_manager.mark_block_received(piece_index, block_offset)
                            self.block_completion_times.append(time.time())
                            
                            # Remove from pending
                            pending_blocks.pop(key)
                            if key in piece_waiters:
                                piece_waiters.pop(key)
                            block_futures.pop(future, None)
                    except asyncio.CancelledError:
                        # Block was cancelled (peer choked)
                        return (False, piece.index)
                    except Exception as e:
                        logger.debug(f"Error processing block: {e}")
                        # Remove failed block from pending
                        for key in list(pending_blocks.keys()):
                            if key in piece_waiters and piece_waiters[key] == future:
                                pending_blocks.pop(key)
                                if key in piece_waiters:
                                    piece_waiters.pop(key)
                                break
                
                # Check for choke
                if peer.remote_choked:
                    # Cancel pending futures
                    for key in list(pending_blocks.keys()):
                        if key in piece_waiters:
                            future = piece_waiters.pop(key)
                            if not future.done():
                                future.cancel()
                            await self.piece_manager.mark_block_received(key[0], key[1])
                    return (False, piece.index)
            
            # Check for any remaining blocks in queue
            while not message_queue.empty():
                try:
                    piece_index, block_offset, block_data = message_queue.get_nowait()
                    if piece_index == piece.index:
                        await self.piece_manager.add_block_data(
                            piece_index,
                            block_offset,
                            block_data
                        )
                        await self.piece_manager.mark_block_received(piece_index, block_offset)
                        # Track block completion time
                        self.block_completion_times.append(time.time())
                except asyncio.QueueEmpty:
                    break
            
            # Assemble piece
            piece_data = await self.piece_manager.assemble_piece(piece.index)
            if not piece_data:
                return (False, piece.index)
            
            # Verify piece
            if not self.piece_manager.verify_piece(piece.index, piece_data):
                logger.warning(f"Piece {piece.index} verification failed")
                return (False, piece.index)
            
            # Write to file
            self.file_manager.write_piece(piece.index, piece_data)
            
            logger.info(f"Downloaded and verified piece {piece.index}")
            return (True, piece.index)
        
        except Exception as e:
            logger.debug(f"Error downloading piece {piece.index}: {e}")
            return (False, piece.index)
        finally:
            # Clean up any remaining futures for this piece
            for key in list(piece_waiters.keys()):
                if key[0] == piece.index:
                    future = piece_waiters.pop(key)
                    if not future.done():
                        future.cancel()
                    block_futures.pop(future, None)
    
    async def _download_from_peers(self) -> None:
        """Download pieces from all active peers."""
        # This is handled by individual peer handlers
        await asyncio.sleep(1)
    
    async def _cleanup(self) -> None:
        """Cleanup resources."""
        logger.info("Cleaning up...")
        
        # Close TUI
        if self.tui:
            self.tui.stop()
            self.tui = None
        
        # Disconnect all peers
        for peer in self.peers.values():
            await peer.disconnect()
        
        # Close file handles
        if self.file_manager:
            self.file_manager.close_all()
        
        self.downloading = False
    
    def stop(self) -> None:
        """Stop the client."""
        self.downloading = False
    
    def _calculate_pieces_per_second(self) -> float:
        """
        Calculate pieces downloaded per second based on recent completions.
        
        Returns:
            Pieces per second (0.0 if no data)
        """
        if len(self.piece_completion_times) < 2:
            if self.start_time and len(self.piece_completion_times) > 0:
                elapsed = time.time() - self.start_time
                if elapsed > 0:
                    return len(self.piece_completion_times) / elapsed
            return 0.0
        
        # Calculate based on time window of recent completions
        now = time.time()
        # Look at last 10 seconds or all completions if less
        window_start = max(now - 10.0, self.piece_completion_times[0])
        recent_completions = [t for t in self.piece_completion_times if t >= window_start]
        
        if len(recent_completions) < 2:
            return 0.0
        
        time_span = recent_completions[-1] - recent_completions[0]
        if time_span > 0:
            return (len(recent_completions) - 1) / time_span
        
        return 0.0
    
    def _calculate_chunks_per_second(self) -> float:
        """
        Calculate chunks (blocks) downloaded per second based on recent completions.
        
        Returns:
            Chunks per second (0.0 if no data)
        """
        if len(self.block_completion_times) < 2:
            if self.start_time and len(self.block_completion_times) > 0:
                elapsed = time.time() - self.start_time
                if elapsed > 0:
                    return len(self.block_completion_times) / elapsed
            return 0.0
        
        # Calculate based on time window of recent completions
        now = time.time()
        # Look at last 10 seconds or all completions if less
        window_start = max(now - 10.0, self.block_completion_times[0])
        recent_completions = [t for t in self.block_completion_times if t >= window_start]
        
        if len(recent_completions) < 2:
            return 0.0
        
        time_span = recent_completions[-1] - recent_completions[0]
        if time_span > 0:
            return (len(recent_completions) - 1) / time_span
        
        return 0.0
    
    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Format bytes into human-readable size."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"
