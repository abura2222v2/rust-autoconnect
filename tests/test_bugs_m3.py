"""Tests for Milestone 3 (Codebase Bug Hunt & Subsystem Hardening).

Verifies all 10 bug fixes:
1. Asynchronous Telegram link code generation in MainWindow._on_tg_link_click.
2. Server card modal grab release before destroy in MainWindow._hide_server_card.
3. Clean pystray icon termination in MainWindow.shutdown().
4. Focus set on Telegram link overlay in MainWindow._show_telegram_link_overlay.
5. Force arming in AppController log watcher on connect event (no accidental toggle-off).
6. Modal dialogs and filedialogs anchored to parent in AppController.
7. Phoenix channel phx_leave sent before phx_join when switching rooms in SwarmService.
8. Event loop safety in A2SClient.get_rustmaps_url when running inside an existing loop.
9. Null/None safety for float conversions in LeaderboardWindow._show_detail.
10. Case-insensitive process matching in ProcessMonitor for RustClient.exe.
"""

import asyncio
import json
import threading
import time
from unittest.mock import MagicMock, patch, call
import pytest

from src.core.config import AppConfig
from src.core.a2s_client import A2SClient
from src.core.history_store import HistoryStore
from src.services.process_monitor import ProcessMonitor
from src.services.swarm_service import SwarmService
from src.gui.main_window import MainWindow
from src.gui.leaderboard_window import LeaderboardWindow
from src.app import AppController


def make_test_history_store(monkeypatch, tmp_path):
    monkeypatch.setattr(AppConfig, "appdata_dir", property(lambda self: tmp_path))
    monkeypatch.setattr(AppConfig, "data_file", property(lambda self: tmp_path / "data.json"))
    return HistoryStore()


# ============================================================================
# Bug 1: MainWindow._on_tg_link_click asynchronous dispatch
# ============================================================================

def test_telegram_link_click_dispatches_on_background_thread():
    """Verify _on_tg_link_click spawns a background thread and does not block."""
    window = object.__new__(MainWindow)
    window.lang = "en"
    window.t = lambda key, **kwargs: key
    window.tg_link_btn = MagicMock()
    window.tg_status_lbl = MagicMock()
    window.dispatch_ui = MagicMock()
    window._finish_telegram_link = MagicMock()

    with patch("src.gui.main_window.telegram_service.generate_link_code", return_value="123456") as mock_gen:
        MainWindow._on_tg_link_click(window)

        # Allow daemon thread to run
        time.sleep(0.1)

        window.tg_link_btn.configure.assert_called_with(state="disabled", text="tg_status_pairing")
        window.tg_status_lbl.configure.assert_called_with(text="tg_status_pairing")
        mock_gen.assert_called_once_with("en")
        window.dispatch_ui.assert_called_once_with(window._finish_telegram_link, "123456")


def test_telegram_link_finish_handles_error_and_success():
    """Verify _finish_telegram_link updates overlay and controls appropriately."""
    window = object.__new__(MainWindow)
    window.t = lambda key, **kwargs: key
    window.winfo_exists = MagicMock(return_value=True)
    window._refresh_telegram_controls = MagicMock()
    window._show_telegram_link_overlay = MagicMock()
    window._telegram_status_text = MagicMock(return_value="Unlinked")
    window.tg_status_lbl = MagicMock()

    # Case 1: Error (None code)
    MainWindow._finish_telegram_link(window, None)
    window._refresh_telegram_controls.assert_called_once()
    window._show_telegram_link_overlay.assert_called_once_with(error=True)
    window.tg_status_lbl.configure.assert_called_with(text="Unlinked")

    # Case 2: Success (valid code)
    window._refresh_telegram_controls.reset_mock()
    window._show_telegram_link_overlay.reset_mock()
    window.tg_status_lbl.reset_mock()

    MainWindow._finish_telegram_link(window, "999888")
    window._refresh_telegram_controls.assert_called_once()
    window.tg_status_lbl.configure.assert_called_with(text="tg_status_pairing")
    window._show_telegram_link_overlay.assert_called_once_with(code="999888")


