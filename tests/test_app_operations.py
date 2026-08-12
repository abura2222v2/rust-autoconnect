import asyncio
import queue
import threading
from unittest.mock import MagicMock, patch

from src.app import AppController
from src.core.smart_monitor import ConnectionPhase, ConnectionSession


def make_controller_stub():
    controller = object.__new__(AppController)
    controller.async_loop = MagicMock()
    controller._operation_lock = threading.Lock()
    controller._poll_operation = 2
    controller._benchmark_operation = 3
    controller._shutdown_event = threading.Event()
    controller._pending_benchmark_restore = None
    controller._ui_queue = queue.Queue()
    controller.after = lambda delay, callback: "scheduled"
    return controller


def test_ui_dispatch_discards_stale_operation():
    controller = make_controller_stub()
    called = []
    controller.dispatch_ui(called.append, "stale", operation=("poll", 1))
    controller.dispatch_ui(called.append, "current", operation=("benchmark", 3))

    controller._drain_ui_queue()

    assert called == ["current"]


def test_restore_benchmark_cfg_replaces_modified_cfg(tmp_path):
    cfg_path = tmp_path / "cfg"
    backup_path = tmp_path / "backup"
    work_path = tmp_path / "work"
    cfg_path.mkdir()
    backup_path.mkdir()
    (cfg_path / "keys.cfg").write_text("benchmark", encoding="utf-8")
    (backup_path / "keys.cfg").write_text("original", encoding="utf-8")
    (backup_path / "operation.log").write_text("temporary", encoding="utf-8")

    assert AppController._restore_benchmark_cfg(str(cfg_path), str(backup_path), str(work_path))
    assert (cfg_path / "keys.cfg").read_text(encoding="utf-8") == "original"
    assert not (cfg_path / "operation.log").exists()
    assert not backup_path.exists()
    assert not work_path.exists()


def test_restore_benchmark_cfg_rolls_back_when_copy_fails(tmp_path, monkeypatch):
    cfg_path = tmp_path / "cfg"
    backup_path = tmp_path / "backup"
    work_path = tmp_path / "work"
    cfg_path.mkdir()
    backup_path.mkdir()
    (cfg_path / "keys.cfg").write_text("benchmark", encoding="utf-8")
    (backup_path / "keys.cfg").write_text("original", encoding="utf-8")

    def fail_copy(source, destination, *args, **kwargs):
        raise OSError("simulated copy failure")

    monkeypatch.setattr("src.app.shutil.copytree", fail_copy)

    assert not AppController._restore_benchmark_cfg(str(cfg_path), str(backup_path), str(work_path))
    assert (cfg_path / "keys.cfg").read_text(encoding="utf-8") == "benchmark"
    assert backup_path.exists()


def test_forced_reconnect_starts_a_new_poll_operation():
    controller = make_controller_stub()
    controller._state_lock = threading.Lock()
    controller._is_reconnecting = False
    controller._is_polling = False
    controller._poll_stop_event = threading.Event()
    controller._poll_stop_event.set()
    controller._poll_wake_event = threading.Event()
    controller.ip_entry = MagicMock()
    controller.connect_btn = MagicMock()
    controller.set_connection_state = MagicMock()
    controller.swarm_service = MagicMock()
    controller.t = lambda key: "Stop"

    with patch("src.app.threading.Thread") as thread:
        AppController.start_process_force(controller, "127.0.0.1:28015")

    assert controller.is_polling is True
    assert controller.is_reconnecting is True
    assert controller._poll_stop_event.is_set() is False
    assert controller._poll_operation > 2
    assert controller._active_session.queue_on_full is False
    thread.assert_called_once_with(
        target=controller.run_logic,
        args=("127.0.0.1:28015", controller._poll_operation),
        daemon=True,
        name="forced-server-poll",
    )
    thread.return_value.start.assert_called_once()


def test_connect_starts_polling_in_a_background_thread():
    controller = make_controller_stub()
    controller._state_lock = threading.Lock()
    controller._is_polling = False
    controller._is_reconnecting = False
    controller._poll_stop_event = threading.Event()
    controller._poll_wake_event = threading.Event()
    controller.ip_entry = MagicMock()
    controller.connect_btn = MagicMock()
    controller.set_connection_state = MagicMock()
    controller.t = lambda key, **_kwargs: {"stop": "Stop"}.get(key, key)

    with patch("src.app.threading.Thread") as thread:
        AppController.start_process(controller, "127.0.0.1:28015")

    assert controller.is_polling is True
    assert controller._active_session.queue_on_full is True
    thread.assert_called_once_with(
        target=controller.run_logic,
        args=("127.0.0.1:28015", controller._poll_operation),
        daemon=True,
        name="server-poll",
    )
    thread.return_value.start.assert_called_once()


