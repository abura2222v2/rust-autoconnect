"""Source Engine A2S_INFO UDP protocol client and query engine.

Implements standard Source Engine query packet construction, response parsing,
challenge token handshakes, rate limiting, and consecutive success tracking.
"""

import socket
import struct
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

# Protocol Header Constants
A2S_INFO_HEADER = b"\xFF\xFF\xFF\xFF\x54Source Engine Query\x00"
A2S_CHALLENGE_RESPONSE_HEADER = b"\xFF\xFF\xFF\xFF\x41"
A2S_INFO_RESPONSE_HEADER = b"\xFF\xFF\xFF\xFF\x49"


def build_a2s_info_request(challenge: Optional[bytes] = None) -> bytes:
    """Builds standard A2S_INFO UDP request packet with optional 4-byte challenge token."""
    packet = A2S_INFO_HEADER
    if challenge is not None:
        if len(challenge) != 4:
            raise ValueError("Challenge token must be exactly 4 bytes")
        packet += challenge
    return packet


def parse_a2s_info_response(data: bytes) -> Dict[str, Any]:
    """Parses raw UDP byte payload into server metadata dictionary."""
    if len(data) < 5:
        raise ValueError(f"Payload too short ({len(data)} bytes)")

    if not data.startswith(A2S_INFO_RESPONSE_HEADER):
        if data.startswith(A2S_CHALLENGE_RESPONSE_HEADER):
            raise ValueError("Expected info response header (0x49), got challenge response (0x41)")
        raise ValueError("Invalid A2S_INFO response header")

    offset = 5
    if offset >= len(data):
        raise ValueError("Truncated payload reading protocol")

    protocol = data[offset]
    offset += 1

    def read_cstring(buf: bytes, start: int) -> Tuple[str, int]:
        end = buf.find(b"\x00", start)
        if end == -1:
            raise ValueError(f"Unterminated string starting at offset {start}")
        raw = buf[start:end]
        try:
            val = raw.decode("utf-8")
        except UnicodeDecodeError:
            val = raw.decode("latin-1", errors="replace")
        return val, end + 1

    name, offset = read_cstring(data, offset)
    map_name, offset = read_cstring(data, offset)
    folder, offset = read_cstring(data, offset)
    game, offset = read_cstring(data, offset)

    if offset + 2 > len(data):
        raise ValueError("Truncated payload reading server AppID")
    server_id = struct.unpack("<H", data[offset : offset + 2])[0]
    offset += 2

    if offset + 3 > len(data):
        raise ValueError("Truncated payload reading player count")
    players = data[offset]
    max_players = data[offset + 1]
    bots = data[offset + 2]
    offset += 3

    if offset + 4 > len(data):
        raise ValueError("Truncated payload reading server flags")
    server_type = chr(data[offset])
    environment = chr(data[offset + 1])
    visibility = data[offset + 2]
    vac = data[offset + 3]
    offset += 4

    version = ""
    if offset < len(data):
        version, offset = read_cstring(data, offset)

    info: Dict[str, Any] = {
        "protocol": protocol,
        "name": name,
        "map": map_name,
        "map_name": map_name,
        "folder": folder,
        "game": game,
        "id": server_id,
        "app_id": server_id,
        "players": players,
        "max_players": max_players,
        "bots": bots,
        "server_type": server_type,
        "environment": environment,
        "visibility": visibility,
        "vac": vac,
        "version": version,
    }

    # Safely parse optional Extra Data Flags (EDF) if present
    if offset < len(data):
        edf_byte = data[offset]
        offset += 1
        info["edf"] = edf_byte

        try:
            if edf_byte & 0x80 and offset + 2 <= len(data):  # Port
                info["port"] = struct.unpack("<H", data[offset : offset + 2])[0]
                offset += 2
            if edf_byte & 0x10 and offset + 8 <= len(data):  # SteamID
                info["steam_id"] = struct.unpack("<Q", data[offset : offset + 8])[0]
                offset += 8
            if edf_byte & 0x40 and offset + 2 <= len(data):  # SourceTV
                info["sourcetv_port"] = struct.unpack("<H", data[offset : offset + 2])[0]
                offset += 2
                info["sourcetv_name"], offset = read_cstring(data, offset)
            if edf_byte & 0x20 and offset < len(data):  # Keywords
                info["keywords"], offset = read_cstring(data, offset)
            if edf_byte & 0x01 and offset + 8 <= len(data):  # GameID
                info["game_id"] = struct.unpack("<Q", data[offset : offset + 8])[0]
                offset += 8
        except Exception:
            pass

    return info


