from datetime import datetime, timedelta, timezone
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.app import AppController
from src.core.network_clock import NetworkClock
from src.core.smart_monitor import ConnectionPhase, ConnectionSession
from src.services import steam_service


def test_force_wipe_uses_london_time_and_converts_to_moldova():
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    wipe = steam_service.next_force_wipe_at(now)
    assert wipe == datetime(2026, 8, 6, 18, tzinfo=timezone.utc)
    assert wipe.astimezone(steam_service.ZoneInfo("Europe/Chisinau")).hour == 21


def test_force_wipe_polling_is_minutely_only_near_event():
    wipe = datetime(2026, 8, 6, 18, tzinfo=timezone.utc)
    assert steam_service.force_wipe_poll_interval(wipe - timedelta(minutes=30)) == 60.0
    assert steam_service.force_wipe_poll_interval(wipe + timedelta(minutes=30)) == 60.0
    assert steam_service.force_wipe_poll_interval(wipe + timedelta(minutes=31)) == 1800.0


def test_force_wipe_session_has_post_wipe_watch_window():
    wipe = datetime(2026, 8, 6, 18, tzinfo=timezone.utc)
    session = ConnectionSession("example.test:28015", force_wipe_at=wipe)
    assert session.select_phase(wipe - timedelta(minutes=20)) == ConnectionPhase.WATCH
    assert session.select_phase(wipe - timedelta(minutes=4)) == ConnectionPhase.TURBO
    assert session.select_phase(wipe) == ConnectionPhase.TURBO
    assert session.select_phase(wipe + timedelta(minutes=4)) == ConnectionPhase.TURBO
    assert session.select_phase(wipe + timedelta(minutes=10)) == ConnectionPhase.WATCH
    assert session.select_phase(wipe + timedelta(minutes=31)) == ConnectionPhase.SCHEDULED
    assert session.force_wipe_notified is False


def test_relevant_force_wipe_keeps_the_current_event_after_wipe():
    now = datetime(2026, 8, 6, 18, 10, tzinfo=timezone.utc)
    assert steam_service.relevant_force_wipe_at(now) == datetime(2026, 8, 6, 18, tzinfo=timezone.utc)


def test_network_clock_uses_monotonic_time_after_http_sample():
    clock = NetworkClock()
    assert clock.observe_http_date("Thu, 01 Jan 2026 00:00:00 GMT", received_monotonic=100.0)
    with patch("src.core.network_clock.time.monotonic", return_value=105.0):
        assert clock.now() == datetime(2026, 1, 1, 0, 0, 5, tzinfo=timezone.utc)
    assert clock.is_synced


def test_network_clock_rejects_invalid_http_date():
    assert not NetworkClock().observe_http_date("not a date")


def _update_controller_stub():
    controller = object.__new__(AppController)
    controller.network_clock = NetworkClock()
    controller._update_ready_event = threading.Event()
    controller._update_ready_event.set()
    controller._update_required = False
    controller._update_steam_opened = False
    controller._update_status_logged = ""
    controller.process_monitor = SimpleNamespace(is_rust_running=lambda: False)
    controller.log_safe = MagicMock()
    controller.t = lambda key: key
    return controller


def test_update_check_blocks_connect_and_opens_downloads_when_rust_is_outdated():
    controller = _update_controller_stub()
    info = steam_service.BuildInfo("200", "Thu, 01 Jan 2026 00:00:00 GMT")
    with patch.object(steam_service, "fetch_latest_build_info", return_value=info), \
         patch.object(steam_service, "get_local_buildid", return_value="100"), \
         patch.object(steam_service, "open_steam_downloads", return_value=True) as open_downloads:
        delay = controller._check_rust_update_once()

    assert delay == 1800.0
    assert controller._update_required is True
    assert not controller._update_ready_event.is_set()
    open_downloads.assert_called_once_with()


def test_update_check_releases_connect_after_local_build_matches():
    controller = _update_controller_stub()
    controller._update_required = True
    controller._update_ready_event.clear()
    info = steam_service.BuildInfo("200", None)
    with patch.object(steam_service, "fetch_latest_build_info", return_value=info), \
         patch.object(steam_service, "get_local_buildid", return_value="200"), \
         patch.object(steam_service, "open_steam_downloads") as open_downloads:
        controller._check_rust_update_once()

    assert controller._update_required is False
    assert controller._update_ready_event.is_set()
    open_downloads.assert_not_called()