def test_deferred_benchmark_restore_reenables_button_after_rust_exits():
    controller = make_controller_stub()
    controller.process_monitor = MagicMock()
    controller.process_monitor.is_rust_running.return_value = False
    controller._restore_benchmark_cfg = MagicMock(return_value=True)
    controller.log_bench = MagicMock()
    controller.bench_btn = MagicMock()
    controller.t = lambda key: "Run Test"
    calls = []
    controller.dispatch_ui = lambda callback, *args, **kwargs: calls.append((callback, args, kwargs))

    controller._restore_benchmark_cfg_after_rust_exit("cfg", "backup", "work", 3)

    controller._restore_benchmark_cfg.assert_called_once_with("cfg", "backup", "work")
    assert calls[0][0] == controller.bench_btn.configure
    assert calls[0][2]["state"] == "normal"
    assert calls[0][2]["operation"] == ("benchmark", 3)


def test_pending_benchmark_restore_is_recovered_during_shutdown():
    controller = make_controller_stub()
    controller._pending_benchmark_restore = ("cfg", "backup", "work", 3)
    controller.process_monitor = MagicMock()
    controller.process_monitor.is_rust_running.return_value = True
    controller._restore_benchmark_cfg = MagicMock(return_value=True)

    AppController._restore_pending_benchmark_on_shutdown(controller)

    controller.process_monitor.force_kill_rust.assert_called_once()
    controller._restore_benchmark_cfg.assert_called_once_with("cfg", "backup", "work")
    assert controller._pending_benchmark_restore is None


def test_stale_log_watcher_disconnect_is_ignored():
    controller = make_controller_stub()
    controller._state_lock = threading.Lock()
    controller._is_polling = True
    old_watcher = MagicMock()
    controller.log_watcher = MagicMock()
    controller.log_safe = MagicMock()
    controller.start_process_force = MagicMock()

    AppController._on_log_disconnect(controller, "old.example:28015", old_watcher, "Disconnected")

    controller.log_safe.assert_not_called()
    controller.start_process_force.assert_not_called()


def test_armed_session_disconnect_schedules_auto_reconnect():
    controller = make_controller_stub()
    controller._state_lock = threading.Lock()
    controller._is_polling = False
    controller._is_reconnecting = False
    controller._active_session = ConnectionSession(
        "server.example:28015", "203.0.113.10:28015", launched_by_app=True
    )
    watcher = MagicMock()
    controller.log_watcher = watcher
    controller.history_store = MagicMock()
    controller.history_store.get_armed_server.return_value = "203.0.113.10:28015"
    controller.swarm_service = MagicMock()
    controller._update_server_profile = MagicMock()
    controller.log_safe = MagicMock()
    controller.t = lambda key, **_kwargs: key

    with patch("src.app.threading.Thread") as thread:
        AppController._on_log_disconnect(controller, "server.example:28015", watcher, "Disconnected")

    names = [call.kwargs.get("name") for call in thread.call_args_list]
    assert "auto-reconnect-cooldown" in names


def test_disarmed_session_disconnect_never_schedules_auto_reconnect():
    controller = make_controller_stub()
    controller._state_lock = threading.Lock()
    controller._is_polling = False
    controller._is_reconnecting = False
    controller._active_session = ConnectionSession("server.example:28015", launched_by_app=True)
    watcher = MagicMock()
    controller.log_watcher = watcher
    controller.history_store = MagicMock()
    controller.history_store.get_armed_server.return_value = "another.example:28015"
    controller.swarm_service = MagicMock()
    controller._update_server_profile = MagicMock()
    controller.log_safe = MagicMock()
    controller.t = lambda key, **_kwargs: key

    with patch("src.app.threading.Thread") as thread:
        AppController._on_log_disconnect(controller, "server.example:28015", watcher, "Disconnected")

    names = [call.kwargs.get("name") for call in thread.call_args_list]
    assert "auto-reconnect-cooldown" not in names


def test_benchmark_upload_starts_when_legacy_leaderboard_flag_is_disabled():
    controller = make_controller_stub()
    controller.hardware_service = MagicMock()
    controller.hardware_service.get_cpu_info.return_value = "CPU"
    controller.hardware_service.get_benchmark_storage.return_value = ("Disk", "NVMe")
    controller.log_bench = MagicMock()
    controller.update_benchmark_summary = MagicMock()
    controller.dispatch_ui = MagicMock()

    store = MagicMock()
    store.get_installation_id.return_value = "install"
    store.get_leaderboard_enabled.return_value = False

    with patch("src.app.history_store", store), patch("src.app.threading.Thread") as thread:
        AppController._record_benchmark_result(controller, "C:\\Rust", 12.0, 18.0, 3)

    store.add_benchmark_run.assert_called_once()
    thread.assert_called_once()
    thread.return_value.start.assert_called_once()


