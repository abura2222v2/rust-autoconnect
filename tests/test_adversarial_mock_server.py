"""Adversarial stress and verification harness for MockA2SServer.

This module empirically stress-tests and verifies `tests/mock_a2s_server.py`.
"""

import socket
import struct
import threading
import time
import pytest
from tests.mock_a2s_server import MockA2SServer

QUERY_PACKET = b"\xFF\xFF\xFF\xFF\x54Source Engine Query\x00"


def send_udp(host: str, port: int, payload: bytes, timeout: float = 0.5) -> bytes | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(payload, (host, port))
        data, _ = sock.recvfrom(2048)
        return data
    except socket.timeout:
        return None
    except Exception:
        return None
    finally:
        sock.close()


def test_rapid_start_stop_cycles():
    """Verify rapid start and stop cycles do not crash or leak sockets."""
    for _ in range(20):
        server = MockA2SServer(host="127.0.0.1", port=0)
        port = server.start()
        assert port > 0
        server.stop()


def test_high_volume_queries():
    """Send 100 queries in rapid succession with the client's bounded retry."""
    server = MockA2SServer(host="127.0.0.1", port=0, challenge_enabled=False)
    port = server.start()
    try:
        successes = 0
        for _ in range(100):
            res = None
            for _ in range(3):
                res = send_udp("127.0.0.1", port, QUERY_PACKET, timeout=0.2)
                if res and res.startswith(b"\xFF\xFF\xFF\xFF\x49"):
                    break
            if res and res.startswith(b"\xFF\xFF\xFF\xFF\x49"):
                successes += 1
        assert successes == 100, f"Expected 100 responses, got {successes}"
    finally:
        server.stop()


def test_concurrent_threads_query():
    """Send queries concurrently from 10 threads."""
    server = MockA2SServer(host="127.0.0.1", port=0, challenge_enabled=False)
    port = server.start()
    try:
        errors = []

        def worker():
            for _ in range(10):
                res = None
                for _ in range(3):
                    res = send_udp("127.0.0.1", port, QUERY_PACKET, timeout=0.5)
                    if res and res.startswith(b"\xFF\xFF\xFF\xFF\x49"):
                        break
                if not res or not res.startswith(b"\xFF\xFF\xFF\xFF\x49"):
                    errors.append("Invalid or missing response")

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Encountered {len(errors)} errors during concurrent queries"
    finally:
        server.stop()


def test_oversized_udp_packet_does_not_kill_server_thread():
    """Malformed UDP traffic must not make the localhost E2E fixture unusable."""
    server = MockA2SServer(host="127.0.0.1", port=0)
    port = server.start()
    try:
        assert server._thread is not None and server._thread.is_alive()
        # Send 4096-byte packet, then prove a valid A2S request still works.
        send_udp("127.0.0.1", port, b"A" * 4096, timeout=0.1)
        time.sleep(0.2)
        assert server._thread.is_alive()
        response = send_udp("127.0.0.1", port, QUERY_PACKET, timeout=0.5)
        assert response and response.startswith(b"\xFF\xFF\xFF\xFF\x49")
    finally:
        server.stop()


def test_interface_contract_conformance():
    """Check required SCOPE.md and test suite interface methods and parameters."""
    server = MockA2SServer(host="127.0.0.1", port=0)

    missing_methods = []
    for method_name in ["get_port", "set_offline", "get_query_count", "reset_query_count", "set_server_info"]:
        if not hasattr(server, method_name) or not callable(getattr(server, method_name)):
            missing_methods.append(method_name)

    assert len(missing_methods) == 0, f"MockA2SServer missing required methods: {missing_methods}"
