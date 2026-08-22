"""Integration tests for the web UI's smart-connect engine (src/web/connect_engine.py).

Uses a real UDP mock A2S server and a real background asyncio loop instead of
mocking the connect flow, matching this project's preference for integration
tests over narrow unit tests with mocks. Never touches Steam: os.startfile is
patched so a test can never actually launch the real game.
"""
import asyncio
import threading
import time
from unittest.mock import patch

import pytest

from src.core.config import config
from src.core.history_store import history_store
from src.web.bridge import WebBridge
from tests.mock_a2s_server import MockA2SServer


@pytest.fixture(autouse=True)
def isolate_history_file(monkeypatch, tmp_path):
    """connect_engine.connect() calls history_store.add_to_history(), which
    saves to config.data_file - point that at a throwaway file so tests never
    write mock-server IPs into the user's real saved-server history."""
    monkeypatch.setattr(type(config), "data_file", property(lambda self: tmp_path / "test_data.json"))


@pytest.fixture
def event_loop_thread():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True, name="test-connect-engine-loop")
    thread.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)


@pytest.fixture
def bridge(event_loop_thread):
    b = WebBridge()
    b.set_event_loop(event_loop_thread)
    yield b
    b.connect_engine.stop(explicit=True)
    b.connect_engine.wait_idle()


def _wait_until(predicate, timeout=5.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def test_dispatches_steam_launch_once_server_has_capacity(bridge):
    """The engine should discover a reachable, non-full server and launch it -
    exactly once, never twice for the same session."""
    server = MockA2SServer(players=1, max_players=10)
    port = server.start()
    try:
        with patch("src.web.connect_engine.os.startfile") as mock_startfile:
            bridge.connect_engine.connect(f"127.0.0.1:{port}")
            assert _wait_until(lambda: mock_startfile.called, timeout=6.0)
            assert _wait_until(
                lambda: bridge.connect_engine._active_session
                and bridge.connect_engine._active_session.launched_by_app,
                timeout=2.0,
            )
            time.sleep(0.3)
            assert mock_startfile.call_count == 1
            (url,), _ = mock_startfile.call_args
            assert url == f"steam://run/252490//+connect 127.0.0.1:{port}"
    finally:
        server.stop()
        bridge.connect_engine.stop(explicit=True)


def test_waits_and_never_launches_when_server_is_full(bridge):
    """A full server must never be launched into - the engine should keep
    polling instead."""
    server = MockA2SServer(players=10, max_players=10)
    port = server.start()
    try:
        with patch("src.web.connect_engine.os.startfile") as mock_startfile:
            bridge.connect_engine.connect(f"127.0.0.1:{port}")
            time.sleep(1.5)
            assert not mock_startfile.called
            assert bridge.connect_engine.is_polling
    finally:
        server.stop()
        bridge.connect_engine.stop(explicit=True)


def test_stop_cancels_active_session_and_leaves_swarm_room(bridge):
    server = MockA2SServer(players=10, max_players=10)
    port = server.start()
    try:
        bridge.connect_engine.connect(f"127.0.0.1:{port}")
        assert _wait_until(lambda: bridge.connect_engine._active_session is not None, timeout=2.0)
        bridge.connect_engine.stop(explicit=True)
        assert bridge.connect_engine._active_session is None
        assert not bridge.connect_engine.is_polling
    finally:
        server.stop()


def test_log_confirms_connection_only_for_matching_endpoint():
    from src.web.connect_engine import _log_confirms_connection
    from src.core.smart_monitor import ConnectionSession

    session = ConnectionSession(requested_endpoint="127.0.0.1:28015")
    session.canonical_endpoint = "127.0.0.1:28015"

    assert _log_confirms_connection("Client connected to 127.0.0.1:28015", "127.0.0.1:28015", session)
    assert not _log_confirms_connection("Client connected to 10.0.0.5:28015", "127.0.0.1:28015", session)
    assert not _log_confirms_connection("just some unrelated log line", "127.0.0.1:28015", session)


def test_log_reports_attempt_sets_flag_before_confirmation():
    from src.web.connect_engine import _log_reports_attempt
    from src.core.smart_monitor import ConnectionSession

    session = ConnectionSession(requested_endpoint="127.0.0.1:28015")
    session.canonical_endpoint = "127.0.0.1:28015"

    assert _log_reports_attempt("Connecting: 127.0.0.1:28015", "127.0.0.1:28015", session)
    assert not _log_reports_attempt("Connecting: 9.9.9.9:28015", "127.0.0.1:28015", session)


def test_full_flow_log_confirmation_then_autoarm_reconnect(bridge, tmp_path, monkeypatch):
    """End-to-end: server has capacity -> app launches (patched) -> fake
    Player.log reports the connection -> session is marked Connected ->
    disconnect on an armed server triggers an automatic reconnect attempt."""
    fake_log = tmp_path / "Player.log"
    fake_log.write_text("", encoding="utf-8")
    monkeypatch.setattr(type(config), "rust_log_path", property(lambda self: fake_log))

    original_armed = history_store.get_armed_server()
    original_auto_arm = history_store.get_auto_arm()
    server = MockA2SServer(players=1, max_players=10)
    port = server.start()
    target = f"127.0.0.1:{port}"
    try:
        history_store.set_auto_arm(True)
        history_store.set_armed_server(target, force=True)

        with patch("src.web.connect_engine.os.startfile"):
            bridge.connect_engine.connect(target)
            assert _wait_until(
                lambda: bridge.connect_engine._active_session
                and bridge.connect_engine._active_session.launched_by_app,
                timeout=6.0,
            )

            with fake_log.open("a", encoding="utf-8") as fh:
                fh.write(f"Client connected to {target}\n")
            assert _wait_until(lambda: bridge.connect_engine.is_connected, timeout=3.0)
            assert bridge._session_status == "Connected"

            connect_calls_before = bridge.connect_engine._operation_id
            with fake_log.open("a", encoding="utf-8") as fh:
                fh.write("Disconnected\n")

            # A new session id proves a fresh connect() was triggered automatically.
            assert _wait_until(
                lambda: bridge.connect_engine._operation_id > connect_calls_before, timeout=3.0
            )
    finally:
        server.stop()
        bridge.connect_engine.stop(explicit=True)
        history_store.set_armed_server(original_armed, force=True)
        history_store.set_auto_arm(original_auto_arm)


def test_swarm_status_changes_are_logged(bridge):
    bridge._log_history.clear()
    bridge.connect_engine._on_swarm_status("connected")
    bridge.connect_engine._on_swarm_status("disabled")
    messages = [entry["message"] for entry in bridge.get_logs()]
    # Localized text varies by active language, so just check each status
    # produced its own distinct, non-empty log entry mentioning Swarm.
    assert len(messages) == 2
    assert messages[0] != messages[1]
    assert all("Swarm" in m for m in messages)