def test_benchmark_upload_is_skipped_when_local_queue_write_fails():
    controller = make_controller_stub()
    controller.hardware_service = MagicMock()
    controller.hardware_service.get_cpu_info.return_value = "CPU"
    controller.hardware_service.get_benchmark_storage.return_value = ("Disk", "NVMe")
    controller.log_bench = MagicMock()
    controller.update_benchmark_summary = MagicMock()
    controller.dispatch_ui = MagicMock()

    store = MagicMock()
    store.get_installation_id.return_value = "install"
    store.add_benchmark_run.return_value = False

    with patch("src.app.history_store", store), patch("src.app.threading.Thread") as thread:
        AppController._record_benchmark_result(controller, "C:\\Rust", 12.0, 18.0, 3)

    thread.assert_not_called()
    controller.dispatch_ui.assert_not_called()


def test_failed_benchmark_upload_remains_pending():
    controller = make_controller_stub()
    controller.log_bench = MagicMock()
    store = MagicMock()
    run = {"id": "pending"}

    with patch("src.app.history_store", store), patch("src.services.leaderboard_service.leaderboard_service.submit_run", return_value=False):
        AppController._submit_benchmark_run_bg(controller, run)

    store.mark_benchmark_run_synced.assert_not_called()
    assert "remains pending" in controller.log_bench.call_args.args[0]


def test_submitted_benchmark_warns_when_sync_marker_write_fails():
    controller = make_controller_stub()
    controller.log_bench = MagicMock()
    store = MagicMock()
    store.mark_benchmark_run_synced.return_value = False
    run = {"id": "submitted"}

    with patch("src.app.history_store", store), patch("src.services.leaderboard_service.leaderboard_service.submit_run", return_value=True):
        AppController._submit_benchmark_run_bg(controller, run)

    store.mark_benchmark_run_synced.assert_called_once_with("submitted")
    assert "may retry later" in controller.log_bench.call_args.args[0]


def test_pending_benchmark_runs_are_retried_on_startup():
    controller = make_controller_stub()
    controller._submit_benchmark_run_bg = MagicMock()
    pending = {"id": "pending", "sync_state": "pending"}
    synced = {"id": "synced", "sync_state": "synced"}
    store = MagicMock()
    store.get_benchmark_runs.return_value = [pending, synced]

    with patch("src.app.history_store", store):
        AppController._retry_pending_benchmark_runs(controller)

    controller._submit_benchmark_run_bg.assert_called_once_with(pending)


def test_application_version_keeps_installed_version_and_reports_update():
    controller = make_controller_stub()
    controller.set_version_status = MagicMock()
    controller.dispatch_ui = lambda callback, *args, **kwargs: callback(*args, **kwargs)

    with patch("src.services.release_service.release_service.fetch_latest_version", return_value="v1.4.0"):
        AppController.check_application_version(controller)

    controller.set_version_status.assert_called_once_with("v0.6.1", "Update: v1.4.0", "#F97316")


def test_application_version_reports_offline_without_replacing_local_version():
    controller = make_controller_stub()
    controller.set_version_status = MagicMock()
    controller.dispatch_ui = lambda callback, *args, **kwargs: callback(*args, **kwargs)

    with patch("src.services.release_service.release_service.fetch_latest_version", return_value=None):
        AppController.check_application_version(controller)

    controller.set_version_status.assert_called_once_with("v0.6.1", "Offline", "#98A2B3")


def test_only_client_connected_confirms_the_current_connection():
    session = ConnectionSession(
        "server.example:28015", canonical_endpoint="203.0.113.10:28015",
    )

    assert not AppController._log_confirms_current_connection("Spawning local player", "server.example:28015", session)
    assert not AppController._log_confirms_current_connection(
        "Client connected to 203.0.113.99:28015", "server.example:28015", session,
    )
    assert AppController._log_confirms_current_connection(
        "Client connected to 203.0.113.10:28015", "server.example:28015", session,
    )
    assert AppController._log_confirms_current_connection(
        "Client connected", "server.example:28015", session,
    )
    assert not AppController._log_confirms_current_connection(
        "[Bootstrap] DONE!", "server.example:28015", session,
    )


def test_swarm_status_messages_are_color_coded():
    controller = object.__new__(AppController)
    controller.log_safe = MagicMock()

    AppController._on_swarm_status(controller, "connected")
    assert controller.log_safe.call_args.args == ("Swarm: connected.", "#55C95D")

    AppController._on_swarm_status(controller, "not_configured")
    assert "public Supabase key" in controller.log_safe.call_args.args[0]
    assert controller.log_safe.call_args.args[1] == "#DE5148"


def test_swarm_hint_only_wakes_local_confirmation_probe():
    controller = object.__new__(AppController)
    controller._state_lock = threading.Lock()
    controller._is_polling = True
    controller._poll_wake_event = threading.Event()
    controller._active_session = ConnectionSession("server.example:28015", "203.0.113.10:28015")
    controller.swarm_service = MagicMock()
    controller.swarm_service.current_ip_port = "203.0.113.10:28015"
    controller.log_safe = MagicMock()

    AppController._handle_swarm_event_ui(controller, "server_connected", "203.0.113.10:28015")

    assert controller._poll_wake_event.is_set()
    assert controller._active_session.phase == ConnectionPhase.IDLE
    assert controller._active_session.interval_seconds() == 1.0
