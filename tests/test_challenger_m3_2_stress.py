"""Empirical Adversarial Stress Tests for Milestone 3 (GUI, State Machine & Lifecycle Hardening).

Challenger: challenger_m3_2
Target Subsystems & Bug Fixes:
1. MainWindow._hide_server_card: Grab release order, sequential/concurrent hide cycles, TclError resilience, idempotence.
2. HistoryStore.set_armed_server: Force arming persistence, concurrency stress, log watcher integration, no accidental toggle-off.
3. MainWindow.shutdown: Pystray tray icon termination, timer cancellation, exception resilience, clean teardown.
4. MainWindow._show_telegram_link_overlay: Modal focus_set(), Escape key binding, rapid open/close lifecycle, error handling.
5. AppController Dialog Anchoring: parent=self propagation across benchmark confirmation, Rust folder selection, config backups.
"""

from collections import defaultdict
import copy
import os
import threading
import time
import tkinter as tk
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call
import pytest

from src.core.config import AppConfig
from src.core.history_store import HistoryStore
from src.gui.main_window import MainWindow
from src.app import AppController


def make_test_history_store(monkeypatch, tmp_path):
    monkeypatch.setattr(AppConfig, "appdata_dir", property(lambda self: tmp_path))
    monkeypatch.setattr(AppConfig, "data_file", property(lambda self: tmp_path / "data.json"))
    return HistoryStore()


# ============================================================================
# Dimension 1: Server Card Modal Grab Release & Teardown Stress
# ============================================================================

