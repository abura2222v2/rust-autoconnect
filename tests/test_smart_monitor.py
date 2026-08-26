from datetime import datetime, timedelta, timezone

from src.core.smart_monitor import ConnectionPhase, ConnectionSession, PollingPolicy


def test_schedule_uses_low_watch_and_turbo_intervals():
    now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
    session = ConnectionSession("server.example:28015", wipe_at=now + timedelta(hours=2), smart_mode=True)
    assert session.interval_seconds(now) == PollingPolicy().idle_seconds
    assert session.phase == ConnectionPhase.SCHEDULED
    session.wipe_at = now + timedelta(minutes=20)
    assert session.interval_seconds(now) == PollingPolicy().watch_seconds
    session.wipe_at = now + timedelta(minutes=3)
    assert session.interval_seconds(now) == PollingPolicy().turbo_seconds


def test_down_and_swarm_hints_have_bounded_turbo_window():
    now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
    session = ConnectionSession("127.0.0.1:28015", smart_mode=True)
    session.request_turbo(now)
    assert session.interval_seconds(now) == 2.0
    assert session.interval_seconds(now + timedelta(minutes=6)) == PollingPolicy().watch_seconds
    assert session.phase == ConnectionPhase.WATCH


def test_confirmed_offline_starts_only_one_turbo_window():
    now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
    session = ConnectionSession("127.0.0.1:28015", smart_mode=True)
    session.observe_server_down(now)
    assert session.interval_seconds(now) == PollingPolicy().turbo_seconds
    assert session.interval_seconds(now + timedelta(minutes=6)) == PollingPolicy().watch_seconds
    session.observe_server_down(now + timedelta(minutes=7))
    assert session.interval_seconds(now + timedelta(minutes=7)) == PollingPolicy().watch_seconds


def test_initial_query_timeout_uses_backoff_without_turbo():
    now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
    session = ConnectionSession("127.0.0.1:28015", smart_mode=True)

    assert not session.observe_query_result(False, now)
    assert session.query_retry_seconds(now) == 30.0
    assert session.phase == ConnectionPhase.SCHEDULED

    assert not session.observe_query_result(False, now)
    assert session.query_retry_seconds(now) == 30.0
    assert session.phase == ConnectionPhase.SCHEDULED


def test_confirmed_server_disappearance_enables_turbo_after_two_misses():
    now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
    session = ConnectionSession("127.0.0.1:28015", smart_mode=True)

    assert not session.observe_query_result(True, now)
    assert not session.observe_query_result(False, now)
    assert session.query_retry_seconds(now) == 30.0
    assert session.observe_query_result(False, now)
    assert session.interval_seconds(now) == PollingPolicy().turbo_seconds


def test_full_server_uses_short_slot_check_without_turbo():
    now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
    session = ConnectionSession("127.0.0.1:28015", smart_mode=True)

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


def test_launch_confirmation_probe_is_short_and_independent_of_wipe_phase():
    """Rust loading must keep observing the target without launching again."""
    policy = PollingPolicy()

    assert policy.launch_confirmation_probe_seconds == 5.0


def test_final_pre_wipe_window_holds_old_server_until_restart_signal():
    now = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)
    session = ConnectionSession("127.0.0.1:28015", wipe_at=now + timedelta(minutes=4), smart_mode=True)

    assert session.begin_wipe_restart_hold(now)
    assert session.phase == ConnectionPhase.WAITING_FOR_WIPE_RESTART
    assert session.confirm_wipe_restart()
    assert session.wipe_restart_seen


def test_pre_wipe_hold_does_not_start_too_early_or_after_steam_launch():
    now = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)
    early = ConnectionSession("127.0.0.1:28015", wipe_at=now + timedelta(minutes=6), smart_mode=True)
    launched = ConnectionSession(
        "127.0.0.1:28015", wipe_at=now + timedelta(minutes=4), launched_by_app=True, smart_mode=True
    )

    assert not early.begin_wipe_restart_hold(now)
    assert not launched.begin_wipe_restart_hold(now)


