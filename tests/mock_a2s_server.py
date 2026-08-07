"""Mock A2S (Source Engine Query) UDP Server for testing.

Simulates Rust server responses to A2S_INFO queries, including challenge handshake,
configurable delays, packet dropping, payload corruption, and server info dynamic updates.
"""

import random
import socket
import struct
import threading
import time
from typing import Optional, Tuple


class MockA2SServer:
    """Mock UDP Server simulating Source Engine A2S_INFO protocol responses for Rust servers."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        server_name: str = "Rust Test Server",
        map_name: str = "Procedural Map",
        game_folder: str = "rust",
        game_name: str = "Rust",
        app_id: int = 25249,
        players: int = 10,
        max_players: int = 100,
        bots: int = 0,
        server_type: str = "d",
        environment: str = "w",
        visibility: int = 0,
        vac: int = 1,
        version: str = "1.0.0",
        game_port: int = 28015,
        drop_rate: float = 0.0,
        corrupt_rate: float = 0.0,
        require_challenge: bool = False,
        challenge_token: bytes = b"\x12\x34\x56\x78",
        response_delay: float = 0.0,
        delay: Optional[float] = None,
        # Legacy/alias parameter compatibility
        challenge_enabled: Optional[bool] = None,
        drop_packets: Optional[bool] = None,
        corrupt_response: Optional[bool] = None,
    ):
        self.host = host
        self.requested_port = port
        self.port = port
        self.server_name = server_name
        self.map_name = map_name
        self.game_folder = game_folder
        self.game_name = game_name
        self.app_id = app_id
        self.players = players
        self.max_players = max_players
        self.bots = bots
        self.server_type = server_type
        self.environment = environment
        self.visibility = visibility
        self.vac = vac
        self.version = version
        self.game_port = game_port

        # Configurable test flags & rates
        self._drop_rate = float(drop_rate)
        if drop_packets is not None:
            self._drop_rate = 1.0 if drop_packets else 0.0

        self._corrupt_rate = float(corrupt_rate)
        if corrupt_response is not None:
            self._corrupt_rate = 1.0 if corrupt_response else 0.0

        if challenge_enabled is not None:
            self.require_challenge = bool(challenge_enabled)
        else:
            self.require_challenge = bool(require_challenge)

        self.challenge_token = challenge_token
        if delay is not None:
            self.response_delay = float(delay)
        else:
            self.response_delay = float(response_delay)

        self.offline = False

        # Server state & stats
        self._socket: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()

        # Telemetry & query counters
        self.query_count = 0
        self.request_count = 0
        self.challenge_sent_count = 0
        self.info_sent_count = 0
        self.last_client_addr: Optional[Tuple[str, int]] = None

    @property
    def drop_rate(self) -> float:
        with self._lock:
            return self._drop_rate

    @drop_rate.setter
    def drop_rate(self, value: float) -> None:
        with self._lock:
            self._drop_rate = float(value)

    @property
    def drop_packets(self) -> bool:
        with self._lock:
            return self._drop_rate >= 1.0

    @drop_packets.setter
    def drop_packets(self, value: bool) -> None:
        with self._lock:
            self._drop_rate = 1.0 if value else 0.0

    @property
    def corrupt_rate(self) -> float:
        with self._lock:
            return self._corrupt_rate

    @corrupt_rate.setter
    def corrupt_rate(self, value: float) -> None:
        with self._lock:
            self._corrupt_rate = float(value)

    @property
    def corrupt_response(self) -> bool:
        with self._lock:
            return self._corrupt_rate >= 1.0

    @corrupt_response.setter
    def corrupt_response(self, value: bool) -> None:
        with self._lock:
            self._corrupt_rate = 1.0 if value else 0.0

    @property
    def challenge_enabled(self) -> bool:
        with self._lock:
            return self.require_challenge

    @challenge_enabled.setter
    def challenge_enabled(self, value: bool) -> None:
        with self._lock:
            self.require_challenge = bool(value)

    def start(self) -> int:
        """Starts the mock UDP server on a background thread.

        Returns bound port.
        """
        with self._lock:
            if self._running:
                return self.port

            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._socket.bind((self.host, self.requested_port))
            self.port = self._socket.getsockname()[1]
            self._socket.settimeout(0.2)  # short timeout for clean shutdown loop check

            self._running = True
            self._thread = threading.Thread(target=self._listen_loop, daemon=True)
            self._thread.start()
            return self.port

    def stop(self) -> None:
        """Stops the mock UDP server and closes socket."""
        with self._lock:
            self._running = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

        with self._lock:
            if self._socket:
                try:
                    self._socket.close()
                except Exception:
                    pass
                self._socket = None

    def get_port(self) -> int:
        """Returns current bound server port."""
        with self._lock:
            return self.port

    def set_offline(self, offline: bool) -> None:
        """Toggles server online/offline state."""
        with self._lock:
            self.offline = offline

    def get_query_count(self) -> int:
        """Returns total number of A2S query requests received."""
        with self._lock:
            return self.query_count

    def reset_query_count(self) -> None:
        """Resets the query counter to zero."""
        with self._lock:
            self.query_count = 0

    def set_server_info(
        self,
        name: Optional[str] = None,
        map_name: Optional[str] = None,
        players: Optional[int] = None,
        max_players: Optional[int] = None,
        server_name: Optional[str] = None,
    ) -> None:
        """Dynamically updates server info fields for A2S_INFO payload."""
        with self._lock:
            target_name = name if name is not None else server_name
            if target_name is not None:
                self.server_name = target_name
            if map_name is not None:
                self.map_name = map_name
            if players is not None:
                self.players = players
            if max_players is not None:
                self.max_players = max_players

    def set_drop_rate(self, rate: float) -> None:
        """Sets packet drop rate (0.0 to 1.0)."""
        with self._lock:
            self._drop_rate = float(rate)

    def set_corrupt_rate(self, rate: float) -> None:
        """Sets payload corruption rate (0.0 to 1.0)."""
        with self._lock:
            self._corrupt_rate = float(rate)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    def build_info_packet(self) -> bytes:
        """Builds standard 0x49 A2S_INFO payload or corrupted payload."""
        with self._lock:
            is_corrupt = self._corrupt_rate >= 1.0 or (
                self._corrupt_rate > 0.0 and random.random() < self._corrupt_rate
            )
            if is_corrupt:
                return b"\xFF\xFF\xFF\xFF\x00CORRUPTED_PAYLOAD"

            header = b"\xFF\xFF\xFF\xFF\x49"  # 0xFFFFFFFF + 'I' (0x49)
            protocol = b"\x11"  # 17 protocol version
            name = self.server_name.encode("utf-8") + b"\x00"
            map_str = self.map_name.encode("utf-8") + b"\x00"
            folder = self.game_folder.encode("utf-8") + b"\x00"
            game = self.game_name.encode("utf-8") + b"\x00"
            app_id = struct.pack("<H", self.app_id)
            players = struct.pack("B", self.players)
            max_players = struct.pack("B", self.max_players)
            bots = struct.pack("B", self.bots)
            server_type = (
                self.server_type.encode("utf-8")
                if isinstance(self.server_type, str)
                else self.server_type
            )
            environment = (
                self.environment.encode("utf-8")
                if isinstance(self.environment, str)
                else self.environment
            )
            visibility = (
                struct.pack("B", self.visibility)
                if isinstance(self.visibility, int)
                else self.visibility
            )
            vac = (
                struct.pack("B", self.vac)
                if isinstance(self.vac, int)
                else self.vac
            )
            version_str = (
                self.version.encode("utf-8") + b"\x00"
                if isinstance(self.version, str)
                else self.version + b"\x00"
            )

            return (
                header
                + protocol
                + name
                + map_str
                + folder
                + game
                + app_id
                + players
                + max_players
                + bots
                + server_type
                + environment
                + visibility
                + vac
                + version_str
            )

    def build_challenge_packet(self) -> bytes:
        """Builds 0x41 Challenge Response packet."""
        with self._lock:
            token = self.challenge_token
        return b"\xFF\xFF\xFF\xFF\x41" + token

    def _listen_loop(self) -> None:
        while True:
            with self._lock:
                if not self._running:
                    break
                sock = self._socket

            if not sock:
                break

            try:
                data, addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except Exception:
                break

            with self._lock:
                self.query_count += 1
                self.request_count += 1
                self.last_client_addr = addr

                if self.offline:
                    continue

                is_drop = self._drop_rate >= 1.0 or (
                    self._drop_rate > 0.0 and random.random() < self._drop_rate
                )
                if is_drop:
                    continue

                delay = self.response_delay
                req_challenge = self.require_challenge
                chal_token = self.challenge_token

            if delay > 0:
                time.sleep(delay)

            # Check A2S_INFO header: \xFF\xFF\xFF\xFFT
            if not data.startswith(b"\xFF\xFF\xFF\xFFT"):
                continue

            expected_prefix = b"\xFF\xFF\xFF\xFFTSource Engine Query\x00"
            if not data.startswith(expected_prefix):
                continue

            payload_after_prefix = data[len(expected_prefix) :]

            if req_challenge:
                if (
                    len(payload_after_prefix) < 4
                    or payload_after_prefix[:4] != chal_token
                ):
                    resp = self.build_challenge_packet()
                    with self._lock:
                        self.challenge_sent_count += 1
                    try:
                        sock.sendto(resp, addr)
                    except Exception:
                        pass
                    continue

            resp = self.build_info_packet()
            with self._lock:
                self.info_sent_count += 1
            try:
                sock.sendto(resp, addr)
            except Exception:
                pass


if __name__ == "__main__":
    print("Starting Mock A2S Server on 127.0.0.1:28015 (press Ctrl+C to stop)...")
    server = MockA2SServer(host="127.0.0.1", port=28015)
    bound_port = server.start()
    print(f"Mock server listening on port {bound_port}")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        server.stop()
        print("Mock server stopped.")