# ============================================================================
# Bug 2: Server Card grab_release before destroy in _hide_server_card
# ============================================================================

def test_hide_server_card_releases_grab_before_destroy():
    """Verify card.grab_release() is called before card.destroy() when hiding."""
    window = object.__new__(MainWindow)
    mock_card = MagicMock()
    mock_card.winfo_exists.return_value = True
    mock_overlay = MagicMock()
    mock_overlay.winfo_exists.return_value = True

    window._server_card_window = mock_card
    window._server_card_overlay = mock_overlay
    window._server_card_escape_id = None
    window._selected_server_endpoint = "127.0.0.1:28015"
    window._selected_server_snapshot = object()

    call_order = []
    mock_card.grab_release.side_effect = lambda: call_order.append("grab_release")
    mock_card.destroy.side_effect = lambda: call_order.append("card_destroy")
    mock_overlay.destroy.side_effect = lambda: call_order.append("overlay_destroy")

    MainWindow._hide_server_card(window, clear_selection=True)

    assert window._server_card_window is None
    assert window._server_card_overlay is None
    assert window._selected_server_endpoint is None
    assert window._selected_server_snapshot is None

    assert call_order == ["grab_release", "card_destroy", "overlay_destroy"]


# ============================================================================
# Bug 3: Clean pystray icon termination in MainWindow.shutdown()
# ============================================================================

def test_shutdown_stops_pystray_tray_icon():
    """Verify MainWindow.shutdown() calls tray_icon.stop() cleanly."""
    window = object.__new__(MainWindow)
    mock_tray = MagicMock()
    window.tray_icon = mock_tray
    window.destroy = MagicMock()

    MainWindow.shutdown(window)

    mock_tray.stop.assert_called_once()
    assert window.tray_icon is None
    window.destroy.assert_called_once()


# ============================================================================
# Bug 4: Focus set on Telegram link overlay in MainWindow
# ============================================================================

def test_telegram_link_overlay_sets_keyboard_focus():
    """Verify overlay.focus_set() is called so Escape key works immediately."""
    window = object.__new__(MainWindow)
    window.t = lambda key, **kwargs: key
    window._close_telegram_link_overlay = MagicMock()
    window._tg_overlay = None

    with patch("src.gui.main_window.ctk.CTkFont"), \
         patch("src.gui.main_window.ctk.CTkFrame") as mock_frame_cls, \
         patch("src.gui.main_window.ctk.CTkLabel"), \
         patch("src.gui.main_window.ctk.CTkButton"):
        
        mock_overlay = MagicMock()
        mock_card = MagicMock()
        mock_frame_cls.side_effect = [mock_overlay, mock_card]

        MainWindow._show_telegram_link_overlay(window, code="123456")

        mock_overlay.focus_set.assert_called_once()
        assert mock_overlay.bind.called


# ============================================================================
# Bug 5: Force arming on log watcher connect event (no accidental toggle-off)
# ============================================================================

def test_history_store_set_armed_server_force_flag(monkeypatch, tmp_path):
    """Verify HistoryStore.set_armed_server with force=True does not toggle off."""
    store = make_test_history_store(monkeypatch, tmp_path)

    # Initially empty
    assert store.get_armed_server() == ""

    # Set server
    store.set_armed_server("127.0.0.1:28015", force=True)
    assert store.get_armed_server() == "127.0.0.1:28015"

    # Calling with force=True again must KEEP the armed server, NOT toggle off
    store.set_armed_server("127.0.0.1:28015", force=True)
    assert store.get_armed_server() == "127.0.0.1:28015"

    # Calling without force toggles it off
    store.set_armed_server("127.0.0.1:28015", force=False)
    assert store.get_armed_server() == ""


