from datetime import datetime, timedelta, timezone

from src.core.smart_monitor import ConnectionPhase, ConnectionSession, PollingPolicy


def test_schedule_uses_low_watch_and_turbo_intervals():
    now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
    session = ConnectionSession("server.example:28015", wipe_at=now + timedelta(hours=2))
    assert session.interval_seconds(now) == PollingPolicy().idle_seconds
    assert session.phase == ConnectionPhase.SCHEDULED
    session.wipe_at = now + timedelta(minutes=20)
    assert session.interval_seconds(now) == PollingPolicy().watch_seconds
    session.wipe_at = now + timedelta(minutes=3)
    assert session.interval_seconds(now) == PollingPolicy().turbo_seconds


def test_down_and_swarm_hints_have_bounded_turbo_window():
    now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
    session = ConnectionSession("127.0.0.1:28015")
    session.request_turbo(now)
    assert session.interval_seconds(now) == 1.0
    assert session.interval_seconds(now + timedelta(minutes=6)) == 30.0
    assert session.phase == ConnectionPhase.SCHEDULED


def test_confirmed_offline_starts_only_one_turbo_window():
    now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
    session = ConnectionSession("127.0.0.1:28015")
    session.observe_server_down(now)
    assert session.interval_seconds(now) == PollingPolicy().turbo_seconds
    assert session.interval_seconds(now + timedelta(minutes=6)) == PollingPolicy().idle_seconds
    session.observe_server_down(now + timedelta(minutes=7))
    assert session.interval_seconds(now + timedelta(minutes=7)) == PollingPolicy().idle_seconds


def test_cancel_stops_smart_session():
    session = ConnectionSession("127.0.0.1:28015")
    session.cancel()
    assert session.phase == ConnectionPhase.IDLE
    assert session.stop_event.is_set()