class TestServerCardGrabReleaseStress:
    """Adversarial stress testing for _hide_server_card and show_server_card modal grab lifecycle."""

    def test_grab_release_strictly_precedes_card_and_overlay_destroy(self):
        """Verify grab_release() is strictly called before card.destroy() and overlay.destroy()."""
        window = object.__new__(MainWindow)
        mock_card = MagicMock()
        mock_card.winfo_exists.return_value = True
        mock_overlay = MagicMock()
        mock_overlay.winfo_exists.return_value = True

        window._server_card_window = mock_card
        window._server_card_overlay = mock_overlay
        window._server_card_escape_id = "escape_123"
        window._selected_server_endpoint = "127.0.0.1:28015"
        window._selected_server_snapshot = SimpleNamespace(name="Rust Server")
        window.unbind = MagicMock()

        execution_log = []
        mock_card.grab_release.side_effect = lambda: execution_log.append("grab_release")
        mock_card.destroy.side_effect = lambda: execution_log.append("card_destroy")
        mock_overlay.destroy.side_effect = lambda: execution_log.append("overlay_destroy")

        MainWindow._hide_server_card(window, clear_selection=True)

        window.unbind.assert_called_once_with("<Escape>", "escape_123")
        assert execution_log == ["grab_release", "card_destroy", "overlay_destroy"]
        assert window._server_card_window is None
        assert window._server_card_overlay is None
        assert window._server_card_escape_id is None
        assert window._selected_server_endpoint is None
        assert window._selected_server_snapshot is None

    def test_hide_server_card_preserves_selection_when_clear_selection_false(self):
        """Verify clear_selection=False preserves selected endpoint and snapshot while tearing down card."""
        window = object.__new__(MainWindow)
        mock_card = MagicMock()
        mock_card.winfo_exists.return_value = True
        mock_overlay = MagicMock()
        mock_overlay.winfo_exists.return_value = True

        snapshot = SimpleNamespace(name="Preserved Snapshot")
        window._server_card_window = mock_card
        window._server_card_overlay = mock_overlay
        window._server_card_escape_id = None
        window._selected_server_endpoint = "10.0.0.1:28015"
        window._selected_server_snapshot = snapshot

        MainWindow._hide_server_card(window, clear_selection=False)

        assert window._selected_server_endpoint == "10.0.0.1:28015"
        assert window._selected_server_snapshot is snapshot
        assert window._server_card_window is None
        assert window._server_card_overlay is None
        mock_card.grab_release.assert_called_once()
        mock_card.destroy.assert_called_once()
        mock_overlay.destroy.assert_called_once()

    def test_rapid_sequential_100_open_hide_cycles(self):
        """Stress test 100 rapid sequential show_server_card / _hide_server_card cycles."""
        window = object.__new__(MainWindow)
        window.history_store = MagicMock()
        window.history_store.get_history.return_value = []
        window.unbind = MagicMock()
        window.bind = MagicMock(return_value="esc_id")
        window._icon_images = defaultdict(MagicMock)
        window._copy_server_card_text = MagicMock()
        window._open_server_card_url = MagicMock()
        window.hide_server_card = lambda: MainWindow.hide_server_card(window)

        grab_release_count = 0
        card_destroy_count = 0
        overlay_destroy_count = 0

        with patch("src.gui.main_window._get_server_metadata", return_value={}), \
             patch("src.gui.main_window._generate_rust_sunset_banner"), \
             patch("src.gui.main_window.ctk.CTkImage"), \
             patch("src.gui.main_window.ctk.CTkFrame") as mock_frame_cls, \
             patch("src.gui.main_window.ctk.CTkLabel"), \
             patch("src.gui.main_window.ctk.CTkButton"), \
             patch("src.gui.main_window.ctk.CTkFont"):

            for i in range(100):
                mock_overlay = MagicMock()
                mock_card = MagicMock()
                mock_overlay.winfo_exists.return_value = True
                mock_card.winfo_exists.return_value = True

                def on_grab():
                    nonlocal grab_release_count
                    grab_release_count += 1

                def on_card_destroy():
                    nonlocal card_destroy_count
                    card_destroy_count += 1

                def on_overlay_destroy():
                    nonlocal overlay_destroy_count
                    overlay_destroy_count += 1

                mock_card.grab_release.side_effect = on_grab
                mock_card.destroy.side_effect = on_card_destroy
                mock_overlay.destroy.side_effect = on_overlay_destroy

                frame_call_index = 0
                def frame_factory(*args, **kwargs):
                    nonlocal frame_call_index
                    frame_call_index += 1
                    if frame_call_index == 1:
                        return mock_overlay
                    elif frame_call_index == 2:
                        return mock_card
                    else:
                        return MagicMock()

                mock_frame_cls.side_effect = frame_factory

                # Open card
                MainWindow.show_server_card(window, f"192.168.1.{i}:28015")
                assert window._server_card_window is mock_card
                assert window._server_card_overlay is mock_overlay

                # Hide card
                MainWindow._hide_server_card(window, clear_selection=True)
                assert window._server_card_window is None
                assert window._server_card_overlay is None

            assert grab_release_count == 100
            assert card_destroy_count == 100
            assert overlay_destroy_count == 100

    def test_double_hide_idempotence_stress(self):
        """Stress test calling _hide_server_card repeatedly (50 consecutive calls)."""
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

        # First call destroys and releases grab
        MainWindow._hide_server_card(window, clear_selection=True)
        assert mock_card.grab_release.call_count == 1
        assert mock_card.destroy.call_count == 1

        # Subsequent 50 calls must be completely no-op and never raise
        for _ in range(50):
            MainWindow._hide_server_card(window, clear_selection=True)

        assert mock_card.grab_release.call_count == 1
        assert mock_card.destroy.call_count == 1
        assert window._server_card_window is None
        assert window._server_card_overlay is None

    def test_tcl_error_resilience_during_grab_release_and_destroy(self):
        """Verify _hide_server_card catches tk.TclError and safely nulls references."""
        window = object.__new__(MainWindow)
        mock_card = MagicMock()
        mock_card.winfo_exists.return_value = True
        mock_card.grab_release.side_effect = tk.TclError("grab release failed - window dead")
        mock_overlay = MagicMock()
        mock_overlay.winfo_exists.return_value = True
        mock_overlay.destroy.side_effect = tk.TclError("overlay destroy failed")

        window._server_card_window = mock_card
        window._server_card_overlay = mock_overlay
        window._server_card_escape_id = "escape_test"
        window._selected_server_endpoint = "127.0.0.1:28015"
        window._selected_server_snapshot = object()
        window.unbind = MagicMock(side_effect=Exception("unbind failed"))

        # Should not raise any exception
        MainWindow._hide_server_card(window, clear_selection=True)

        assert window._server_card_window is None
        assert window._server_card_overlay is None
        assert window._server_card_escape_id is None
        assert window._selected_server_endpoint is None
        assert window._selected_server_snapshot is None


