"""Integration tests for the web UI's smart-connect engine (src/web/connect_engine.py).

Uses a real UDP mock A2S server and a real background asyncio loop instead of
mocking the connect flow, matching this project's preference for integration
tests over narrow unit tests with mocks. Never touches Steam: os.startfile is
patched so a test can never actually launch the real game.
"""
import asyncio
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.core.config import config
from src.core.history_store import history_store
from src.web.bridge import WebBridge
from src.web.connect_engine import _MAX_RECONNECT_ATTEMPTS
from tests.mock_a2s_server import MockA2SServer


@pytest.fixture(autouse=True)
def isolate_history_file(monkeypatch, tmp_path):
    """connect_engine.connect() calls history_store.add_to_history(), which
    saves to config.data_file - point that at a throwaway file so tests never
    write mock-server IPs into the user's real saved-server history."""
    monkeypatch.setattr(type(config), "data_file", property(lambda self: tmp_path / "test_data.json"))


@pytest.fixture(autouse=True)
def default_rust_not_running(monkeypatch):
    """_dispatch_launch checks the real process list via process_monitor.
    Default it to "not running" so these tests don't depend on whether the
    developer's own real Rust client happens to be open on the test machine;
    individual tests can still override this with their own monkeypatch."""
    monkeypatch.setattr("src.web.connect_engine.process_monitor.is_rust_running", lambda: False)


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
        with patch("src.services.steam_service.os.startfile") as mock_startfile:
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


def test_continues_observing_after_launch_without_relaunching_steam(bridge):
    """Once Steam is launched, keep lightly observing A2S (for user-visible
    feedback while Rust boots, which can take 20-90+ real seconds) without
    ever launching Steam a second time. Matches app.py's post-launch
    behavior, ported here after being deferred earlier in this same pass."""
    server = MockA2SServer(players=1, max_players=10)
    port = server.start()
    target = f"127.0.0.1:{port}"
    try:
        with patch("src.services.steam_service.os.startfile") as mock_startfile:
            bridge.connect_engine.connect(target)
            assert _wait_until(lambda: mock_startfile.called, timeout=6.0)

            # Give the observation loop time to run at least one full pass
            # after the launch (it waits ~5s between probes) and prove it
            # neither stops polling nor launches Steam again.
            assert _wait_until(
                lambda: history_store.get_server_profile(target).get("last_state") == "launching",
                timeout=8.0,
            )
            assert mock_startfile.call_count == 1
            assert bridge.connect_engine.is_polling
    finally:
        server.stop()
        bridge.connect_engine.stop(explicit=True)


def test_waits_and_never_launches_when_server_is_full(bridge):
    """A full server must never be launched into - the engine should keep
    polling instead."""
    server = MockA2SServer(players=10, max_players=10)
    port = server.start()
    try:
        with patch("src.services.steam_service.os.startfile") as mock_startfile:
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

        with patch("src.services.steam_service.os.startfile"):
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

            # stop() alone also bumps _operation_id, so that check alone
            # can't tell "stopped" apart from "stopped, then reconnected".
            # A fresh, non-None active session for the same target is the
            # actual proof a new connect() ran.
            # The retry is deliberately delayed (backoff), so allow for it.
            assert _wait_until(
                lambda: bridge.connect_engine._operation_id > connect_calls_before
                and bridge.connect_engine._active_session is not None
                and bridge.connect_engine._active_session.requested_endpoint == target,
                timeout=8.0,
            )
    finally:
        server.stop()
        bridge.connect_engine.stop(explicit=True)
        history_store.set_armed_server(original_armed, force=True)
        history_store.set_auto_arm(original_auto_arm)