def test_app_log_watcher_event_uses_force_arm(monkeypatch, tmp_path):
    """Verify log watcher event handler sets armed server with force=True."""
    controller = object.__new__(AppController)
    controller.history_store = make_test_history_store(monkeypatch, tmp_path)
    controller.history_store.set_auto_arm(True)
    controller.history_store.set_armed_server("127.0.0.1:28015", force=True)

    controller.refresh_history_ui = MagicMock()
    controller._refresh_session_state_once = MagicMock()
    controller.log_safe = MagicMock()
    controller.t = lambda key, **kwargs: key
    controller.dispatch_ui = lambda callback, *args, **kwargs: callback(*args)
    controller.async_loop = MagicMock()
    controller._state_lock = threading.Lock()
    controller._is_polling = False
    controller._active_session = None

    # Simulate running global log watcher handle_event
    with patch("src.app.LogWatcher") as mock_watcher_cls:
        AppController._start_global_log_watcher(controller)
        assert mock_watcher_cls.called
        handle_event = mock_watcher_cls.call_args[1]["on_event"]

        # Log event for connecting to the already-armed server
        handle_event("Connecting to 127.0.0.1:28015")

        # Must still be armed, NOT toggled to ""
        assert controller.history_store.get_armed_server() == "127.0.0.1:28015"


# ============================================================================
# Bug 6: Modal dialogs anchored with parent=self in AppController
# ============================================================================

def test_run_benchmark_passes_parent_to_messagebox_and_filedialog():
    """Verify run_benchmark anchors messageboxes and filedialog to parent."""
    controller = object.__new__(AppController)
    controller.bench_btn = MagicMock()
    controller.process_monitor = MagicMock()
    controller.process_monitor.is_rust_running.return_value = True
    controller.t = lambda key, **kwargs: key
    controller.log_safe = MagicMock()
    controller.is_benchmarking = False
    controller._operation_lock = threading.Lock()
    controller._benchmark_operation = 1
    controller._benchmark_stop_event = threading.Event()
    controller.bench_log = MagicMock()

    with patch("tkinter.messagebox.askyesno", return_value=True) as mock_yesno, \
         patch("tkinter.messagebox.askokcancel", return_value=True) as mock_okcancel, \
         patch("src.core.history_store.history_store.get_rust_path", return_value=""), \
         patch("src.services.steam_service.find_rust_install_path", return_value=""), \
         patch("tkinter.filedialog.askdirectory", return_value="") as mock_askdir:

        AppController.run_benchmark(controller)

        mock_yesno.assert_called_once_with("close_rust_title", "bench_warn_running", parent=controller)
        mock_okcancel.assert_called_once()
        assert mock_okcancel.call_args[1].get("parent") == controller
        mock_askdir.assert_called_once_with(title="select_rust_folder_title", parent=controller)


def test_save_user_config_passes_parent_to_messagebox():
    """Verify save_user_config anchors messagebox to parent window."""
    controller = object.__new__(AppController)
    controller.t = lambda key, **kwargs: key

    with patch("src.core.history_store.history_store.get_rust_path", return_value=""), \
         patch("tkinter.messagebox.showerror") as mock_err:

        AppController.save_user_config(controller)

        mock_err.assert_called_once_with("error_title", "rust_path_not_found_err", parent=controller)


# ============================================================================
# Bug 7: Phoenix channel phx_leave on room switch in SwarmService
# ============================================================================

def test_swarm_join_room_sends_phx_leave_before_phx_join_on_room_switch():
    """Verify switching rooms leaves the previous room channel to prevent topic leaks."""
    service = SwarmService()
    service.is_enabled = True
    service.is_connected = True
    mock_ws = MagicMock()
    service.ws = mock_ws

    sent_messages = []
    mock_ws.send.side_effect = lambda msg: sent_messages.append(json.loads(msg))

    # First join
    service.join_room("127.0.0.1:28015")
    assert service.current_room == "realtime:room_127_0_0_1_28015"
    assert any(m.get("event") == "phx_join" and m.get("topic") == "realtime:room_127_0_0_1_28015" for m in sent_messages)

    sent_messages.clear()

    # Second join to a different room
    service.join_room("192.168.1.100:28016")

    # Must first have sent phx_leave for the old topic, then phx_join for the new topic
    events = [(m.get("event"), m.get("topic")) for m in sent_messages]
    assert ("phx_leave", "realtime:room_127_0_0_1_28015") in events
    assert ("phx_join", "realtime:room_192_168_1_100_28016") in events

    # Leave must come before join
    leave_idx = events.index(("phx_leave", "realtime:room_127_0_0_1_28015"))
    join_idx = events.index(("phx_join", "realtime:room_192_168_1_100_28016"))
    assert leave_idx < join_idx