# ============================================================================
# Dimension 2: HistoryStore.set_armed_server Force Arming & State Machine Stress
# ============================================================================

class TestHistoryStoreArmedServerStress:
    """Stress tests for HistoryStore.set_armed_server with force=True vs force=False."""

    def test_repeated_reconnection_same_server_retains_armed_state(self, monkeypatch, tmp_path):
        """Stress test 200 consecutive set_armed_server calls with force=True on same IP."""
        store = make_test_history_store(monkeypatch, tmp_path)
        server_ip = "192.168.1.50:28015"

        for i in range(200):
            store.set_armed_server(server_ip, force=True)
            assert store.get_armed_server() == server_ip, f"Failed at iteration {i}: armed server was reset!"

    def test_force_true_vs_force_false_behavior_contrast(self, monkeypatch, tmp_path):
        """Verify strict distinction: force=False toggles on/off, force=True stays on."""
        store = make_test_history_store(monkeypatch, tmp_path)
        target = "10.0.0.5:28015"

        # force=True: idempotence
        store.set_armed_server(target, force=True)
        assert store.get_armed_server() == target
        store.set_armed_server(target, force=True)
        assert store.get_armed_server() == target

        # force=False: toggle off
        store.set_armed_server(target, force=False)
        assert store.get_armed_server() == ""

        # force=False: toggle on
        store.set_armed_server(target, force=False)
        assert store.get_armed_server() == target

    def test_concurrent_multithreaded_force_arming_stress(self, monkeypatch, tmp_path):
        """Stress test 20 threads hammering set_armed_server concurrently."""
        store = make_test_history_store(monkeypatch, tmp_path)
        errors = []

        def worker(thread_id):
            ip = f"172.16.0.{thread_id % 5}:28015"
            try:
                for _ in range(30):
                    store.set_armed_server(ip, force=True)
                    current = store.get_armed_server()
                    # Current armed server must be one of the valid IPs, never corrupted
                    if not current.startswith("172.16.0."):
                        errors.append(f"Invalid armed server: {current}")
                    time.sleep(0.001)
            except Exception as exc:
                errors.append(str(exc))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrency errors encountered: {errors}"
        final_armed = store.get_armed_server()
        assert final_armed.startswith("172.16.0.")

    def test_log_watcher_event_stream_force_arm_integration(self, monkeypatch, tmp_path):
        """Simulate 50 rapid log watcher connect events and ensure armed state never drops."""
        controller = object.__new__(AppController)
        controller.history_store = make_test_history_store(monkeypatch, tmp_path)
        controller.history_store.set_auto_arm(True)
        controller.history_store.set_armed_server("127.0.0.1:28015", force=True)

        controller.refresh_history_ui = MagicMock()
        controller._refresh_session_state_once = MagicMock()
        controller.log_safe = MagicMock()
        controller.t = lambda key, **kwargs: key
        controller.dispatch_ui = lambda callback, *args, **kwargs: callback(*args) if callable(callback) else None
        controller.async_loop = MagicMock()
        controller._state_lock = threading.Lock()
        controller._is_polling = False
        controller._active_session = None

        with patch("src.app.LogWatcher") as mock_watcher_cls:
            AppController._start_global_log_watcher(controller)
            handle_event = mock_watcher_cls.call_args[1]["on_event"]

            for i in range(50):
                if i % 2 == 0:
                    handle_event("Connecting to 127.0.0.1:28015")
                else:
                    handle_event("Client connected to 127.0.0.1:28015")

                assert controller.history_store.get_armed_server() == "127.0.0.1:28015"

    def test_set_armed_server_none_or_empty_clears_armed_server(self, monkeypatch, tmp_path):
        """Verify setting None or empty string with force=True resets armed server to empty string."""
        store = make_test_history_store(monkeypatch, tmp_path)
        store.set_armed_server("127.0.0.1:28015", force=True)
        assert store.get_armed_server() == "127.0.0.1:28015"

        store.set_armed_server(None, force=True)
        assert store.get_armed_server() == ""

        store.set_armed_server("127.0.0.1:28015", force=True)
        store.set_armed_server("", force=True)
        assert store.get_armed_server() == ""