def test_reconnects_after_first_attempt_rejection_when_armed(bridge, tmp_path, monkeypatch):
    """A rejected FIRST join attempt (kick, full, "Connection Attempt
    Failed") must still trigger a reconnect on an armed server - not only a
    disconnect after an already-confirmed connection. Matches app.py, which
    reconnects whenever the session it launched targets the armed server,
    regardless of whether a connection was ever confirmed."""
    fake_log = tmp_path / "Player.log"
    fake_log.write_text("", encoding="utf-8")
    monkeypatch.setattr(type(config), "rust_log_path", property(lambda self: fake_log))

    original_armed = history_store.get_armed_server()
    server = MockA2SServer(players=1, max_players=10)
    port = server.start()
    target = f"127.0.0.1:{port}"
    try:
        history_store.set_armed_server(target, force=True)

        with patch("src.services.steam_service.os.startfile"):
            bridge.connect_engine.connect(target)
            assert _wait_until(
                lambda: bridge.connect_engine._active_session
                and bridge.connect_engine._active_session.launched_by_app,
                timeout=6.0,
            )
            assert not bridge.connect_engine.is_connected

            connect_calls_before = bridge.connect_engine._operation_id
            with fake_log.open("a", encoding="utf-8") as fh:
                fh.write("Disconnected (Connection Attempt Failed) - returning to main menu\n")

            # stop() alone also bumps _operation_id - require a fresh active
            # session for the same target as proof a real reconnect ran.
            # The retry is deliberately delayed (backoff), so allow for it.
            assert _wait_until(
                lambda: bridge.connect_engine._operation_id > connect_calls_before
                and bridge.connect_engine._active_session is not None
                and bridge.connect_engine._active_session.requested_endpoint == target,
                timeout=8.0,
            )
    finally:
        server.stop()
        bridge.connect_engine.stop(explicit=True)
        history_store.set_armed_server(original_armed, force=True)


def test_handle_unexpected_rust_exit_reconnects_when_armed(bridge, monkeypatch):
    """If Rust's process disappears without ever writing a disconnect line
    (a hard crash), the engine must notice via handle_unexpected_rust_exit
    and reconnect - the log watcher alone can never catch this case."""
    original_armed = history_store.get_armed_server()
    server = MockA2SServer(players=1, max_players=10)
    port = server.start()
    target = f"127.0.0.1:{port}"
    try:
        history_store.set_armed_server(target, force=True)

        with patch("src.services.steam_service.os.startfile"):
            bridge.connect_engine.connect(target)
            assert _wait_until(
                lambda: bridge.connect_engine._active_session
                and bridge.connect_engine._active_session.launched_by_app,
                timeout=6.0,
            )

            connect_calls_before = bridge.connect_engine._operation_id
            bridge.connect_engine.handle_unexpected_rust_exit()

            # stop() alone also bumps _operation_id - require a fresh active
            # session for the same target as proof a real reconnect ran.
            # The retry is deliberately delayed (backoff), so allow for it.
            assert _wait_until(
                lambda: bridge.connect_engine._operation_id > connect_calls_before
                and bridge.connect_engine._active_session is not None
                and bridge.connect_engine._active_session.requested_endpoint == target,
                timeout=8.0,
            )
    finally:
        server.stop()
        bridge.connect_engine.stop(explicit=True)
        history_store.set_armed_server(original_armed, force=True)


def test_handle_unexpected_rust_exit_does_nothing_when_not_armed(bridge, monkeypatch):
    """Must not react to a Rust exit for a session that isn't the armed
    target - only the currently armed server's crash should auto-reconnect."""
    original_armed = history_store.get_armed_server()
    server = MockA2SServer(players=1, max_players=10)
    port = server.start()
    target = f"127.0.0.1:{port}"
    try:
        history_store.set_armed_server("", force=True)

        with patch("src.services.steam_service.os.startfile"):
            bridge.connect_engine.connect(target)
            assert _wait_until(
                lambda: bridge.connect_engine._active_session
                and bridge.connect_engine._active_session.launched_by_app,
                timeout=6.0,
            )

            connect_calls_before = bridge.connect_engine._operation_id
            bridge.connect_engine.handle_unexpected_rust_exit()
            time.sleep(0.5)
            assert bridge.connect_engine._operation_id == connect_calls_before
    finally:
        server.stop()
        bridge.connect_engine.stop(explicit=True)
        history_store.set_armed_server(original_armed, force=True)


