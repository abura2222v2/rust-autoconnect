"""Unit test suite for A2S query engine (src/query.py) and Mock A2S Server (tests/mock_a2s_server.py).
"""

import socket
import time
from typing import Any, Dict, List, Tuple

import pytest

from src.query import (
    A2S_CHALLENGE_RESPONSE_HEADER,
    A2S_INFO_HEADER,
    A2S_INFO_RESPONSE_HEADER,
    A2SQueryEngine,
    build_a2s_info_request,
    parse_a2s_info_response,
    query_a2s_info,
)
from tests.mock_a2s_server import MockA2SServer


@pytest.fixture
def mock_server():
    """Pytest fixture providing a running MockA2SServer instance on dynamic localhost port."""
    server = MockA2SServer(host="127.0.0.1", port=0, challenge_enabled=True)
    port = server.start()
    yield server
    server.stop()


def test_build_a2s_info_request():
    """Tests construction of A2S_INFO request packets."""
    req_no_challenge = build_a2s_info_request()
    assert req_no_challenge == A2S_INFO_HEADER
    assert len(req_no_challenge) == 25

    challenge = b"\x12\x34\x56\x78"
    req_with_challenge = build_a2s_info_request(challenge)
    assert req_with_challenge == A2S_INFO_HEADER + challenge
    assert len(req_with_challenge) == 29

    with pytest.raises(ValueError, match="Challenge token must be exactly 4 bytes"):
        build_a2s_info_request(b"123")


def test_parse_a2s_info_response_invalid_headers():
    """Tests parser error handling on invalid or challenge headers."""
    with pytest.raises(ValueError, match="Payload too short"):
        parse_a2s_info_response(b"\x00\x01")

    with pytest.raises(ValueError, match="Expected info response header"):
        parse_a2s_info_response(b"\xFF\xFF\xFF\xFF\x41\x00\x00\x00\x00")

    with pytest.raises(ValueError, match="Invalid A2S_INFO response header"):
        parse_a2s_info_response(b"\x00\x00\x00\x00\x49test")


