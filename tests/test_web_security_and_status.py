"""Integration tests for the web UI's CSRF token gate and the live per-server
A2S status cache (src/web/bridge.py). Uses a real UDP mock A2S server and a
real aiohttp TestClient instead of mocking the HTTP layer."""
import time

import pytest
from aiohttp.test_utils import TestClient, TestServer

from src.web.server import create_app
from tests.mock_a2s_server import MockA2SServer


def _wait_until(predicate, timeout=5.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


@pytest.mark.anyio
async def test_api_request_without_token_is_rejected():
    app = create_app()
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        resp = await client.get("/api/state")
        assert resp.status == 403
    finally:
        await client.close()


@pytest.mark.anyio
async def test_api_request_with_wrong_token_is_rejected():
    app = create_app()
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        resp = await client.get("/api/state", headers={"X-AutoConnect-Token": "not-the-real-token"})
        assert resp.status == 403
    finally:
        await client.close()


@pytest.mark.anyio
async def test_api_request_with_correct_token_succeeds():
    app = create_app()
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        resp = await client.get("/api/state", headers={"X-AutoConnect-Token": app["session_token"]})
        assert resp.status == 200
        data = await resp.json()
        assert "servers" in data
    finally:
        await client.close()


def test_status_is_checking_before_any_refresh():
    from src.web.bridge import WebBridge
    bridge = WebBridge()
    assert bridge._status_for("203.0.113.5:28015") == "checking"


def test_status_reflects_a_real_reachable_server():
    from src.web.bridge import WebBridge
    bridge = WebBridge()
    server = MockA2SServer(players=5, max_players=50)
    port = server.start()
    try:
        bridge._status_cache.clear()

        def check_one():
            host, port_str = f"127.0.0.1:{port}".rsplit(":", 1)
            status = bridge.a2s_client.check_server_status(host, int(port_str))
            with bridge._status_lock:
                bridge._status_cache[f"127.0.0.1:{port}"] = (time.monotonic(), status.alive)

        check_one()
        assert bridge._status_for(f"127.0.0.1:{port}") == "online"
    finally:
        server.stop()


def test_status_reflects_an_unreachable_server():
    from src.web.bridge import WebBridge
    bridge = WebBridge()
    # Port with nothing listening - A2S query must fail and report offline.
    unreachable = "127.0.0.1:1"
    host, port_str = unreachable.rsplit(":", 1)
    status = bridge.a2s_client.check_server_status(host, int(port_str))
    with bridge._status_lock:
        bridge._status_cache[unreachable] = (time.monotonic(), status.alive)
    assert bridge._status_for(unreachable) == "offline"


def test_rustmaps_fallback_degrades_gracefully_without_rules_support():
    """MockA2SServer only implements A2S_INFO, not A2S_RULES - the rustmaps
    lookup must fail closed (cache an empty string) rather than hang or crash."""
    from src.web.bridge import WebBridge
    bridge = WebBridge()
    server = MockA2SServer(players=1, max_players=10)
    port = server.start()
    ip = f"127.0.0.1:{port}"
    try:
        result = bridge._resolve_rustmaps_url(ip, "https://rustmaps.com")
        assert result == "https://rustmaps.com"  # immediate fallback, lookup runs in background
        assert _wait_until(lambda: ip in bridge._rustmaps_cache, timeout=5.0)
        assert bridge._rustmaps_cache[ip] == ""
    finally:
        server.stop()