def test_does_not_launch_into_stale_pre_wipe_server(bridge, monkeypatch):
    """Regression test for the reported bug: the engine must not launch into
    a still-alive pre-wipe server just because it has capacity. It must wait
    until a restart is actually observed (the old server going unreachable
    once the scheduled wipe time has passed), matching the legacy app.py
    behavior this was ported from."""
    near_future = datetime.now(timezone.utc) + timedelta(seconds=3)
    monkeypatch.setattr(
        "src.web.connect_engine.steam_service.relevant_force_wipe_at",
        lambda now=None: near_future,
    )
    server = MockA2SServer(players=1, max_players=10)
    port = server.start()
    target = f"127.0.0.1:{port}"
    try:
        with patch("src.services.steam_service.os.startfile") as mock_startfile:
            bridge.connect_engine.connect(target)
            assert _wait_until(lambda: bridge.connect_engine._active_session is not None, timeout=2.0)
            session = bridge.connect_engine._active_session

            assert _wait_until(lambda: session.waiting_for_wipe_restart, timeout=3.0)
            # Give it a couple of poll ticks against the still-alive, still
            # has-capacity server. Before the fix this launched immediately.
            time.sleep(2.0)
            assert not mock_startfile.called

            # Simulate the real wipe: the old server stops answering once the
            # scheduled wipe time has passed.
            assert _wait_until(lambda: datetime.now(timezone.utc) >= near_future, timeout=3.0)
            server.set_offline(True)
            assert _wait_until(lambda: not session.waiting_for_wipe_restart, timeout=6.0)
            assert not mock_startfile.called

            # The "new" post-wipe server comes back up with a free slot.
            server.set_offline(False)
            assert _wait_until(lambda: mock_startfile.called, timeout=8.0)
    finally:
        server.stop()
        bridge.connect_engine.stop(explicit=True)


def test_zero_max_players_is_not_treated_as_capacity(bridge):
    """A server reporting max_players=0 (e.g. still starting up right after a
    wipe restart) must not be mistaken for a free slot."""
    server = MockA2SServer(players=0, max_players=0)
    port = server.start()
    try:
        with patch("src.services.steam_service.os.startfile") as mock_startfile:
            bridge.connect_engine.connect(f"127.0.0.1:{port}")
            time.sleep(1.5)
            assert not mock_startfile.called
            assert bridge.connect_engine.is_polling
    finally:
        server.stop()
        bridge.connect_engine.stop(explicit=True)


def test_manual_connect_queues_on_a_full_server(bridge):
    """bridge.connect_to_server() must enable queue_on_full so a manual
    Connect click can enter Rust's own server queue on a full server,
    instead of polling forever without ever launching."""
    server = MockA2SServer(players=10, max_players=10)
    port = server.start()
    target = f"127.0.0.1:{port}"
    try:
        with patch("src.services.steam_service.os.startfile") as mock_startfile:
            bridge.connect_to_server(target)
            assert _wait_until(lambda: mock_startfile.called, timeout=6.0)
            (url,), _ = mock_startfile.call_args
            assert url == f"steam://run/252490//+connect {target}"
            assert bridge._session_status == "Queueing"
    finally:
        server.stop()
        bridge.connect_engine.stop(explicit=True)


def test_connect_command_is_sent_even_when_rust_is_already_running(bridge, monkeypatch):
    """Measured against a real Rust client (2026-09-04): the same
    steam://run//+connect URL also redirects an ALREADY-RUNNING client that
    sits in the main menu - the log answers "Connecting: ip:port" about a
    second later. An earlier measurement said otherwise and made the engine
    refuse to send anything while Rust was open, which silently disabled
    auto-reconnect in its most common case (kick -> menu -> rejoin). The
    engine must dispatch in both states."""
    monkeypatch.setattr(
        "src.web.connect_engine.process_monitor.is_rust_running", lambda: True
    )
    server = MockA2SServer(players=1, max_players=10)
    port = server.start()
    try:
        with patch("src.services.steam_service.os.startfile") as mock_startfile:
            bridge._log_history.clear()
            bridge.connect_engine.connect(f"127.0.0.1:{port}")
            assert _wait_until(lambda: mock_startfile.called, timeout=6.0)
            url = mock_startfile.call_args[0][0]
            assert url == f"steam://run/{config.STEAM_APP_ID}//+connect 127.0.0.1:{port}"
            # The user still needs to know which of the two happened.
            messages = [entry["message"] for entry in bridge.get_logs()]
            assert any("already open" in m.lower() or "уже открыт" in m.lower() for m in messages)
    finally:
        server.stop()
        bridge.connect_engine.stop(explicit=True)


