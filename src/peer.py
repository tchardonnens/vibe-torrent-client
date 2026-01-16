"""
BitTorrent peer protocol implementation.
Handles peer connections, handshakes, and message exchange.
"""

import asyncio
import struct
from enum import IntEnum


class MessageType(IntEnum):
    """BitTorrent protocol message types."""

    CHOKE = 0
    UNCHOKE = 1
    INTERESTED = 2
    NOT_INTERESTED = 3
    HAVE = 4
    BITFIELD = 5
    REQUEST = 6
    PIECE = 7
    CANCEL = 8
    PORT = 9
    KEEP_ALIVE = -1  # Special case: no message ID, length = 0


class PeerError(Exception):
    """Exception raised for peer communication errors."""

    pass


class Peer:
    """Represents a BitTorrent peer connection."""

    def __init__(self, ip: str, port: int, info_hash: bytes, peer_id: bytes) -> None:
        """
        Initialize peer connection.

        Args:
            ip: Peer IP address
            port: Peer port
            info_hash: SHA-1 hash of the info dictionary
            peer_id: Our peer ID
        """
        self.ip = ip
        self.port = port
        self.info_hash = info_hash
        self.peer_id = peer_id
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.remote_peer_id: bytes | None = None
        self.bitfield: set[int] | None = None
        self.choked = True
        self.interested = False
        self.remote_choked = True
        self.remote_interested = False
        self.connected = False
        self.pieces_have: set[int] = set()
        self.counted_pieces: set[int] = set()

    async def connect(self, timeout: float = 10.0) -> bool:
        """
        Connect to peer and perform handshake.

        Args:
            timeout: Connection timeout in seconds

        Returns:
            True if connection successful, False otherwise
        """
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.ip, self.port), timeout=timeout
            )

            # Perform handshake
            await self._handshake()
            self.connected = True
            return True
        except TimeoutError:
            await self._safe_close()
            return False
        except Exception:
            await self._safe_close()
            return False

    async def _safe_close(self) -> None:
        """Best-effort close of the underlying stream."""
        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except Exception:
                pass
        self.connected = False
        self.reader = None
        self.writer = None

    async def _handshake(self) -> None:
        """Perform BitTorrent handshake."""
        # Handshake format:
        # <pstrlen><pstr><reserved><info_hash><peer_id>
        # pstr = "BitTorrent protocol"
        # pstrlen = 19
        # reserved = 8 bytes (all zeros for basic protocol)

        handshake = struct.pack(
            ">B19s8s20s20s",
            19,  # pstrlen
            b"BitTorrent protocol",  # pstr
            b"\x00" * 8,  # reserved
            self.info_hash,
            self.peer_id,
        )

        self.writer.write(handshake)
        await self.writer.drain()

        # Read response
        response = await self.reader.read(68)  # 1 + 19 + 8 + 20 + 20 = 68

        if len(response) < 68:
            raise PeerError("Invalid handshake response length")

        pstrlen = response[0]
        if pstrlen != 19:
            raise PeerError(f"Invalid protocol string length: {pstrlen}")

        pstr = response[1:20]
        if pstr != b"BitTorrent protocol":
            raise PeerError(f"Invalid protocol string: {pstr}")

        # Extract info_hash and peer_id
        response_info_hash = response[28:48]
        self.remote_peer_id = response[48:68]

        if response_info_hash != self.info_hash:
            raise PeerError("Info hash mismatch in handshake")

    async def send_message(self, message_type: MessageType, payload: bytes = b"", drain: bool = True) -> None:
        """
        Send a message to the peer.

        Args:
            message_type: Type of message to send
            payload: Message payload (if any)
            drain: Whether to drain the write buffer immediately
        """
        if not self.writer:
            raise PeerError("Not connected to peer")

        if message_type == MessageType.KEEP_ALIVE:
            # Keep-alive: 4 bytes of zeros (length = 0)
            message = struct.pack(">I", 0)
        else:
            # Message format: <length><message_id><payload>
            # length = 1 + len(payload)
            message = struct.pack(">IB", 1 + len(payload), message_type) + payload

        self.writer.write(message)
        if drain:
            await self.writer.drain()

    async def flush(self) -> None:
        """Flush buffered writes to the peer."""
        if self.writer:
            await self.writer.drain()

    async def receive_message(self, timeout: float | None = None) -> tuple[MessageType, bytes]:
        """
        Receive a message from the peer.

        Args:
            timeout: Optional timeout in seconds

        Returns:
            Tuple of (message_type, payload)
        """
        if not self.reader:
            raise PeerError("Not connected to peer")

        try:
            # Read message length (4 bytes)
            length_data = await asyncio.wait_for(self.reader.readexactly(4), timeout=timeout)
            length = struct.unpack(">I", length_data)[0]

            # Keep-alive message
            if length == 0:
                return (MessageType.KEEP_ALIVE, b"")

            # Read message ID and payload
            message_data = await asyncio.wait_for(self.reader.readexactly(length), timeout=timeout)

            message_id = message_data[0]
            payload = message_data[1:] if len(message_data) > 1 else b""

            return (MessageType(message_id), payload)
        except TimeoutError as e:
            raise PeerError("Message receive timeout") from e
        except Exception as e:
            raise PeerError(f"Error receiving message: {e}") from e

    async def send_interested(self) -> None:
        """Send INTERESTED message."""
        await self.send_message(MessageType.INTERESTED)
        self.interested = True

    async def send_not_interested(self) -> None:
        """Send NOT_INTERESTED message."""
        await self.send_message(MessageType.NOT_INTERESTED)
        self.interested = False

    async def send_unchoke(self) -> None:
        """Send UNCHOKE message."""
        await self.send_message(MessageType.UNCHOKE)
        self.choked = False

    async def send_have(self, piece_index: int) -> None:
        """Send HAVE message."""
        payload = struct.pack(">I", piece_index)
        await self.send_message(MessageType.HAVE, payload)
        self.pieces_have.add(piece_index)

    async def send_request(self, piece_index: int, block_offset: int, block_length: int, drain: bool = True) -> None:
        """
        Send REQUEST message for a block.

        Args:
            piece_index: Index of the piece
            block_offset: Offset within the piece
            block_length: Length of the block (typically 16KB)
            drain: Whether to drain the write buffer immediately
        """
        payload = struct.pack(">III", piece_index, block_offset, block_length)
        await self.send_message(MessageType.REQUEST, payload, drain=drain)

    async def send_cancel(self, piece_index: int, block_offset: int, block_length: int) -> None:
        """Send CANCEL message."""
        payload = struct.pack(">III", piece_index, block_offset, block_length)
        await self.send_message(MessageType.CANCEL, payload)

    async def handle_bitfield(self, payload: bytes) -> None:
        """
        Handle BITFIELD message from peer.

        Args:
            payload: Bitfield data
        """
        self.bitfield = set()
        for byte_index, byte_value in enumerate(payload):
            for bit_index in range(8):
                if byte_value & (1 << (7 - bit_index)):
                    piece_index = byte_index * 8 + bit_index
                    self.bitfield.add(piece_index)
                    self.pieces_have.add(piece_index)

    async def handle_have(self, payload: bytes) -> None:
        """
        Handle HAVE message from peer.

        Args:
            payload: Piece index (4 bytes)
        """
        if len(payload) != 4:
            return
        piece_index = struct.unpack(">I", payload)[0]
        self.pieces_have.add(piece_index)
        if self.bitfield is not None:
            self.bitfield.add(piece_index)

    async def handle_unchoke(self) -> None:
        """Handle UNCHOKE message from peer."""
        self.remote_choked = False

    async def handle_choke(self) -> None:
        """Handle CHOKE message from peer."""
        self.remote_choked = True

    def has_piece(self, piece_index: int) -> bool:
        """
        Check if peer has a specific piece.

        Args:
            piece_index: Index of the piece

        Returns:
            True if peer has the piece
        """
        if self.bitfield:
            return piece_index in self.bitfield
        return piece_index in self.pieces_have

    async def disconnect(self) -> None:
        """Close connection to peer."""
        await self._safe_close()
