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
    assert session.interval_seconds(now + timedelta(minutes=6)) == PollingPolicy().watch_seconds
    assert session.phase == ConnectionPhase.WATCH


def test_confirmed_offline_starts_only_one_turbo_window():
    now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
    session = ConnectionSession("127.0.0.1:28015")
    session.observe_server_down(now)
    assert session.interval_seconds(now) == PollingPolicy().turbo_seconds
    assert session.interval_seconds(now + timedelta(minutes=6)) == PollingPolicy().watch_seconds
    session.observe_server_down(now + timedelta(minutes=7))
    assert session.interval_seconds(now + timedelta(minutes=7)) == PollingPolicy().watch_seconds


def test_initial_query_timeout_uses_backoff_without_turbo():
    now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
    session = ConnectionSession("127.0.0.1:28015")

    assert not session.observe_query_result(False, now)
    assert session.query_retry_seconds(now) == 30.0
    assert session.phase == ConnectionPhase.SCHEDULED

    assert not session.observe_query_result(False, now)
    assert session.query_retry_seconds(now) == 60.0
    assert session.phase == ConnectionPhase.SCHEDULED


def test_confirmed_server_disappearance_enables_turbo_after_two_misses():
    now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
    session = ConnectionSession("127.0.0.1:28015")

    assert not session.observe_query_result(True, now)
    assert not session.observe_query_result(False, now)
    assert session.query_retry_seconds(now) == 30.0
    assert session.observe_query_result(False, now)
    assert session.interval_seconds(now) == PollingPolicy().turbo_seconds


def test_full_server_uses_short_slot_check_without_turbo():
    now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
    session = ConnectionSession("127.0.0.1:28015")

    assert session.full_server_retry_seconds(now) == 30.0
    assert session.phase == ConnectionPhase.SCHEDULED


def test_manual_connect_has_bounded_fast_retry_then_gradual_backoff():
    now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
    session = ConnectionSession("127.0.0.1:28015", queue_on_full=True)

    for _ in range(12):
        session.observe_query_result(False, now)
        assert session.query_retry_seconds(now) == 5.0
    for _ in range(12):
        session.observe_query_result(False, now)
        assert session.query_retry_seconds(now) == 15.0
    assert session.query_retry_seconds(now) == 15.0
    session.observe_query_result(False, now)
    assert session.query_retry_seconds(now) == 30.0
    session.observe_query_result(False, now)
    assert session.query_retry_seconds(now) == 60.0


def test_provider_online_empty_server_is_only_a_hint_not_turbo():
    now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
    session = ConnectionSession("127.0.0.1:28015")
    changed = session.apply_provider_hint(
        online=True, wipe_at=None, source="gamemonitoring", confidence="medium",
        checked_at=now, now=now,
    )
    assert changed
    assert session.interval_seconds(now) == PollingPolicy().idle_seconds


def test_provider_offline_enters_turbo_then_watch_not_idle():
    now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
    session = ConnectionSession("127.0.0.1:28015")
    session.apply_provider_hint(
        online=False, wipe_at=None, source="gamemonitoring", confidence="medium",
        checked_at=now, now=now,
    )
    assert session.interval_seconds(now) == PollingPolicy().turbo_seconds
    assert session.interval_seconds(now + timedelta(minutes=6)) == PollingPolicy().watch_seconds


def test_cancel_stops_smart_session():
    session = ConnectionSession("127.0.0.1:28015")
    session.cancel()
    assert session.phase == ConnectionPhase.IDLE
    assert session.stop_event.is_set()