def test_mock_server_direct_handshake(mock_server):
    """Direct low-level socket test of MockA2SServer challenge handshake protocol."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(1.0)
    addr = ("127.0.0.1", mock_server.port)

    # 1. Send initial query without challenge
    req1 = b"\xFF\xFF\xFF\xFFTSource Engine Query\x00"
    sock.sendto(req1, addr)

    # Receive challenge packet 0x41
    data1, _ = sock.recvfrom(2048)
    assert data1.startswith(b"\xFF\xFF\xFF\xFF\x41")
    token = data1[5:9]
    assert token == mock_server.challenge_token

    # 2. Re-send query with challenge token attached
    req2 = req1 + token
    sock.sendto(req2, addr)

    # Receive info packet 0x49
    data2, _ = sock.recvfrom(2048)
    assert data2.startswith(b"\xFF\xFF\xFF\xFF\x49")

    sock.close()


def test_query_a2s_info_direct(mock_server):
    """Tests query_a2s_info synchronous function directly."""
    success, info, msg = query_a2s_info("127.0.0.1", mock_server.port, timeout=2.0)
    assert success is True
    assert msg == "Query successful"
    assert info is not None
    assert info["name"] == "Rust Test Server"
    assert info["game"] == "Rust"
    assert info["players"] == 10
    assert info["max_players"] == 100


def test_query_engine_success_with_challenge(mock_server):
    """Test A2SQueryEngine successful handshake and polling against MockA2SServer with challenge enabled."""
    updates: List[Tuple[str, str, int, Dict[str, Any]]] = []

    def on_status_update(status_type: str, message: str, count: int, info: Dict[str, Any]):
        updates.append((status_type, message, count, info))

    engine = A2SQueryEngine(
        ip="127.0.0.1",
        port=mock_server.port,
        poll_interval=0.1,  # fast polling for unit test execution
        required_successes=2,
        callback=on_status_update,
    )

    engine.start_polling()
    time.sleep(0.35)
    engine.stop_polling()

    assert not engine.is_polling()
    assert len(updates) >= 2
    # Verify last update reached required consecutive success count
    success_updates = [
        u for u in updates if u[0].upper() in ("SUCCESS", "READY")
    ]
    assert len(success_updates) >= 2
    assert success_updates[-1][2] >= 2
    info = success_updates[-1][3]
    assert info is not None
    assert info["name"] == "Rust Test Server"


def test_query_engine_success_no_challenge():
    """Test A2SQueryEngine against MockA2SServer when challenge protocol is disabled."""
    with MockA2SServer(host="127.0.0.1", port=0, challenge_enabled=False) as server:
        updates = []

        def callback(status_type, msg, count, info):
            updates.append((status_type, msg, count, info))

        engine = A2SQueryEngine(
            ip="127.0.0.1",
            port=server.port,
            poll_interval=0.1,
            required_successes=1,
            callback=callback,
        )

        engine.start_polling()
        time.sleep(0.2)
        engine.stop_polling()

        assert any(u[0].upper() == "READY" for u in updates)


def test_consecutive_success_reset_on_timeout():
    """Test that consecutive success counter resets to 0 when server drops packets (timeout)."""
    with MockA2SServer(host="127.0.0.1", port=0, challenge_enabled=False) as server:
        updates = []

        def callback(status_type, msg, count, info):
            updates.append((status_type, msg, count, info))

        engine = A2SQueryEngine(
            ip="127.0.0.1",
            port=server.port,
            poll_interval=0.1,
            required_successes=3,
            callback=callback,
            timeout=0.2,
        )

        # 1. Start polling, get successful responses
        engine.start_polling()
        time.sleep(0.15)

        # Enable drop packets to simulate timeout failure
        server.drop_packets = True
        time.sleep(0.35)
        engine.stop_polling()

        # Check updates list: after drop_packets=True, count should reset to 0
        error_updates = [u for u in updates if u[0].upper() == "ERROR"]
        assert len(error_updates) > 0
        assert error_updates[-1][2] == 0
        assert engine.get_success_count() == 0


def test_rate_limiting_interval():
    """Test that query engine respects minimum poll interval between queries."""
    with MockA2SServer(host="127.0.0.1", port=0, challenge_enabled=False) as server:
        timestamps = []

        def callback(status_type, msg, count, info):
            if status_type.upper() in ("SUCCESS", "READY"):
                timestamps.append(time.monotonic())

        poll_interval = 0.15
        engine = A2SQueryEngine(
            ip="127.0.0.1",
            port=server.port,
            poll_interval=poll_interval,
            required_successes=5,
            callback=callback,
        )

        engine.start_polling()
        time.sleep(0.5)
        engine.stop_polling()

        assert len(timestamps) >= 2
        for i in range(1, len(timestamps)):
            diff = timestamps[i] - timestamps[i - 1]
            assert diff >= (poll_interval * 0.8)  # Allow slight timing tolerance


def test_corrupted_response_handling():
    """Test that malformed/corrupted server payload resets success counter."""
    with MockA2SServer(host="127.0.0.1", port=0, corrupt_response=True) as server:
        updates = []

        def callback(status_type, msg, count, info):
            updates.append((status_type, msg, count, info))

        engine = A2SQueryEngine(
            ip="127.0.0.1",
            port=server.port,
            poll_interval=0.1,
            required_successes=2,
            callback=callback,
        )

        engine.start_polling()
        time.sleep(0.25)
        engine.stop_polling()

        error_updates = [u for u in updates if u[0].upper() == "ERROR"]
        assert len(error_updates) > 0
        assert error_updates[-1][2] == 0


def test_unreachable_server():
    """Test polling an unopened UDP port handles timeouts cleanly."""
    updates = []

    def callback(status_type, msg, count, info):
        updates.append((status_type, msg, count, info))

    # Port 59999 (unlikely to have listener)
    engine = A2SQueryEngine(
        ip="127.0.0.1",
        port=59999,
        poll_interval=0.1,
        required_successes=2,
        callback=callback,
        timeout=0.2,
    )

    engine.start_polling()
    time.sleep(0.25)
    engine.stop_polling()

    assert any(u[0].upper() == "ERROR" for u in updates)


def test_start_stop_polling_lifecycle():
    """Test starting, stopping, checking state, and restarting A2SQueryEngine."""
    with MockA2SServer(host="127.0.0.1", port=0, challenge_enabled=False) as server:
        engine = A2SQueryEngine(
            ip="127.0.0.1",
            port=server.port,
            poll_interval=0.1,
            required_successes=2,
        )

        assert not engine.is_polling()
        engine.start_polling()
        assert engine.is_polling()
        engine.stop_polling()
        assert not engine.is_polling()

        # Restart
        engine.start_polling()
        assert engine.is_polling()
        engine.stop_polling()
        assert not engine.is_polling()


def test_callback_exception_resilience():
    """Test that an exception thrown inside a user callback does not crash the polling loop."""
    with MockA2SServer(host="127.0.0.1", port=0, challenge_enabled=False) as server:
        call_count = 0

        def buggy_callback(status_type, msg, count, info):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("Boom in callback!")

        engine = A2SQueryEngine(
            ip="127.0.0.1",
            port=server.port,
            poll_interval=0.1,
            required_successes=3,
            callback=buggy_callback,
        )

        engine.start_polling()
        time.sleep(0.35)
        engine.stop_polling()

        assert call_count >= 2