# ============================================================================
# Dimension 3: MainWindow.shutdown Pystray & Timer Lifecycle Stress
# ============================================================================

class TestMainWindowShutdownStress:
    """Stress tests for MainWindow.shutdown lifecycle, pystray icon stop, and timer cleanup."""

    def test_shutdown_cancels_all_active_timers_and_stops_tray(self):
        """Verify shutdown cancels all 4 timer handles and terminates tray icon."""
        window = object.__new__(MainWindow)
        mock_tray = MagicMock()
        window.tray_icon = mock_tray
        window._ui_dispatch_closing = False
        window._ui_dispatch_after_id = "after_dispatch_1"
        window._search_timer = "after_search_2"
        window._session_state_after_id = "after_session_3"
        window._drawer_animation_id = "after_drawer_4"
        window.after_cancel = MagicMock()
        window.destroy = MagicMock()

        MainWindow.shutdown(window)

        assert window._ui_dispatch_closing is True
        mock_tray.stop.assert_called_once()
        assert window.tray_icon is None
        assert window._ui_dispatch_after_id is None
        assert window._search_timer is None
        assert window._session_state_after_id is None
        assert window._drawer_animation_id is None

        window.after_cancel.assert_has_calls([
            call("after_dispatch_1"),
            call("after_search_2"),
            call("after_session_3"),
            call("after_drawer_4"),
        ], any_order=True)
        window.destroy.assert_called_once()

    def test_shutdown_when_tray_icon_already_none(self):
        """Verify shutdown executes safely when tray_icon is None."""
        window = object.__new__(MainWindow)
        window.tray_icon = None
        window.after_cancel = MagicMock()
        window.destroy = MagicMock()

        MainWindow.shutdown(window)

        assert window._ui_dispatch_closing is True
        assert window.tray_icon is None
        window.destroy.assert_called_once()

    def test_shutdown_resilience_when_tray_stop_throws_exception(self):
        """Verify shutdown completes even if tray.stop() raises an error."""
        window = object.__new__(MainWindow)
        mock_tray = MagicMock()
        mock_tray.stop.side_effect = RuntimeError("Tray thread already dead")
        window.tray_icon = mock_tray
        window.after_cancel = MagicMock()
        window.destroy = MagicMock()

        MainWindow.shutdown(window)

        assert window.tray_icon is None
        window.destroy.assert_called_once()

    def test_shutdown_idempotence_10_sequential_calls(self):
        """Verify shutdown can be called multiple times without raising exceptions."""
        window = object.__new__(MainWindow)
        mock_tray = MagicMock()
        window.tray_icon = mock_tray
        window.after_cancel = MagicMock()
        window.destroy = MagicMock()

        for _ in range(10):
            MainWindow.shutdown(window)

        mock_tray.stop.assert_called_once()
        assert window.tray_icon is None
        assert window.destroy.call_count == 10


# ============================================================================
# Dimension 4: Telegram Link Overlay Modal & Keyboard Focus Stress
# ============================================================================

