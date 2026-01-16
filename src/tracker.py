"""
Tracker communication module for BitTorrent client.
Handles HTTP/HTTPS and UDP tracker communication.
"""

import asyncio
import random
import socket
import struct
import urllib.parse

import aiohttp


class TrackerError(Exception):
    """Exception raised for tracker communication errors."""

    pass


class Tracker:
    """Handles communication with BitTorrent trackers."""

    def __init__(
        self,
        announce_url: str,
        info_hash: bytes,
        peer_id: bytes,
        port: int = 6881,
        uploaded: int = 0,
        downloaded: int = 0,
        left: int = 0,
        event: str = "started",
        numwant: int | None = None,
    ) -> None:
        """
        Initialize tracker connection.

        Args:
            announce_url: Tracker announce URL
            info_hash: SHA-1 hash of the info dictionary (20 bytes)
            peer_id: Unique peer ID (20 bytes)
            port: Port number for incoming connections
            uploaded: Bytes uploaded so far
            downloaded: Bytes downloaded so far
            left: Bytes remaining to download
            event: Event type (started, stopped, completed)
        """
        self.announce_url = announce_url
        self.info_hash = info_hash
        self.peer_id = peer_id
        self.port = port
        self.uploaded = uploaded
        self.downloaded = downloaded
        self.left = left
        self.event = event
        self.numwant = numwant
        self.transaction_id: int | None = None

    async def announce(self) -> dict[str, any]:
        """
        Announce to tracker and get peer list.

        Returns:
            Dictionary with peer information
        """
        if self.announce_url.startswith("http://") or self.announce_url.startswith("https://"):
            return await self._announce_http()
        elif self.announce_url.startswith("udp://"):
            return await self._announce_udp()
        else:
            raise TrackerError(f"Unsupported tracker protocol: {self.announce_url}")

    async def _announce_http(self) -> dict[str, any]:
        """Announce via HTTP/HTTPS tracker."""
        params = {
            "info_hash": self.info_hash,
            "peer_id": self.peer_id,
            "port": self.port,
            "uploaded": self.uploaded,
            "downloaded": self.downloaded,
            "left": self.left,
            "compact": 1,  # Request compact peer list
            "event": self.event,
        }
        if self.numwant is not None:
            params["numwant"] = self.numwant

        # Build URL with query parameters
        parsed = urllib.parse.urlparse(self.announce_url)
        query = urllib.parse.urlencode(params, doseq=False)
        url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{query}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status != 200:
                        raise TrackerError(f"Tracker returned status {response.status}")

                    data = await response.read()
                    return self._parse_tracker_response(data)
        except TimeoutError as e:
            raise TrackerError("Tracker request timed out") from e
        except Exception as e:
            raise TrackerError(f"HTTP tracker error: {e}") from e

    async def _announce_udp(self) -> dict[str, any]:
        """Announce via UDP tracker."""
        parsed = urllib.parse.urlparse(self.announce_url)
        host = parsed.hostname
        port = parsed.port or 80

        try:
            # Create UDP socket using asyncio
            loop = asyncio.get_event_loop()
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setblocking(False)

            # Connect to tracker
            addr = (host, port)

            # Send connect request
            connection_id, transaction_id = await self._udp_connect(sock, addr, loop)

            # Send announce request
            response = await self._udp_announce(sock, addr, connection_id, transaction_id, loop)

            sock.close()
            return response
        except Exception as e:
            raise TrackerError(f"UDP tracker error: {e}") from e

    async def _udp_connect(
        self, sock: socket.socket, addr: tuple[str, int], loop: asyncio.AbstractEventLoop
    ) -> tuple[int, int]:
        """
        Send UDP connect request.

        Returns:
            Tuple of (connection_id, transaction_id)
        """
        transaction_id = random.randint(0, 0xFFFFFFFF)

        # Connect request: [0x41727101980][action=0][transaction_id]
        connect_request = struct.pack(">QII", 0x41727101980, 0, transaction_id)

        await loop.sock_sendto(sock, connect_request, addr)

        # Receive response
        try:
            data, _ = await asyncio.wait_for(loop.sock_recvfrom(sock, 16), timeout=10.0)
            if len(data) < 16:
                raise TrackerError("Invalid UDP connect response")

            action, recv_transaction_id, connection_id = struct.unpack(">IIQ", data)

            if action != 0:
                raise TrackerError(f"UDP connect failed with action {action}")
            if recv_transaction_id != transaction_id:
                raise TrackerError("Transaction ID mismatch")

            return connection_id, transaction_id
        except TimeoutError as e:
            raise TrackerError("UDP connect timeout") from e

    async def _udp_announce(
        self,
        sock: socket.socket,
        addr: tuple[str, int],
        connection_id: int,
        transaction_id: int,
        loop: asyncio.AbstractEventLoop,
    ) -> dict[str, any]:
        """Send UDP announce request."""
        # Announce request structure:
        # [connection_id][action=1][transaction_id][info_hash][peer_id]
        # [downloaded][left][uploaded][event][IP][key][num_want][port]

        event_map = {"started": 2, "stopped": 3, "completed": 1}
        event_id = event_map.get(self.event, 0)

        # Ensure info_hash and peer_id are exactly 20 bytes
        if len(self.info_hash) != 20:
            raise TrackerError(f"Info hash must be 20 bytes, got {len(self.info_hash)}")
        if len(self.peer_id) != 20:
            raise TrackerError(f"Peer ID must be 20 bytes, got {len(self.peer_id)}")

        num_want = self.numwant if self.numwant is not None else -1
        announce_request = struct.pack(
            ">QII20s20sQQQIIIiH",
            connection_id,
            1,  # action = announce
            transaction_id,
            self.info_hash,
            self.peer_id,
            self.downloaded,
            self.left,
            self.uploaded,
            event_id,
            0,  # IP (0 = use sender's IP)
            0,  # key
            num_want,  # num_want (-1 = default, use signed int)
            self.port,
        )

        await loop.sock_sendto(sock, announce_request, addr)

        try:
            data, _ = await asyncio.wait_for(loop.sock_recvfrom(sock, 4096), timeout=10.0)
            if len(data) < 20:
                raise TrackerError("Invalid UDP announce response")

            action, recv_transaction_id = struct.unpack(">II", data[:8])

            if action != 1:
                raise TrackerError(f"UDP announce failed with action {action}")
            if recv_transaction_id != transaction_id:
                raise TrackerError("Transaction ID mismatch")

            # Parse response: [action][transaction_id][interval][leechers][seeders][peers...]
            interval, leechers, seeders = struct.unpack(">III", data[8:20])

            # Parse compact peer list (6 bytes per peer: 4 bytes IP + 2 bytes port)
            peers_data = data[20:]
            peers = []

            for i in range(0, len(peers_data), 6):
                if i + 6 > len(peers_data):
                    break
                ip_bytes, port = struct.unpack(">IH", peers_data[i : i + 6])
                ip = socket.inet_ntoa(struct.pack(">I", ip_bytes))
                peers.append({"ip": ip, "port": port})

            return {"interval": interval, "complete": seeders, "incomplete": leechers, "peers": peers}
        except TimeoutError as e:
            raise TrackerError("UDP announce timeout") from e

    def _parse_tracker_response(self, data: bytes) -> dict[str, any]:
        """
        Parse bencoded tracker response.

        Args:
            data: Bencoded response data

        Returns:
            Parsed tracker response dictionary
        """

        # Create a temporary parser to decode the response
        class TempParser:
            def __init__(self, data: bytes):
                self._raw_data = data

            def _decode_bencode(self, data: bytes, index: int) -> tuple[any, int]:
                if index >= len(data):
                    raise ValueError(f"Unexpected end of data at index {index}")

                char = data[index : index + 1]

                if char == b"i":
                    end_index = data.find(b"e", index + 1)
                    if end_index == -1:
                        raise ValueError(f"Unterminated integer at index {index}")
                    value = int(data[index + 1 : end_index])
                    return value, end_index + 1

                elif char == b"l":
                    index += 1
                    result = []
                    while index < len(data) and data[index : index + 1] != b"e":
                        value, index = self._decode_bencode(data, index)
                        result.append(value)
                    if index >= len(data):
                        raise ValueError(f"Unterminated list at index {index}")
                    return result, index + 1

                elif char == b"d":
                    index += 1
                    result = {}
                    while index < len(data) and data[index : index + 1] != b"e":
                        key, index = self._decode_bencode(data, index)
                        value, index = self._decode_bencode(data, index)
                        if isinstance(key, bytes):
                            key = key.decode("utf-8", errors="replace")
                        result[key] = value
                    if index >= len(data):
                        raise ValueError(f"Unterminated dictionary at index {index}")
                    return result, index + 1

                elif char.isdigit():
                    colon_index = data.find(b":", index)
                    if colon_index == -1:
                        raise ValueError(f"No colon found for string at index {index}")
                    length = int(data[index:colon_index])
                    start_index = colon_index + 1
                    end_index = start_index + length
                    if end_index > len(data):
                        raise ValueError(f"String length exceeds data at index {index}")
                    value = data[start_index:end_index]
                    return value, end_index

                else:
                    raise ValueError(f"Unexpected character at index {index}")

        parser = TempParser(data)
        response, _ = parser._decode_bencode(data, 0)

        if not isinstance(response, dict):
            raise TrackerError("Invalid tracker response format")

        # Parse peers (can be compact or list format)
        peers = []
        if "peers" in response:
            peers_data = response["peers"]

            # Compact format: binary string with 6 bytes per peer
            if isinstance(peers_data, bytes):
                for i in range(0, len(peers_data), 6):
                    if i + 6 > len(peers_data):
                        break
                    ip_bytes, port = struct.unpack(">IH", peers_data[i : i + 6])
                    ip = socket.inet_ntoa(struct.pack(">I", ip_bytes))
                    peers.append({"ip": ip, "port": port})
            # List format: list of dictionaries
            elif isinstance(peers_data, list):
                for peer in peers_data:
                    if isinstance(peer, dict):
                        ip = peer.get("ip", b"")
                        if isinstance(ip, bytes):
                            ip = ip.decode("utf-8", errors="replace")
                        port = peer.get("port", 0)
                        peers.append({"ip": ip, "port": port})

        return {
            "interval": response.get("interval", 1800),
            "complete": response.get("complete", 0),
            "incomplete": response.get("incomplete", 0),
            "peers": peers,
        }


def generate_peer_id() -> bytes:
    """
    Generate a random peer ID.

    Returns:
        20-byte peer ID
    """
    # BitTorrent peer ID format: -<client_id><random>
    # Using '-TS' as client ID (Torrent Study)
    client_id = b"-TS0001-"
    random_bytes = bytes([random.randint(0, 255) for _ in range(12)])
    return client_id + random_bytes
