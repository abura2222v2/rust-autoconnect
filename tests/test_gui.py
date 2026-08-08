import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.gui.main_window import MainWindow
from src.app import AppController
from src.core.history_store import HistoryStore
from src.core.i18n import I18nManager
from src.services import steam_service

@pytest.fixture
def temp_env(monkeypatch, tmp_path):
    """Temporary APPDATA environment fixture."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    return tmp_path

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

    frame = children[0]
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
    app.destroy()

def test_bug_01_reconnect_finally_cleanup(temp_env):
    app = AppController()
    app.withdraw()

    app.is_reconnecting = True
    app.run_logic("invalid_target_no_colon")
    assert app.is_reconnecting is False

    if app._search_timer:
        app.after_cancel(app._search_timer)
    app.destroy()

def test_bug_04_graceful_shutdown(temp_env):
    app = AppController()
    app.withdraw()

    app.is_polling = True
    app.quit_window()
    app.update()

    assert app.is_polling is False

def test_save_user_config_exists(temp_env):
    store = HistoryStore()
    app = MainWindow(history_mgr=store)
    app.withdraw()
    assert hasattr(app, "save_user_config")
    app.save_user_config()
    if app._search_timer:
        app.after_cancel(app._search_timer)
    app.destroy()

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

def test_open_leaderboard_single_instance(temp_env):
    store = HistoryStore()
    app = MainWindow(history_mgr=store)
    app.withdraw()
    app.open_leaderboard()
    assert hasattr(app, "lb_window")
    first_lb = app.lb_window
    assert first_lb.winfo_exists()
    app.open_leaderboard()
    assert app.lb_window is first_lb
    if app._search_timer:
        app.after_cancel(app._search_timer)
    first_lb.destroy()
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