class TestTelegramLinkOverlayStress:
    """Stress tests for MainWindow._show_telegram_link_overlay focus and Escape dismiss."""

    def test_telegram_overlay_pairing_code_focus_and_escape_binding(self):
        """Verify focus_set() and <Escape> binding on valid link code overlay."""
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

            MainWindow._show_telegram_link_overlay(window, code="987654")

            assert window._tg_overlay is mock_overlay
            mock_overlay.focus_set.assert_called_once()
            mock_overlay.bind.assert_called_once()
            assert mock_overlay.bind.call_args[0][0] == "<Escape>"

    def test_telegram_overlay_error_mode_focus_and_escape_binding(self):
        """Verify focus_set() and <Escape> binding on error overlay."""
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

            MainWindow._show_telegram_link_overlay(window, error=True)

            assert window._tg_overlay is mock_overlay
            mock_overlay.focus_set.assert_called_once()
            mock_overlay.bind.assert_called_once()
            assert mock_overlay.bind.call_args[0][0] == "<Escape>"

    def test_telegram_overlay_50_rapid_open_escape_cycles(self):
        """Stress test 50 rapid open -> trigger Escape -> close cycles."""
        window = object.__new__(MainWindow)
        window.t = lambda key, **kwargs: key
        window._tg_overlay = None

        escape_dismiss_count = 0

        def mock_close():
            nonlocal escape_dismiss_count
            escape_dismiss_count += 1
            if window._tg_overlay is not None:
                window._tg_overlay.destroy()
                window._tg_overlay = None

        window._close_telegram_link_overlay = mock_close

        with patch("src.gui.main_window.ctk.CTkFont"), \
             patch("src.gui.main_window.ctk.CTkFrame") as mock_frame_cls, \
             patch("src.gui.main_window.ctk.CTkLabel"), \
             patch("src.gui.main_window.ctk.CTkButton"):

            for i in range(50):
                mock_overlay = MagicMock()
                mock_card = MagicMock()
                mock_overlay.winfo_exists.return_value = True

                escape_callbacks = {}
                mock_overlay.bind.side_effect = lambda event_str, cb: escape_callbacks.update({event_str: cb})
                mock_frame_cls.side_effect = [mock_overlay, mock_card]

                initial_close_count = escape_dismiss_count
                MainWindow._show_telegram_link_overlay(window, code=f"code_{i:04d}")
                # Showing overlay triggers initial _close_telegram_link_overlay to clean previous
                assert escape_dismiss_count == initial_close_count + 1
                assert window._tg_overlay is mock_overlay

                # Trigger the bound <Escape> handler
                assert "<Escape>" in escape_callbacks
                escape_callbacks["<Escape>"](None)
                assert escape_dismiss_count == initial_close_count + 2
                assert window._tg_overlay is None

            assert escape_dismiss_count == 100

    def test_telegram_overlay_focus_set_exception_resilience(self):
        """Verify _show_telegram_link_overlay does not crash if focus_set() raises."""
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
            mock_overlay.focus_set.side_effect = tk.TclError("cannot set focus: window not mapped")
            mock_frame_cls.side_effect = [mock_overlay, mock_card]

            # Should complete without error
            MainWindow._show_telegram_link_overlay(window, code="123456")
            assert window._tg_overlay is mock_overlay


# ============================================================================
# Dimension 5: AppController Dialog Parent Anchoring Stress
# ============================================================================