def query_a2s_info(
    ip: str, port: int, timeout: float = 2.0
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """Performs single synchronous UDP A2S_INFO query with challenge handshake."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)

    # Windows UDP connection reset fix (SIO_UDP_CONNRESET)
    if hasattr(socket, "SIO_UDP_CONNRESET"):
        try:
            sock.ioctl(socket.SIO_UDP_CONNRESET, False)
        except (AttributeError, OSError, ValueError):
            pass
    else:
        try:
            SIO_UDP_CONNRESET = -1744830452  # 0x9800000C as signed int
            sock.ioctl(SIO_UDP_CONNRESET, False)
        except (AttributeError, OSError, ValueError):
            pass

    try:
        req = build_a2s_info_request()
        sock.sendto(req, (ip, port))
        data, _ = sock.recvfrom(4096)

        if data.startswith(A2S_CHALLENGE_RESPONSE_HEADER) and len(data) >= 9:
            challenge = data[5:9]
            req_challenge = build_a2s_info_request(challenge)
            sock.sendto(req_challenge, (ip, port))
            data, _ = sock.recvfrom(4096)

        info = parse_a2s_info_response(data)
        return True, info, "Query successful"
    except socket.timeout:
        return False, None, "Connection timeout"
    except (socket.error, OSError) as e:
        return False, None, f"Socket error: {e}"
    except ValueError as e:
        return False, None, f"Malformed packet: {e}"
    finally:
        sock.close()


class A2SQueryEngine:
    """Thread-safe background query engine for A2S_INFO server polling."""

    def __init__(
        self,
        ip: str,
        port: int,
        poll_interval: float = 3.0,
        required_successes: int = 3,
        callback: Optional[Callable[[str, str, int, Optional[Dict[str, Any]]], None]] = None,
        timeout: float = 2.0,
    ):
        self.ip = ip
        self.port = int(port)
        self.poll_interval = max(0.05, float(poll_interval))
        self.required_successes = max(1, int(required_successes))
        self.callback = callback
        self.timeout = max(0.05, float(timeout))

        self._lock = threading.Lock()
        self._is_polling = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._success_count = 0

    def start_polling(self) -> None:
        """Starts background server polling thread."""
        with self._lock:
            if self._is_polling:
                return
            self._is_polling = True
            self._stop_event.clear()
            self._success_count = 0
            self._thread = threading.Thread(target=self._polling_loop, daemon=True)
            self._thread.start()

        self._notify_callback("START", f"Started polling {self.ip}:{self.port}", 0, None)

    def stop_polling(self) -> None:
        """Stops background server polling thread."""
        with self._lock:
            if not self._is_polling:
                return
            self._is_polling = False
            self._stop_event.set()

        if self._thread and self._thread.is_alive():
            if threading.current_thread() != self._thread:
                self._thread.join(timeout=1.0)

        self._notify_callback(
            "STOP", f"Stopped polling {self.ip}:{self.port}", self.get_success_count(), None
        )

    def is_polling(self) -> bool:
        """Returns True if background polling is active."""
        with self._lock:
            return self._is_polling

    def get_success_count(self) -> int:
        """Returns current consecutive success count."""
        with self._lock:
            return self._success_count

    def _polling_loop(self) -> None:
        """Internal background thread loop."""
        while not self._stop_event.is_set():
            start_time = time.monotonic()

            success, server_info, msg = query_a2s_info(
                self.ip, self.port, timeout=self.timeout
            )

            with self._lock:
                if success:
                    self._success_count += 1
                    count = self._success_count
                    if count >= self.required_successes:
                        status = "READY"
                        log_msg = (
                            f"Server online! ({count}/{self.required_successes} consecutive successes)"
                        )
                    else:
                        status = "SUCCESS"
                        log_msg = f"Server responding ({count}/{self.required_successes})"
                else:
                    self._success_count = 0
                    count = 0
                    status = "ERROR"
                    log_msg = f"Query failed: {msg}"

            self._notify_callback(status, log_msg, count, server_info if success else None)

            if self._stop_event.is_set():
                break

            elapsed = time.monotonic() - start_time
            sleep_needed = max(0.0, self.poll_interval - elapsed)
            if sleep_needed > 0:
                self._stop_event.wait(timeout=sleep_needed)

    def _notify_callback(
        self,
        status_type: str,
        message: str,
        success_count: int,
        server_info: Optional[Dict[str, Any]],
    ) -> None:
        """Safely invokes callback without letting exceptions bubble up."""
        if self.callback:
            try:
                self.callback(status_type, message, success_count, server_info)
            except Exception:
                pass
