"""Adversarial and stress test cases for A2S query engine (src/query.py) and Mock A2S Server (tests/mock_a2s_server.py).

Covers edge cases: malformed packets, truncated payloads, missing null terminators, non-ASCII strings,
corrupted EDF flags, short/repeated challenge tokens, rapid start/stop polling loops, concurrent calls,
unreachable UDP ports, and consecutive success counter resetting.
"""

import socket
import threading
import time
import pytest

from src.query import (
    A2SQueryEngine,
    build_a2s_info_request,
    parse_a2s_info_response,
    query_a2s_info,
)
from tests.mock_a2s_server import MockA2SServer


def test_empty_bytes_payload():
    with pytest.raises(ValueError, match="Payload too short"):
        parse_a2s_info_response(b"")


def test_garbage_header_payload():
    with pytest.raises(ValueError, match="Invalid A2S_INFO response header"):
        parse_a2s_info_response(b"\x00\x00\x00\x00\x49Rust Server\x00")


def test_missing_null_terminator_string():
    data = b"\xFF\xFF\xFF\xFF\x49\x11RustServerNoNull"
    with pytest.raises(ValueError, match="Unterminated string"):
        parse_a2s_info_response(data)


def test_truncated_payload_before_app_id():
    header = b"\xFF\xFF\xFF\xFF\x49\x11"
    strings = b"Name\x00Map\x00Folder\x00Game\x00"
    data = header + strings + b"\x01"  # Only 1 byte for app_id (2 expected)
    with pytest.raises(ValueError, match="Truncated payload"):
        parse_a2s_info_response(data)


def test_non_ascii_utf8_fallback():
    header = b"\xFF\xFF\xFF\xFF\x49\x11"
    bad_utf8_name = b"Rust \x80\xFF Server\x00"
    data = (
        header
        + bad_utf8_name
        + b"Map\x00Folder\x00Game\x00\x01\x00\x05\x0A\x00dw\x00\x011.0.0\x00"
    )
    info = parse_a2s_info_response(data)
    assert "Rust" in info["name"]


def test_edf_truncated_garbage():
    base = (
        b"\xFF\xFF\xFF\xFF\x49\x11"
        b"Name\x00Map\x00Folder\x00Game\x00"
        b"\x01\x00"  # app_id
        b"\x05\x0A\x00"  # players, max, bots
        b"dw\x00\x01"  # type, env, vis, vac
        b"1.0.0\x00"  # version
        b"\xFF"  # EDF byte with all flags set but no data following
    )
    info = parse_a2s_info_response(base)
    assert info["name"] == "Name"
    assert info["edf"] == 255


def test_challenge_response_too_short():
    class ShortChallengeServer:
        def __init__(self):
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind(("127.0.0.1", 0))
            self.port = self.sock.getsockname()[1]
            self.running = True
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

        def _run(self):
            self.sock.settimeout(0.2)
            while self.running:
                try:
                    data, addr = self.sock.recvfrom(1024)
                    self.sock.sendto(b"\xFF\xFF\xFF\xFF\x41\x12\x34", addr)
                except socket.timeout:
                    continue
                except Exception:
                    break

        def stop(self):
            self.running = False
            self.sock.close()

    srv = ShortChallengeServer()
    try:
        success, info, msg = query_a2s_info("127.0.0.1", srv.port, timeout=0.5)
        assert success is False
        assert "Malformed packet" in msg or "Expected info response" in msg
    finally:
        srv.stop()


def test_infinite_challenge_loop():
    class InfiniteChallengeServer:
        def __init__(self):
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind(("127.0.0.1", 0))
            self.port = self.sock.getsockname()[1]
            self.running = True
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

        def _run(self):
            self.sock.settimeout(0.2)
            while self.running:
                try:
                    data, addr = self.sock.recvfrom(1024)
                    self.sock.sendto(b"\xFF\xFF\xFF\xFF\x41\x99\x88\x77\x66", addr)
                except socket.timeout:
                    continue
                except Exception:
                    break

        def stop(self):
            self.running = False
            self.sock.close()

    srv = InfiniteChallengeServer()
    try:
        success, info, msg = query_a2s_info("127.0.0.1", srv.port, timeout=0.5)
        assert success is False
        assert "got challenge response (0x41)" in msg
    finally:
        srv.stop()


def test_rapid_start_stop_polling():
    with MockA2SServer(host="127.0.0.1", port=0, challenge_enabled=False) as server:
        engine = A2SQueryEngine(
            ip="127.0.0.1",
            port=server.port,
            poll_interval=0.05,
            required_successes=3,
        )

        for _ in range(30):
            engine.start_polling()
            time.sleep(0.01)
            engine.stop_polling()

        assert not engine.is_polling()


def test_concurrent_start_polling_calls():
    with MockA2SServer(host="127.0.0.1", port=0, challenge_enabled=False) as server:
        engine = A2SQueryEngine(
            ip="127.0.0.1",
            port=server.port,
            poll_interval=0.05,
            required_successes=3,
        )

        threads = []
        for _ in range(10):
            t = threading.Thread(target=engine.start_polling)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert engine.is_polling()
        engine.stop_polling()
        assert not engine.is_polling()


def test_consecutive_success_counter_resets_on_drop():
    with MockA2SServer(host="127.0.0.1", port=0, challenge_enabled=False) as server:
        counts = []

        def callback(status_type, msg, count, info):
            counts.append((status_type, count))

        engine = A2SQueryEngine(
            ip="127.0.0.1",
            port=server.port,
            poll_interval=0.05,
            required_successes=5,
            callback=callback,
            timeout=0.1,
        )

        engine.start_polling()
        time.sleep(0.12)
        server.drop_packets = True
        time.sleep(0.15)
        server.drop_packets = False
        time.sleep(0.15)
        engine.stop_polling()

        error_indices = [i for i, c in enumerate(counts) if c[0] == "ERROR"]
        assert len(error_indices) > 0
        post_error_successes = [
            c[1] for c in counts[error_indices[0] + 1 :] if c[0] == "SUCCESS"
        ]
        assert len(post_error_successes) > 0
        assert post_error_successes[0] == 1