class TestAppControllerDialogParentStress:
    """Stress tests for parent=self propagation across all AppController dialogs."""

    def test_run_benchmark_dialog_flow_pass_parent(self):
        """Verify run_benchmark anchors all 3 dialog types (askyesno, askokcancel, askdirectory) to parent."""
        controller = object.__new__(AppController)
        controller.bench_btn = MagicMock()
        controller.process_monitor = MagicMock()
        controller.process_monitor.is_rust_running.return_value = True
        controller.t = lambda key, **kwargs: key
        controller.log_safe = MagicMock()
        controller.is_benchmarking = False
        controller._operation_lock = threading.Lock()
        controller._benchmark_operation = 0
        controller._benchmark_stop_event = threading.Event()
        controller.bench_log = MagicMock()

        with patch("tkinter.messagebox.askyesno", return_value=True) as mock_yesno, \
             patch("tkinter.messagebox.askokcancel", return_value=True) as mock_okcancel, \
             patch("src.core.history_store.history_store.get_rust_path", return_value=""), \
             patch("src.services.steam_service.find_rust_install_path", return_value=""), \
             patch("tkinter.filedialog.askdirectory", return_value="C:\\Rust") as mock_askdir, \
             patch("src.core.history_store.history_store.set_rust_path") as mock_set_path, \
             patch("threading.Thread") as mock_thread_cls:

            AppController.run_benchmark(controller)

            assert mock_yesno.call_args[1].get("parent") == controller
            assert mock_okcancel.call_args[1].get("parent") == controller
            assert mock_askdir.call_args[1].get("parent") == controller
            mock_set_path.assert_called_with("C:\\Rust")

    def test_run_benchmark_abort_scenarios_clean_exit(self):
        """Test user abortion at each dialog step restores UI state cleanly."""
        controller = object.__new__(AppController)
        controller.bench_btn = MagicMock()
        controller.process_monitor = MagicMock()
        controller.t = lambda key, **kwargs: key
        controller.log_safe = MagicMock()
        controller.is_benchmarking = False

        # Scenario 1: User says NO to killing Rust
        controller.process_monitor.is_rust_running.return_value = True
        with patch("tkinter.messagebox.askyesno", return_value=False) as mock_yesno:
            AppController.run_benchmark(controller)
            assert mock_yesno.call_args[1].get("parent") == controller
            controller.bench_btn.configure.assert_called_with(state="normal")
            assert controller.is_benchmarking is False

        # Scenario 2: User cancels instruction dialog
        controller.process_monitor.is_rust_running.return_value = False
        controller.bench_btn.reset_mock()
        with patch("tkinter.messagebox.askokcancel", return_value=False) as mock_okcancel:
            AppController.run_benchmark(controller)
            assert mock_okcancel.call_args[1].get("parent") == controller
            controller.bench_btn.configure.assert_called_with(state="normal")
            assert controller.is_benchmarking is False

        # Scenario 3: User cancels folder browser dialog
        controller.bench_btn.reset_mock()
        with patch("tkinter.messagebox.askokcancel", return_value=True), \
             patch("src.core.history_store.history_store.get_rust_path", return_value=""), \
             patch("src.services.steam_service.find_rust_install_path", return_value=""), \
             patch("tkinter.filedialog.askdirectory", return_value="") as mock_askdir:
            AppController.run_benchmark(controller)
            assert mock_askdir.call_args[1].get("parent") == controller
            assert controller.is_benchmarking is False

    def test_save_user_config_all_error_and_success_dialogs_anchored(self):
        """Verify save_user_config anchors showerror and showinfo dialogs with parent=self."""
        controller = object.__new__(AppController)
        controller.t = lambda key, **kwargs: key

        # Case 1: No rust path -> showerror
        with patch("src.core.history_store.history_store.get_rust_path", return_value=""), \
             patch("tkinter.messagebox.showerror") as mock_err:
            AppController.save_user_config(controller)
            mock_err.assert_called_once_with("error_title", "rust_path_not_found_err", parent=controller)

        # Case 2: Rust path exists, but no cfg folder -> showerror
        with patch("src.core.history_store.history_store.get_rust_path", return_value="C:\\FakeRust"), \
             patch("os.path.exists", side_effect=lambda p: p == "C:\\FakeRust"), \
             patch("tkinter.messagebox.showerror") as mock_err:
            AppController.save_user_config(controller)
            mock_err.assert_called_once_with("error_title", "no_cfg_folder_err", parent=controller)

        # Case 3: Success -> showinfo
        with patch("src.core.history_store.history_store.get_rust_path", return_value="C:\\FakeRust"), \
             patch("os.path.exists", return_value=True), \
             patch("shutil.copytree"), \
             patch("tkinter.messagebox.showinfo") as mock_info:
            AppController.save_user_config(controller)
            assert mock_info.called
            assert mock_info.call_args[1].get("parent") == controller

        # Case 4: copytree raises exception -> showerror
        with patch("src.core.history_store.history_store.get_rust_path", return_value="C:\\FakeRust"), \
             patch("os.path.exists", return_value=True), \
             patch("shutil.copytree", side_effect=PermissionError("Access denied")), \
             patch("tkinter.messagebox.showerror") as mock_err:
            AppController.save_user_config(controller)
            assert mock_err.called
            assert mock_err.call_args[1].get("parent") == controller
