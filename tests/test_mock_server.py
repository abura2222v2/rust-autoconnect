"""
Unit test suite for MockA2SServer UDP implementation.
"""

import socket
import struct
import pytest
from tests.mock_a2s_server import MockA2SServer

QUERY_PACKET = b"\xFF\xFF\xFF\xFF\x54Source Engine Query\x00"


def _send_udp(port: int, payload: bytes, timeout: float = 1.0) -> bytes | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(payload, ("127.0.0.1", port))
        data, _ = sock.recvfrom(2048)
        return data
    except socket.timeout:
        return None
    finally:
        sock.close()


def test_mock_server_start_stop():
    server = MockA2SServer(host="127.0.0.1", port=0)
    port = server.start()
    assert port > 0
    assert server.get_port() == port
    server.stop()


def test_mock_server_context_manager():
    with MockA2SServer() as server:
        port = server.get_port()
        assert port > 0
        res = _send_udp(port, QUERY_PACKET)
        assert res is not None
        assert res.startswith(b"\xFF\xFF\xFF\xFF\x49")


def test_mock_server_a2s_info_payload_parsing():
    with MockA2SServer(
        server_name="My Custom Rust Server",
        map_name="procedural_v2",
        players=42,
        max_players=200,
        game_port=28015,
        vac=1,
    ) as server:
        port = server.get_port()
        res = _send_udp(port, QUERY_PACKET)
        assert res is not None
        assert len(res) > 6
        assert res[:5] == b"\xFF\xFF\xFF\xFF\x49"
        assert res[5] == 0x11  # protocol

        # Parse null-terminated strings
        parts = res[6:].split(b"\x00")
        assert len(parts) >= 5
        server_name = parts[0].decode("utf-8")
        map_name = parts[1].decode("utf-8")
        folder = parts[2].decode("utf-8")
        game = parts[3].decode("utf-8")

        assert server_name == "My Custom Rust Server"
        assert map_name == "procedural_v2"
        assert folder == "rust"
        assert game == "Rust"

        # Check numeric binary fields after game string
        idx = 6 + len(parts[0]) + 1 + len(parts[1]) + 1 + len(parts[2]) + 1 + len(parts[3]) + 1
        app_id = struct.unpack("<H", res[idx:idx + 2])[0]
        players = res[idx + 2]
        max_players = res[idx + 3]
        bots = res[idx + 4]
        server_type = chr(res[idx + 5])
        environment = chr(res[idx + 6])
        visibility = res[idx + 7]
        vac = res[idx + 8]

        assert app_id == 25249
        assert players == 42
        assert max_players == 200
        assert bots == 0
        assert server_type == "d"
        assert environment == "w"
        assert visibility == 0
        assert vac == 1


def test_mock_server_challenge_handshake():
    with MockA2SServer(require_challenge=True) as server:
        port = server.get_port()
        # Initial request without challenge token
        res1 = _send_udp(port, QUERY_PACKET)
        assert res1 is not None
        assert res1[:5] == b"\xFF\xFF\xFF\xFF\x41"
        assert len(res1) == 9
        challenge_token = res1[5:]

        # Second request appending challenge token
        challenged_packet = QUERY_PACKET + challenge_token
        res2 = _send_udp(port, challenged_packet)
        assert res2 is not None
        assert res2[:5] == b"\xFF\xFF\xFF\xFF\x49"


def test_mock_server_drop_rate():
    with MockA2SServer(drop_rate=1.0) as server:
        port = server.get_port()
        res = _send_udp(port, QUERY_PACKET, timeout=0.3)
        assert res is None


def test_mock_server_corrupt_rate():
    with MockA2SServer(corrupt_rate=1.0) as server:
        port = server.get_port()
        res = _send_udp(port, QUERY_PACKET, timeout=0.5)
        assert res is not None
        assert not res.startswith(b"\xFF\xFF\xFF\xFF\x49")
        assert b"CORRUPTED" in res


def test_mock_server_offline_toggle():
    with MockA2SServer() as server:
        port = server.get_port()
        # Online query
        res1 = _send_udp(port, QUERY_PACKET)
        assert res1 is not None

        # Toggle offline
        server.set_offline(True)
        res2 = _send_udp(port, QUERY_PACKET, timeout=0.3)
        assert res2 is None

        # Toggle online back
        server.set_offline(False)
        res3 = _send_udp(port, QUERY_PACKET)
        assert res3 is not None


def test_mock_server_query_counter():
    with MockA2SServer() as server:
        port = server.get_port()
        assert server.get_query_count() == 0

        for _ in range(5):
            _send_udp(port, QUERY_PACKET)

        assert server.get_query_count() == 5
        server.reset_query_count()
        assert server.get_query_count() == 0


def test_mock_server_set_server_info():
    with MockA2SServer() as server:
        port = server.get_port()
        server.set_server_info(name="Updated Server", map_name="barren", players=88, max_players=150)
        res = _send_udp(port, QUERY_PACKET)
        assert res is not None
        parts = res[6:].split(b"\x00")
        assert parts[0].decode("utf-8") == "Updated Server"
        assert parts[1].decode("utf-8") == "barren"
