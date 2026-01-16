"""
Piece manager for downloading and verifying torrent pieces.
"""

import asyncio
import hashlib
from dataclasses import dataclass
from enum import Enum


class PieceStatus(Enum):
    """Status of a piece."""

    MISSING = "missing"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class Block:
    """Represents a block within a piece."""

    piece_index: int
    offset: int
    length: int
    data: bytes | None = None
    requested: bool = False


@dataclass
class Piece:
    """Represents a torrent piece."""

    index: int
    length: int
    hash: bytes
    status: PieceStatus = PieceStatus.MISSING
    blocks: list[Block] = None
    blocks_by_offset: dict[int, Block] = None
    data: bytes | None = None

    def __post_init__(self) -> None:
        """Initialize blocks after creation."""
        if self.blocks is None:
            self.blocks = []
        if self.blocks_by_offset is None:
            self.blocks_by_offset = {}
            # Create blocks (typically 16KB each)
            block_size = 16 * 1024  # 16KB
            offset = 0
            while offset < self.length:
                block_length = min(block_size, self.length - offset)
                block = Block(piece_index=self.index, offset=offset, length=block_length)
                self.blocks.append(block)
                self.blocks_by_offset[offset] = block
                offset += block_length


class PieceManager:
    """Manages downloading and verifying torrent pieces."""

    def __init__(self, pieces: list[tuple[int, int, bytes]], total_pieces: int) -> None:
        """
        Initialize piece manager.

        Args:
            pieces: List of (index, length, hash) tuples
            total_pieces: Total number of pieces
        """
        self.pieces: dict[int, Piece] = {}
        self.total_pieces = total_pieces
        self.completed_pieces: set[int] = set()
        self.downloading_pieces: set[int] = set()
        self.piece_lock = asyncio.Lock()
        self.block_locks: dict[int, asyncio.Lock] = {}  # piece_index -> Lock

        # Create piece objects
        for index, length, piece_hash in pieces:
            self.pieces[index] = Piece(index=index, length=length, hash=piece_hash)
            self.block_locks[index] = asyncio.Lock()

    def get_piece(self, index: int) -> Piece | None:
        """Get a piece by index."""
        return self.pieces.get(index)

    def get_next_piece_to_download(
        self, peer_has_pieces: set[int], availability: list[int] | None = None
    ) -> Piece | None:
        """
        Get the next piece to download based on peer availability.

        Args:
            peer_has_pieces: Set of piece indices the peer has
            availability: Optional list of availability counts by piece index

        Returns:
            Next piece to download or None
        """
        # Find pieces that:
        # 1. We don't have
        # 2. Peer has
        # 3. We're not currently downloading

        available_pieces = peer_has_pieces - self.completed_pieces - self.downloading_pieces

        if not available_pieces:
            return None

        # Prefer pieces with fewer peers (rarest-first strategy)
        if availability:
            ordered = sorted(
                available_pieces, key=lambda idx: (availability[idx] if idx < len(availability) else 0, idx)
            )
        else:
            ordered = sorted(available_pieces)

        for piece_index in ordered:
            piece = self.pieces.get(piece_index)
            if piece and piece.status == PieceStatus.MISSING:
                return piece

        return None

    async def mark_piece_downloading(self, piece_index: int) -> bool:
        """
        Mark a piece as being downloaded.

        Args:
            piece_index: Index of the piece

        Returns:
            True if successfully marked, False if already downloading
        """
        async with self.piece_lock:
            if piece_index in self.downloading_pieces:
                return False

            piece = self.pieces.get(piece_index)
            if not piece or piece.status != PieceStatus.MISSING:
                return False

            piece.status = PieceStatus.DOWNLOADING
            self.downloading_pieces.add(piece_index)
            return True

    async def mark_piece_complete(self, piece_index: int) -> None:
        """
        Mark a piece as complete.

        Args:
            piece_index: Index of the piece
        """
        async with self.piece_lock:
            piece = self.pieces.get(piece_index)
            if piece:
                piece.status = PieceStatus.COMPLETE
            self.completed_pieces.add(piece_index)
            self.downloading_pieces.discard(piece_index)

    async def mark_piece_failed(self, piece_index: int) -> None:
        """
        Mark a piece as failed.

        Args:
            piece_index: Index of the piece
        """
        async with self.piece_lock:
            piece = self.pieces.get(piece_index)
            if piece:
                piece.status = PieceStatus.MISSING
            self.downloading_pieces.discard(piece_index)
        await self.reset_piece(piece_index)

    async def reset_piece(self, piece_index: int) -> None:
        """
        Reset a piece's blocks so it can be re-downloaded.

        Args:
            piece_index: Index of the piece
        """
        piece = self.pieces.get(piece_index)
        if not piece:
            return

        lock = self.block_locks.get(piece_index)
        if not lock:
            return

        async with lock:
            for block in piece.blocks:
                block.data = None
                block.requested = False

    async def add_block_data(self, piece_index: int, block_offset: int, block_data: bytes) -> None:
        """
        Add block data to a piece.

        Args:
            piece_index: Index of the piece
            block_offset: Offset of the block within the piece
            block_data: Block data
        """
        piece = self.pieces.get(piece_index)
        if not piece:
            return

        lock = self.block_locks.get(piece_index)
        if not lock:
            return

        async with lock:
            block = piece.blocks_by_offset.get(block_offset)
            if block:
                block.data = block_data

    async def is_piece_complete(self, piece_index: int) -> bool:
        """
        Check if all blocks of a piece are downloaded.

        Args:
            piece_index: Index of the piece

        Returns:
            True if piece is complete
        """
        piece = self.pieces.get(piece_index)
        if not piece:
            return False

        lock = self.block_locks.get(piece_index)
        if not lock:
            return False

        async with lock:
            return all(block.data is not None for block in piece.blocks)

    async def assemble_piece(self, piece_index: int) -> bytes | None:
        """
        Assemble piece data from blocks.

        Args:
            piece_index: Index of the piece

        Returns:
            Assembled piece data or None if incomplete
        """
        piece = self.pieces.get(piece_index)
        if not piece:
            return None

        if not await self.is_piece_complete(piece_index):
            return None

        # Assemble blocks in order (blocks already built in order)
        piece_data = b"".join(block.data for block in piece.blocks if block.data)

        # Store in piece
        piece.data = piece_data
        return piece_data

    def verify_piece(self, piece_index: int, piece_data: bytes) -> bool:
        """
        Verify piece data against its hash.

        Args:
            piece_index: Index of the piece
            piece_data: Piece data to verify

        Returns:
            True if hash matches, False otherwise
        """
        piece = self.pieces.get(piece_index)
        if not piece:
            return False

        # Calculate SHA-1 hash
        piece_hash = hashlib.sha1(piece_data).digest()

        return piece_hash == piece.hash

    def get_progress(self) -> tuple[int, int, float]:
        """
        Get download progress.

        Returns:
            Tuple of (completed, total, percentage)
        """
        completed = len(self.completed_pieces)
        total = self.total_pieces
        percentage = (completed / total * 100) if total > 0 else 0.0
        return (completed, total, percentage)

    async def get_completed_bytes(self) -> int:
        """
        Get total bytes for completed pieces.

        Returns:
            Total completed bytes
        """
        async with self.piece_lock:
            return sum(self.pieces[index].length for index in self.completed_pieces if index in self.pieces)

    async def get_next_block_to_request(self, piece_index: int) -> Block | None:
        """
        Get the next block to request for a piece.

        Args:
            piece_index: Index of the piece

        Returns:
            Next block to request or None
        """
        piece = self.pieces.get(piece_index)
        if not piece:
            return None

        lock = self.block_locks.get(piece_index)
        if not lock:
            return None

        async with lock:
            # Find first block that hasn't been requested and doesn't have data
            for block in piece.blocks:
                if not block.requested and block.data is None:
                    return block

        return None

    async def mark_block_requested(self, piece_index: int, block_offset: int) -> None:
        """
        Mark a block as requested.

        Args:
            piece_index: Index of the piece
            block_offset: Offset of the block
        """
        piece = self.pieces.get(piece_index)
        if not piece:
            return

        lock = self.block_locks.get(piece_index)
        if not lock:
            return

        async with lock:
            block = piece.blocks_by_offset.get(block_offset)
            if block:
                block.requested = True

    async def mark_block_received(self, piece_index: int, block_offset: int) -> None:
        """
        Mark a block as received (reset requested flag).

        Args:
            piece_index: Index of the piece
            block_offset: Offset of the block
        """
        piece = self.pieces.get(piece_index)
        if not piece:
            return

        lock = self.block_locks.get(piece_index)
        if not lock:
            return

        async with lock:
            block = piece.blocks_by_offset.get(block_offset)
            if block:
                block.requested = False
