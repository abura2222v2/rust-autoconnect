import asyncio
import time
import tkinter
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.gui.main_window import (
    BENCH_CONTROLS_DEFAULT_WIDTH,
    HOME_HISTORY_DEFAULT_WIDTH,
    MainWindow,
)
from src.app import AppController
from src.core.history_store import HistoryStore
from src.core.i18n import I18nManager
from src.services import steam_service

@pytest.fixture
def temp_env(monkeypatch, tmp_path):
    """Temporary APPDATA environment fixture."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def reset_default_tk_root(monkeypatch):
    """Prevent CustomTkinter image caches from binding to a destroyed test window."""
    python_root = Path(tkinter.__file__).resolve().parents[2]
    monkeypatch.setenv("TCL_LIBRARY", str(python_root / "tcl" / "tcl8.6"))
    monkeypatch.setenv("TK_LIBRARY", str(python_root / "tcl" / "tk8.6"))
    tkinter._default_root = None
    yield
    tkinter._default_root = None

def test_steam_service_parse_acf_buildid():
    content = '''
    "AppState"
    {
        "appid"     "252490"
        "buildid"   "12345678"
    }
    '''
    assert steam_service.parse_acf_buildid(content) == "12345678"
    assert steam_service.parse_acf_buildid("invalid content") is None

def test_steam_service_is_force_wipe_window():
    from datetime import datetime, timezone
    dt_normal = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    assert steam_service.is_force_wipe_window(dt_normal) is False

    dt_wipe = datetime(2026, 2, 5, 15, 0, tzinfo=timezone.utc)
    assert steam_service.is_force_wipe_window(dt_wipe) is True

def test_main_window_init_and_search_debounce(temp_env):
    store = HistoryStore()
    app = MainWindow(history_mgr=store)
    app.withdraw()

    app.search_var.set("test search")
    assert app._search_timer is not None

    if app._search_timer:
        app.after_cancel(app._search_timer)
    app.destroy()

def test_bug_09_inline_edit_unbind(temp_env):
    store = HistoryStore()
    store.add_to_history("127.0.0.1:28015", "Old Name")

    app = MainWindow(history_mgr=store)
    app.withdraw()

    app.refresh_history_ui()
    children = app.history_scroll.winfo_children()
    assert len(children) > 0

    frame = next(child for child in children if child.__class__.__name__ == "CTkFrame")
    btn = frame.winfo_children()[0]

    save_cb = app.start_inline_edit(frame, btn, "127.0.0.1:28015", "Old Name")

    entry_widget = None
    for w in frame.winfo_children():
        if hasattr(w, "get"):
            entry_widget = w
            break

    assert entry_widget is not None
    entry_widget.delete(0, "end")
    entry_widget.insert(0, "New Name")

    save_cb()
    save_cb()

    assert store.get_history()[0]["name"] == "New Name"

    if app._search_timer:
        app.after_cancel(app._search_timer)
    app.update()
    app.destroy()

def test_bug_01_reconnect_finally_cleanup(temp_env):
    app = AppController()
    app.withdraw()

    app.is_reconnecting = True
    app._poll_operation = 1
    app.run_logic("invalid_target_no_colon", 1)
    assert app.is_reconnecting is False

    app.shutdown()

def test_bug_04_graceful_shutdown():
    app = object.__new__(AppController)
    app._state_lock = threading.Lock()
    app._is_polling = True
    app._is_shutting_down = False
    app._shutdown_event = threading.Event()
    app._benchmark_stop_event = threading.Event()
    app._global_watcher_after_id = None
    app._ui_queue_after_id = None
    app.log_watcher = None
    app.global_log_watcher = None
    app._ui_dispatch_closing = False
    app._ui_dispatch_after_id = None
    app._search_timer = None
    app._session_state_after_id = None
    app._nav_marker_after_id = None
    app._status_pulse_after_id = None
    app._operation_lock = threading.Lock()
    app._next_poll_operation = MagicMock()
    app.after_cancel = MagicMock()
    app.destroy = MagicMock()

    with patch("src.app.MainWindow.shutdown") as window_shutdown:
        AppController.shutdown(app)

    assert app.is_polling is False
    assert app._shutdown_event.is_set()
    assert app._benchmark_stop_event.is_set()
    window_shutdown.assert_called_once_with()

def test_save_user_config_exists():
    assert hasattr(AppController, "save_user_config")

def test_on_swarm_change_uses_swarm_checkbox(temp_env):
    store = HistoryStore()
    app = MainWindow(history_mgr=store)
    app.withdraw()
    app.swarm_var.set(False)
    app._on_swarm_change()
    assert store.get_swarm_enabled() is False
    if app._search_timer:
        app.after_cancel(app._search_timer)
    app.destroy()

def test_benchmark_views_are_embedded(temp_env):
    store = HistoryStore()
    app = MainWindow(history_mgr=store)
    app.withdraw()
    assert app.bench_view_tabs.cget("values") == ["Run log", "Online ranking"]
    assert not hasattr(app, "bench_local_history")
    assert not hasattr(app, "leaderboard_checkbox")
    assert not hasattr(app, "reset_identity_btn")
    app.show_benchmark_view("Run log")
    assert app.bench_log.winfo_manager() == "grid"
    if app._search_timer:
        app.after_cancel(app._search_timer)
    app.destroy()


def test_sidebar_version_and_rust_status_are_compact(temp_env):
    store = HistoryStore()
    app = MainWindow(history_mgr=store)
    app.withdraw()

    app.set_version_status("v1.3.0", "Latest", "#2ECC71")
    app.set_rust_status(False)
    assert app.version_label.cget("text") == "Version: v1.3.0"
    assert app.version_state_label.cget("text") == "Latest"
    assert app.rust_status_label.cget("text") == "Rust"

    if app._search_timer:
        app.after_cancel(app._search_timer)
    app.destroy()


def test_background_ui_callbacks_are_queued_until_the_ui_loop_runs(temp_env):
    store = HistoryStore()
    app = MainWindow(history_mgr=store)
    app.withdraw()
    called = []

    worker = threading.Thread(target=app._dispatch_ui, args=(called.append, "ready"))
    worker.start()
    worker.join()
    assert called == []

    app._drain_ui_callbacks()
    assert called == ["ready"]
    app.shutdown()


def test_address_field_is_plain_entry_and_keeps_manual_connection(temp_env):
    store = HistoryStore()
    app = MainWindow(history_mgr=store)
    app.withdraw()

    assert app.ip_entry.__class__.__name__ == "CTkEntry"
    app.set_address("client.connect 127.0.0.1:28015")
    assert app.get_target_ip() == "127.0.0.1:28015"

    if app._search_timer:
        app.after_cancel(app._search_timer)
    app.destroy()


def test_splitters_clamp_and_reset_at_constrained_widths(temp_env):
    store = HistoryStore()
    app = MainWindow(history_mgr=store)
    app.withdraw()

    app._history_width = 10_000
    app._apply_home_split(920)
    assert 0 < app._applied_history_width < 920
    with patch.object(app.home_content, "winfo_width", return_value=920):
        app._reset_home_split(None)
    assert app._history_width == HOME_HISTORY_DEFAULT_WIDTH

    app._bench_controls_width = 10_000
    app._apply_bench_split(760)
    assert 0 < app._applied_bench_controls_width < 760
    with patch.object(app.bench_content, "winfo_width", return_value=760):
        app._reset_bench_split(None)
    assert app._bench_controls_width == BENCH_CONTROLS_DEFAULT_WIDTH

    if app._search_timer:
        app.after_cancel(app._search_timer)
    app.destroy()


def test_splitter_drag_does_not_change_geometry_or_install_hover_handlers(temp_env):
    store = HistoryStore()
    app = MainWindow(history_mgr=store)
    app.withdraw()

    home_width = app.home_splitter.cget("width")
    bench_width = app.bench_splitter.cget("width")

    class MockEvent:
        x_root = 0
    event = MockEvent()

    app._start_home_resize(event)
    app._finish_home_resize(event)
    app._start_bench_resize(event)
    app._finish_bench_resize(event)

    assert app.home_splitter.cget("width") == home_width
    assert app.bench_splitter.cget("width") == bench_width
    assert app.home_splitter.bind("<Enter>") in (None, "")
    assert app.bench_splitter.bind("<Leave>") in (None, "")

    if app._search_timer:
        app.after_cancel(app._search_timer)
    app.destroy()


def test_log_textbox_truncation(temp_env):
    store = HistoryStore()
    app = MainWindow(history_mgr=store)
    app.withdraw()
    for i in range(510):
        app.log(f"Test log line {i}")
    lines = int(app.log_textbox.index('end-1c').split('.')[0])
    assert lines <= 500
    if app._search_timer:
        app.after_cancel(app._search_timer)
    app.destroy()


def test_log_clear_and_auto_scroll_controls(temp_env):
    store = HistoryStore()
    app = MainWindow(history_mgr=store)
    app.withdraw()

    app.auto_scroll.set(False)
    app.log("Retained without scrolling")
    assert "Retained without scrolling" in app.log_textbox.get("1.0", "end")

    app.clear_log()
    assert app.log_textbox.get("1.0", "end").strip() == ""
    app.destroy()


def test_session_state_reflects_armed_server(temp_env):
    store = HistoryStore()
    store.add_to_history("127.0.0.1:28015", "Test Server")
    app = MainWindow(history_mgr=store)
    app.withdraw()

    app.toggle_armed("127.0.0.1:28015")
    assert "armed" in app.footer_armed_label.cget("text").casefold()
    app.set_connection_state("Connected", "127.0.0.1:28015")
    assert app.session_status_var.get() == "Connected"
    assert app.last_connected_var.get() == "127.0.0.1:28015"
    app.destroy()

def test_leaderboard_load_more_disabled_and_destroyed_window(temp_env):
    from src.gui.leaderboard_window import LeaderboardWindow
    store = HistoryStore()
    app = MainWindow(history_mgr=store)
    app.withdraw()
    lb = LeaderboardWindow(app)
    lb.withdraw()
    
    small_data = [{'cpu': 'CPU', 'disk': 'Disk', 'total_time': 10.0}]
    lb._render_data(small_data, is_new_search=True)
    assert lb.load_more_btn.cget("state") == "disabled"
    
    lb.destroy()
    lb._render_data(small_data, is_new_search=False)
    
    if app._search_timer:
        app.after_cancel(app._search_timer)
    app.destroy()

def test_tooltip_topmost(temp_env):
    from src.gui.tooltip import ToolTip
    store = HistoryStore()
    app = MainWindow(history_mgr=store)
    app.withdraw()
    tip = ToolTip(app.save_cfg_btn, "Test tooltip")
    tip.showtip()
    assert tip.tw is not None
    assert tip.tw.attributes('-topmost')
    tip.hidetip()
    if app._search_timer:
        app.after_cancel(app._search_timer)
    app.destroy()