def test_observation_stops_instead_of_watching_forever(bridge, monkeypatch):
    """Once launched, the engine observes A2S until the log confirms the
    join. If confirmation never comes (log format change, silently failed
    join) it used to keep probing and keep showing "Launching" forever."""
    monkeypatch.setattr("src.web.connect_engine._OBSERVATION_LIMIT_SECONDS", 1.0)
    server = MockA2SServer(players=1, max_players=10)
    port = server.start()
    try:
        with patch("src.services.steam_service.os.startfile"):
            bridge.connect_engine.connect(f"127.0.0.1:{port}")
            assert _wait_until(
                lambda: bridge.connect_engine._active_session
                and bridge.connect_engine._active_session.launched_by_app,
                timeout=8.0,
            )
            # No log confirmation will ever arrive in this test.
            assert _wait_until(lambda: not bridge.connect_engine.is_polling, timeout=15.0)
            assert bridge._session_status == "idle"
            messages = [entry["message"] for entry in bridge.get_logs()]
            assert any("gave up watching" in m.lower() or "прекращено" in m.lower() for m in messages)
    finally:
        server.stop()
        bridge.connect_engine.stop(explicit=True)


def test_restarting_the_global_watcher_does_not_leave_two_alive(bridge):
    """Restarts are scheduled from two independent places (a disconnect and
    the end of a benchmark). Each one used to build a new watcher over the
    old one, so both stayed alive on the same file and every auto-arm and log
    line arrived twice."""
    bridge.start_global_watcher()
    first = bridge._global_log_watcher
    assert first is not None

    bridge._start_global_log_watcher()
    second = bridge._global_log_watcher

    assert second is not first
    assert not first.is_monitoring, "the previous watcher was left tailing the log"
    bridge._running = False
    if second:
        second.stop()


def test_polling_crash_is_reported_instead_of_hanging_the_ui(bridge, monkeypatch):
    """The polling thread used to have try/finally with no except: any
    unexpected error killed it silently while the UI kept showing
    "Connecting" for a session that no longer existed."""
    def explode(*args, **kwargs):
        raise RuntimeError("simulated A2S library failure")

    monkeypatch.setattr("src.web.connect_engine.a2s_client.check_server_status", explode)
    bridge._log_history.clear()
    bridge._session_status = "Connecting"

    bridge.connect_engine.connect("203.0.113.11:28015")

    assert _wait_until(lambda: not bridge.connect_engine.is_polling, timeout=6.0)
    assert bridge._session_status == "idle", "UI left stuck on a dead session"
    messages = [entry["message"] for entry in bridge.get_logs()]
    assert any("RuntimeError" in m for m in messages), "the real reason must reach the user"


def test_launch_is_held_while_a_rust_update_is_pending(bridge, monkeypatch):
    """Rust patches on every force-wipe day. Launching an outdated client
    makes Steam download the update instead of starting the game, and the
    join then fails on a protocol mismatch - so the launch must wait. The web
    UI had the auto_update setting but nothing acting on it until now."""
    # The background check starts with the bridge and runs against the
    # developer's own machine, where Rust is up to date. Let its first pass
    # finish (it then sleeps for the poll interval) before closing the gate,
    # otherwise it re-opens it mid-test. The patch keeps any later pass inert.
    _wait_until(lambda: bridge._update_status_logged != "", timeout=10.0)
    monkeypatch.setattr(bridge, "_check_rust_update_once", lambda: 3600.0)
    server = MockA2SServer(players=1, max_players=10)
    port = server.start()
    try:
        bridge._update_ready_event.clear()  # an update is pending
        with patch("src.services.steam_service.os.startfile") as mock_startfile:
            bridge.connect_engine.connect(f"127.0.0.1:{port}")
            # The server is reachable and has room, so without the gate this
            # would have launched well inside this window.
            time.sleep(3.0)
            assert not mock_startfile.called, "launched Rust while an update was still pending"

            bridge._update_ready_event.set()  # update finished
            assert _wait_until(lambda: mock_startfile.called, timeout=6.0)
    finally:
        bridge._update_ready_event.set()
        server.stop()
        bridge.connect_engine.stop(explicit=True)


def test_network_clock_is_anchored_from_steams_http_date(bridge, monkeypatch):
    """Every wipe calculation reads network_clock. Nothing in the web app
    ever anchored it, so it silently fell back to the Windows clock - and a
    drifting local clock mistimes the whole wipe hold."""
    from src.services.steam_service import BuildInfo

    clock = bridge.connect_engine.network_clock
    assert not clock.is_synced, "precondition: a fresh clock is unanchored"

    monkeypatch.setattr(
        "src.services.steam_service.fetch_latest_build_info",
        lambda: BuildInfo("12345", "Wed, 21 Oct 2026 07:28:00 GMT"),
    )
    monkeypatch.setattr("src.services.steam_service.get_local_buildid", lambda: "12345")

    bridge._check_rust_update_once()

    assert clock.is_synced
    assert clock.now().year == 2026 and clock.now().month == 10 and clock.now().day == 21


