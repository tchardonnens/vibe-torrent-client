"""
BitTorrent peer protocol implementation.
Handles peer connections, handshakes, and message exchange.
Supports BEP 9 (Extension for Peers to Send Metadata Files).
"""

import asyncio
import hashlib
import struct
from enum import IntEnum
from typing import Any

from magnet import bencode_decode, bencode_encode


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
    EXTENDED = 20  # BEP 10 Extension Protocol
    KEEP_ALIVE = -1  # Special case: no message ID, length = 0


# Extension message IDs (BEP 10)
EXTENSION_HANDSHAKE = 0
UT_METADATA = 1  # Our local ID for ut_metadata extension


class ExtendedMessageType(IntEnum):
    """Extended message types for ut_metadata (BEP 9)."""

    REQUEST = 0
    DATA = 1
    REJECT = 2


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

        # Extension protocol (BEP 10 / BEP 9)
        self.supports_extensions = False
        self.extension_handshake_received = False
        self.remote_extensions: dict[str, int] = {}  # Extension name -> message ID
        self.metadata_size: int | None = None  # Size of metadata if peer supports ut_metadata

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

    async def _handshake(self, support_extensions: bool = False) -> None:
        """
        Perform BitTorrent handshake.

        Args:
            support_extensions: If True, advertise extension protocol support (BEP 10)
        """
        # Handshake format:
        # <pstrlen><pstr><reserved><info_hash><peer_id>
        # pstr = "BitTorrent protocol"
        # pstrlen = 19
        # reserved = 8 bytes
        #   - Bit 20 (0x00100000) indicates extension protocol support (BEP 10)

        reserved = bytearray(8)
        if support_extensions:
            # Set bit 20 from the right (byte 5, bit 4) to indicate extension support
            reserved[5] |= 0x10

        handshake = struct.pack(
            ">B19s8s20s20s",
            19,  # pstrlen
            b"BitTorrent protocol",  # pstr
            bytes(reserved),  # reserved
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

        # Check if peer supports extensions (bit 20 from right = byte 5, bit 4)
        remote_reserved = response[20:28]
        self.supports_extensions = bool(remote_reserved[5] & 0x10)

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

    # Extension Protocol (BEP 10) Methods

    async def send_extension_handshake(self, metadata_size: int | None = None) -> None:
        """
        Send extension protocol handshake (BEP 10).

        Args:
            metadata_size: If we have metadata, include its size
        """
        # Build extension handshake dictionary
        handshake_dict: dict[str, Any] = {
            "m": {
                "ut_metadata": UT_METADATA,  # Advertise ut_metadata support
            },
        }

        if metadata_size is not None:
            handshake_dict["metadata_size"] = metadata_size

        # Encode the handshake
        payload = bencode_encode(handshake_dict)

        # Extension message format: <extended_message_id><payload>
        # For handshake, extended_message_id = 0
        message = bytes([EXTENSION_HANDSHAKE]) + payload
        await self.send_message(MessageType.EXTENDED, message)

    async def handle_extension_message(self, payload: bytes) -> tuple[int, dict[str, Any] | bytes]:
        """
        Handle an extension protocol message.

        Args:
            payload: Extension message payload

        Returns:
            Tuple of (extension_message_id, decoded_payload)
        """
        if len(payload) < 1:
            raise PeerError("Empty extension message")

        ext_msg_id = payload[0]
        ext_payload = payload[1:]

        if ext_msg_id == EXTENSION_HANDSHAKE:
            # Decode extension handshake
            decoded, _ = bencode_decode(ext_payload)
            self.extension_handshake_received = True

            # Extract supported extensions
            if isinstance(decoded, dict):
                m = decoded.get("m", {})
                if isinstance(m, dict):
                    for ext_name, ext_id in m.items():
                        if isinstance(ext_name, str) and isinstance(ext_id, int):
                            self.remote_extensions[ext_name] = ext_id

                # Extract metadata size if available
                if "metadata_size" in decoded:
                    self.metadata_size = decoded["metadata_size"]

            return (ext_msg_id, decoded)
        else:
            # Other extension message - return raw payload
            return (ext_msg_id, ext_payload)

    async def request_metadata_piece(self, piece_index: int) -> None:
        """
        Request a metadata piece from peer (BEP 9).

        Args:
            piece_index: Index of the metadata piece to request
        """
        if "ut_metadata" not in self.remote_extensions:
            raise PeerError("Peer does not support ut_metadata")

        remote_ut_metadata_id = self.remote_extensions["ut_metadata"]

        # Build request message
        request_dict = {
            "msg_type": ExtendedMessageType.REQUEST,
            "piece": piece_index,
        }

        payload = bencode_encode(request_dict)
        message = bytes([remote_ut_metadata_id]) + payload
        await self.send_message(MessageType.EXTENDED, message)

    def parse_metadata_response(self, payload: bytes) -> tuple[int, int, bytes | None]:
        """
        Parse a metadata response from peer.

        Args:
            payload: The metadata message payload (after extension message ID)

        Returns:
            Tuple of (msg_type, piece_index, data_or_none)
            data_or_none is the metadata piece data for DATA messages, None for REJECT
        """
        # The payload is: <bencoded dict><raw metadata data>
        # We need to find where the dict ends and data begins

        decoded, end_pos = bencode_decode(payload)

        if not isinstance(decoded, dict):
            raise PeerError("Invalid metadata response format")

        msg_type = decoded.get("msg_type", -1)
        piece_index = decoded.get("piece", -1)

        if msg_type == ExtendedMessageType.DATA:
            # Data follows the bencoded dictionary
            data = payload[end_pos:]
            return (msg_type, piece_index, data)
        elif msg_type == ExtendedMessageType.REJECT:
            return (msg_type, piece_index, None)
        else:
            raise PeerError(f"Unknown metadata message type: {msg_type}")

    async def connect_for_metadata(self, timeout: float = 10.0) -> bool:
        """
        Connect to peer with extension protocol support for metadata fetching.

        Args:
            timeout: Connection timeout in seconds

        Returns:
            True if connection successful and peer supports ut_metadata
        """
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.ip, self.port), timeout=timeout
            )

            # Perform handshake with extension support
            await self._handshake(support_extensions=True)
            self.connected = True

            if not self.supports_extensions:
                return False

            # Send our extension handshake
            await self.send_extension_handshake()

            # Wait for their extension handshake
            try:
                msg_type, payload = await asyncio.wait_for(self.receive_message(), timeout=10.0)

                if msg_type == MessageType.EXTENDED:
                    await self.handle_extension_message(payload)
                elif msg_type == MessageType.BITFIELD:
                    await self.handle_bitfield(payload)
                    # Try to get extension handshake next
                    msg_type, payload = await asyncio.wait_for(self.receive_message(), timeout=10.0)
                    if msg_type == MessageType.EXTENDED:
                        await self.handle_extension_message(payload)
            except TimeoutError:
                pass

            return "ut_metadata" in self.remote_extensions and self.metadata_size is not None

        except TimeoutError:
            await self._safe_close()
            return False
        except Exception:
            await self._safe_close()
            return False

    async def fetch_metadata(self) -> bytes | None:
        """
        Fetch complete metadata from peer.

        Returns:
            Complete metadata bytes, or None if failed
        """
        if self.metadata_size is None:
            return None

        if "ut_metadata" not in self.remote_extensions:
            return None

        # Metadata is sent in 16KB pieces
        piece_size = 16384
        num_pieces = (self.metadata_size + piece_size - 1) // piece_size

        metadata_pieces: dict[int, bytes] = {}

        for piece_index in range(num_pieces):
            # Request piece
            await self.request_metadata_piece(piece_index)

            # Wait for response
            try:
                while True:
                    msg_type, payload = await asyncio.wait_for(self.receive_message(), timeout=30.0)

                    if msg_type == MessageType.EXTENDED:
                        ext_id = payload[0]
                        ext_payload = payload[1:]

                        # Check if this is a ut_metadata response
                        if ext_id == self.remote_extensions.get("ut_metadata"):
                            msg_type_meta, piece_idx, data = self.parse_metadata_response(ext_payload)

                            if msg_type_meta == ExtendedMessageType.DATA and data:
                                metadata_pieces[piece_idx] = data
                                break
                            elif msg_type_meta == ExtendedMessageType.REJECT:
                                return None

                    elif msg_type == MessageType.CHOKE:
                        await self.handle_choke()
                    elif msg_type == MessageType.UNCHOKE:
                        await self.handle_unchoke()
                    elif msg_type == MessageType.HAVE:
                        await self.handle_have(payload)
                    elif msg_type == MessageType.BITFIELD:
                        await self.handle_bitfield(payload)

            except TimeoutError:
                return None
            except Exception:
                return None

        # Assemble metadata
        if len(metadata_pieces) != num_pieces:
            return None

        metadata = b""
        for i in range(num_pieces):
            metadata += metadata_pieces[i]

        # Truncate to actual size (last piece may be padded)
        metadata = metadata[: self.metadata_size]

        # Verify hash
        if hashlib.sha1(metadata).digest() != self.info_hash:
            return None

        return metadata
