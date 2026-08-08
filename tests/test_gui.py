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
    # Non-wipe date: Jan 15, 2026
    dt_normal = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    assert steam_service.is_force_wipe_window(dt_normal) is False

    # Force wipe date: Feb 5, 2026 15:00 UTC (First Thursday of Feb 2026)
    dt_wipe = datetime(2026, 2, 5, 15, 0, tzinfo=timezone.utc)
    assert steam_service.is_force_wipe_window(dt_wipe) is True

def test_main_window_init_and_search_debounce(temp_env):
    """Test MainWindow creation and search bar debouncing (UI stutter fix)."""
    store = HistoryStore()
    app = MainWindow(history_mgr=store)
    app.withdraw()

    # Verify search debounce timer setup
    app.search_var.set("test search")
    assert app._search_timer is not None

    # Cancel pending after call before destroying
    app.after_cancel(app._search_timer)
    app.destroy()

def test_bug_09_inline_edit_unbind(temp_env):
    """Test BUG-09 fix: inline edit unbinds handlers to prevent double invocation Tcl errors."""
    store = HistoryStore()
    store.add_to_history("127.0.0.1:28015", "Old Name")

    app = MainWindow(history_mgr=store)
    app.withdraw()

    app.refresh_history_ui()
    children = app.history_scroll.winfo_children()
    assert len(children) > 0

    frame = children[0]
    btn = frame.winfo_children()[0]

    # Trigger inline edit
    save_cb = app.start_inline_edit(frame, btn, "127.0.0.1:28015", "Old Name")

    # Verify entry created
    entry_widget = None
    for w in frame.winfo_children():
        if hasattr(w, "get"):
            entry_widget = w
            break

    assert entry_widget is not None
    entry_widget.delete(0, "end")
    entry_widget.insert(0, "New Name")

    # Call save_cb (simulating Return or FocusOut)
    save_cb()
    # Call save_cb a second time (simulating double invocation event)
    save_cb()

    assert store.get_history()[0]["name"] == "New Name"

    if app._search_timer:
        app.after_cancel(app._search_timer)
    app.destroy()

def test_bug_01_reconnect_finally_cleanup(temp_env):
    """Test BUG-01 fix: run_logic resets is_reconnecting = False in finally block."""
    app = AppController()
    app.withdraw()

    app.is_reconnecting = True

    # Call run_logic with invalid target string to trigger early return
    app.run_logic("invalid_target_no_colon")

    # Verify is_reconnecting was set back to False by finally block
    assert app.is_reconnecting is False

    if app._search_timer:
        app.after_cancel(app._search_timer)
    app.destroy()

def test_bug_04_graceful_shutdown(temp_env):
    """Test BUG-04 fix: system tray quit uses graceful shutdown instead of abrupt os._exit(0)."""
    app = AppController()
    app.withdraw()

    app.is_polling = True

    # Call quit_window (which schedules shutdown on main thread)
    app.quit_window()
    app.update()

    assert app.is_polling is False