def test_pre_wipe_hold_releases_only_after_confirmed_server_disappearance():
    now = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)
    session = ConnectionSession("127.0.0.1:28015", wipe_at=now + timedelta(minutes=4), smart_mode=True)
    assert session.begin_wipe_restart_hold(now)

    assert not session.observe_query_result(True, now)
    assert not session.observe_query_result(False, now)
    assert session.observe_query_result(False, now)
    assert session.confirm_wipe_restart()
    assert session.wipe_restart_seen


def test_pre_wipe_hold_can_release_after_scheduled_time_when_server_is_offline():
    now = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)
    session = ConnectionSession("127.0.0.1:28015", wipe_at=now + timedelta(minutes=4), smart_mode=True)
    assert session.begin_wipe_restart_hold(now)
    assert not session.wipe_time_has_arrived(now)
    assert session.wipe_time_has_arrived(now + timedelta(minutes=4))


def test_provider_online_empty_server_is_only_a_hint_not_turbo():
    now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
    session = ConnectionSession("127.0.0.1:28015", smart_mode=True)
    changed = session.apply_provider_hint(
        online=True, wipe_at=None, source="gamemonitoring", confidence="medium",
        checked_at=now, now=now,
    )
    assert changed
    assert session.interval_seconds(now) == PollingPolicy().idle_seconds


def test_provider_offline_enters_turbo_then_watch_not_idle():
    now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
    session = ConnectionSession("127.0.0.1:28015", smart_mode=True)
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


def test_connection_diagnostics_record_only_stage_changes():
    session = ConnectionSession("127.0.0.1:28015")

    elapsed, changed = session.record_stage("Resolving server address")
    repeated_elapsed, repeated_changed = session.record_stage("Resolving server address")

    assert changed and not repeated_changed
    assert elapsed >= 0 and repeated_elapsed >= elapsed
    assert session.diagnostic_events == [("Resolving server address", elapsed)]


def test_selected_server_uses_thirty_second_normal_poll_and_two_second_turbo():
    now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
    session = ConnectionSession("127.0.0.1:28015", smart_mode=True)

    assert session.interval_seconds(now) == 30.0
    session.request_turbo(now)
    assert session.interval_seconds(now) == 2.0


def test_swarm_hint_does_not_escalate_polling_rate():
    now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
    session = ConnectionSession("127.0.0.1:28015", smart_mode=True)

    assert session.interval_seconds(now, swarm_hint=True) == 30.0


def test_force_wipe_fingerprint_change_requires_window_and_releases_hold():
    now = datetime(2026, 8, 6, 17, 56, tzinfo=timezone.utc)
    session = ConnectionSession("127.0.0.1:28015", force_wipe_at=now + timedelta(minutes=4), smart_mode=True)
    assert session.begin_wipe_restart_hold(now)
    assert not session.observe_provider_wipe_fingerprint(("2632", "old", 1), now)
    assert session.observe_provider_wipe_fingerprint(("2633", "new", 2), now)
    assert session.confirm_wipe_restart()


def test_provider_wipe_restart_requires_offline_then_online():
    session = ConnectionSession("127.0.0.1:28015")
    assert not session.observe_provider_wipe_availability(True)
    assert not session.observe_provider_wipe_availability(False)
    assert session.observe_provider_wipe_availability(True)


# --- Normal mode (smart_mode=False, the current default) ---


def test_normal_mode_is_always_turbo_regardless_of_wipe_schedule():
    now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
    session = ConnectionSession("127.0.0.1:28015", wipe_at=now + timedelta(hours=5))
    assert not session.smart_mode
    assert session.interval_seconds(now) == PollingPolicy().turbo_seconds
    assert session.phase == ConnectionPhase.TURBO


def test_normal_mode_ignores_force_wipe_schedule_too():
    now = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
    session = ConnectionSession("127.0.0.1:28015", force_wipe_at=now + timedelta(hours=5))
    assert session.select_phase(now) == ConnectionPhase.TURBO


def test_normal_mode_never_enters_pre_wipe_restart_hold():
    now = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)
    session = ConnectionSession("127.0.0.1:28015", wipe_at=now + timedelta(minutes=4))
    assert not session.begin_wipe_restart_hold(now)
    assert session.phase != ConnectionPhase.WAITING_FOR_WIPE_RESTART


def test_normal_mode_still_respects_stop_event():
    session = ConnectionSession("127.0.0.1:28015")
    session.cancel()
    assert session.select_phase() == ConnectionPhase.IDLE