def test_reconnect_gives_up_after_repeated_refusals(bridge, monkeypatch):
    """A server that keeps refusing (outdated client, ban, password) must not
    be retried forever. Before the launch block was removed this loop was
    capped by accident - the second attempt was refused because Rust was
    already open - so an explicit budget is what stops it now."""
    monkeypatch.setattr("src.web.connect_engine._RECONNECT_BACKOFF_SECONDS", (0.05,) * 5)
    target = "203.0.113.7:28015"
    attempts = []
    monkeypatch.setattr(
        bridge.connect_engine, "connect", lambda t, **kw: attempts.append(t)
    )
    bridge._log_history.clear()

    for _ in range(10):
        bridge.connect_engine._schedule_reconnect(target)
        _wait_until(lambda: bridge.connect_engine._reconnect_timer is None, timeout=2.0)

    assert len(attempts) == 5, f"expected the retry budget to cap attempts, got {len(attempts)}"
    messages = [entry["message"] for entry in bridge.get_logs()]
    assert any("stopped reconnecting" in m.lower() or "остановлено" in m.lower() for m in messages)


def test_manual_connect_restores_the_retry_budget(bridge, monkeypatch):
    """Giving up is not permanent: when the person clicks Connect again, the
    app must try again rather than staying silently dead."""
    monkeypatch.setattr("src.web.connect_engine._RECONNECT_BACKOFF_SECONDS", (0.05,) * 5)
    target = "203.0.113.7:28015"
    bridge.connect_engine._reconnect_attempts = _MAX_RECONNECT_ATTEMPTS
    bridge.connect_engine._reconnect_target = target

    server = MockA2SServer(players=1, max_players=10)
    port = server.start()
    try:
        with patch("src.services.steam_service.os.startfile"):
            bridge.connect_engine.connect(f"127.0.0.1:{port}")
            assert bridge.connect_engine._reconnect_attempts == 0
    finally:
        server.stop()
        bridge.connect_engine.stop(explicit=True)


def test_stop_cancels_a_scheduled_retry(bridge, monkeypatch):
    """Pressing Stop must also cancel a retry that was already scheduled -
    otherwise the game gets yanked to a server the person just abandoned."""
    monkeypatch.setattr("src.web.connect_engine._RECONNECT_BACKOFF_SECONDS", (1.5,) * 5)
    target = "203.0.113.7:28015"
    attempts = []
    monkeypatch.setattr(
        bridge.connect_engine, "connect", lambda t, **kw: attempts.append(t)
    )

    bridge.connect_engine._schedule_reconnect(target)
    assert bridge.connect_engine._reconnect_timer is not None
    bridge.connect_engine.stop(explicit=True)

    time.sleep(2.0)
    assert attempts == [], "a cancelled retry must never fire"


def test_log_confirms_connection_via_real_world_loading_sequence():
    """Verified against a real successful join (2026-09-03): Rust never
    actually prints "Client connected" or "OnClientConnected" as a log
    message. The real, observed signal is the world-loading sequence
    ("Spawning World" then "Processing World") after a matched "Connecting:"
    line. See tests/fixtures/player_log_real_connect_localhost.log."""
    from src.web.connect_engine import _log_confirms_connection, _log_reports_attempt
    from src.core.smart_monitor import ConnectionSession

    session = ConnectionSession(requested_endpoint="127.0.0.1:28015")
    session.canonical_endpoint = "127.0.0.1:28015"

    # Before a matching "Connecting:" line is seen, world-loading text alone
    # must not confirm anything (it could belong to a different attempt).
    assert not _log_confirms_connection(
        "2026-09-03T11:31:10.131Z|0x34f8|[6.9s] Spawning World", "127.0.0.1:28015", session
    )

    assert _log_reports_attempt(
        "2026-09-03T11:30:56.575Z|0x34f8|Connecting: 127.0.0.1:28015 (Raknet)",
        "127.0.0.1:28015", session,
    )
    session.target_connection_attempt_seen = True

    assert _log_confirms_connection(
        "2026-09-03T11:31:10.131Z|0x34f8|[6.9s] Spawning World", "127.0.0.1:28015", session
    )


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