# ============================================================================
# Bug 8: A2SClient.get_rustmaps_url running loop safety
# ============================================================================

def test_get_rustmaps_url_safe_inside_running_asyncio_loop():
    """Verify get_rustmaps_url works safely inside a thread with an existing running event loop."""
    client = A2SClient()

    async def run_in_async_context():
        # Inside an active asyncio loop, calling get_rustmaps_url should use ThreadPoolExecutor without raising RuntimeError
        with patch.object(client, "_get_rustmaps_url_async", return_value="https://rustmaps.com/map/1234567890abcdef1234567890abcdef"):
            url = client.get_rustmaps_url("127.0.0.1", 28015)
            return url

    result = asyncio.run(run_in_async_context())
    assert result == "https://rustmaps.com/map/1234567890abcdef1234567890abcdef"


# ============================================================================
# Bug 9: Leaderboard detail popup null/None float conversion safety
# ============================================================================

def test_leaderboard_show_detail_handles_null_fields_safely():
    """Verify _show_detail does not raise TypeError when backend returns null/None for statistics."""
    window = object.__new__(LeaderboardWindow)
    window.winfo_exists = MagicMock(return_value=True)
    window.parent = MagicMock()
    window.parent.t = lambda key, **kwargs: key

    detail_with_nulls = {
        "summary": {
            "median_total_time": None,
            "installation_count": None,
            "run_count": None,
            "min_total_time": None,
            "max_total_time": None,
        },
        "installations": [
            {
                "median_total_time": None,
                "run_count": None,
            }
        ]
    }

    with patch("src.gui.leaderboard_window.ctk.CTkFont"), \
         patch("src.gui.leaderboard_window.ctk.CTkToplevel") as mock_top, \
         patch("src.gui.leaderboard_window.ctk.CTkLabel") as mock_label, \
         patch("src.gui.leaderboard_window.ctk.CTkScrollableFrame"):

        # Should execute without raising TypeError
        LeaderboardWindow._show_detail(window, detail_with_nulls)
        assert mock_top.called
        assert mock_label.called


# ============================================================================
# Bug 10: ProcessMonitor case-insensitive matching for Windows
# ============================================================================

def test_process_monitor_case_insensitive_matching():
    """Verify ProcessMonitor matches rustclient.exe regardless of case."""
    monitor = ProcessMonitor()

    mock_proc_lower = MagicMock()
    mock_proc_lower.name.return_value = "rustclient.exe"
    mock_proc_lower.pid = 1234
    mock_proc_lower.info = {"name": "rustclient.exe"}

    mock_proc_upper = MagicMock()
    mock_proc_upper.name.return_value = "RUSTCLIENT.EXE"
    mock_proc_upper.pid = 5678
    mock_proc_upper.info = {"name": "RUSTCLIENT.EXE"}

    # Test is_rust_running slow path
    with patch("psutil.process_iter", return_value=[mock_proc_lower]):
        assert monitor.is_rust_running() is True
        assert monitor.cached_pid == 1234

    monitor.cached_pid = None
    monitor._last_scan_time = 0.0

    with patch("psutil.process_iter", return_value=[mock_proc_upper]):
        assert monitor.is_rust_running() is True
        assert monitor.cached_pid == 5678

    # Test get_rust_pids
    with patch("psutil.process_iter", return_value=[mock_proc_lower, mock_proc_upper]):
        pids = monitor.get_rust_pids()
        assert pids == {1234, 5678}