def test_global_watcher_auto_arms_on_manual_connect_when_enabled(bridge, tmp_path, monkeypatch):
    """A server joined manually (F1 console, Rust's own server browser, a
    friend invite) - with no Connect click in this app at all - must still
    get armed when AutoArm is on. Uses the real log line format
    ("Connecting: ip:port"), not the "Connecting to ip:port" wording the
    legacy app.py global watcher used, which never matches a real log."""
    fake_log = tmp_path / "Player.log"
    fake_log.write_text("", encoding="utf-8")
    monkeypatch.setattr(type(config), "rust_log_path", property(lambda self: fake_log))

    original_armed = history_store.get_armed_server()
    original_auto_arm = history_store.get_auto_arm()
    try:
        history_store.set_auto_arm(True)
        history_store.set_armed_server("", force=True)

        bridge.start_global_watcher()
        assert _wait_until(lambda: bridge._global_log_watcher is not None, timeout=2.0)

        with fake_log.open("a", encoding="utf-8") as fh:
            fh.write("2026-09-03T12:00:00.000Z|0x1|Connecting: 203.0.113.9:28015 (Raknet)\n")

        assert _wait_until(lambda: history_store.get_armed_server() == "203.0.113.9:28015", timeout=3.0)
    finally:
        if bridge._global_log_watcher:
            bridge._global_log_watcher.stop()
        history_store.set_armed_server(original_armed, force=True)
        history_store.set_auto_arm(original_auto_arm)


def test_global_watcher_does_not_arm_when_auto_arm_disabled(bridge, tmp_path, monkeypatch):
    """AutoArm is an explicit opt-in - a manual connect must not silently
    arm a server when the user has this setting off."""
    fake_log = tmp_path / "Player.log"
    fake_log.write_text("", encoding="utf-8")
    monkeypatch.setattr(type(config), "rust_log_path", property(lambda self: fake_log))

    original_armed = history_store.get_armed_server()
    original_auto_arm = history_store.get_auto_arm()
    try:
        history_store.set_auto_arm(False)
        history_store.set_armed_server("", force=True)

        bridge.start_global_watcher()
        assert _wait_until(lambda: bridge._global_log_watcher is not None, timeout=2.0)

        with fake_log.open("a", encoding="utf-8") as fh:
            fh.write("Connecting: 203.0.113.9:28015 (Raknet)\n")
        time.sleep(1.0)

        assert history_store.get_armed_server() == ""
    finally:
        if bridge._global_log_watcher:
            bridge._global_log_watcher.stop()
        history_store.set_armed_server(original_armed, force=True)
        history_store.set_auto_arm(original_auto_arm)


def test_global_watcher_restarts_itself_after_a_disconnect(bridge, tmp_path, monkeypatch):
    """LogWatcher stops itself on any detected disconnect line - the global
    observer must restart afterward so a later manual connect can still be
    caught, instead of silently going dark after the first disconnect it
    ever observes."""
    fake_log = tmp_path / "Player.log"
    fake_log.write_text("", encoding="utf-8")
    monkeypatch.setattr(type(config), "rust_log_path", property(lambda self: fake_log))

    original_armed = history_store.get_armed_server()
    original_auto_arm = history_store.get_auto_arm()
    try:
        history_store.set_auto_arm(True)
        history_store.set_armed_server("", force=True)

        bridge.start_global_watcher()
        assert _wait_until(lambda: bridge._global_log_watcher is not None, timeout=2.0)
        first_watcher = bridge._global_log_watcher

        with fake_log.open("a", encoding="utf-8") as fh:
            fh.write("Disconnected\n")

        assert _wait_until(
            lambda: bridge._global_log_watcher is not None and bridge._global_log_watcher is not first_watcher,
            timeout=8.0,
        )

        with fake_log.open("a", encoding="utf-8") as fh:
            fh.write("Connecting: 203.0.113.9:28015 (Raknet)\n")
        assert _wait_until(lambda: history_store.get_armed_server() == "203.0.113.9:28015", timeout=3.0)
    finally:
        if bridge._global_log_watcher:
            bridge._global_log_watcher.stop()
        history_store.set_armed_server(original_armed, force=True)
        history_store.set_auto_arm(original_auto_arm)
