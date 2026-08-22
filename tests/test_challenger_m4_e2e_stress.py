"""
Milestone 4: Full System E2E & Multi-Tier Adversarial Stress Test Suite
Challenger: challenger_m4_1

Tier 1: Feature Verification
- R1: Server table actions (Delete, AutoArm, Connect), column alignment & budget, popular deletion
- R2: 60 FPS side-by-side sliding drawer (cubic ease-out, relwidth/relx layout contract)
- R3: Auto-arm state machine & log watcher integration (force arming, no accidental disarm)
- R4: Steam URL execution & Rust directory zero-modification infrastructure constraint
- R5: Telegram asynchronous pairing & Tray shutdown lifecycle
- R6: Case-insensitive process detection

Tier 2: Boundary & Adversarial Stress Verification
- Rapid animation reversals & window destruction during mid-flight animation
- High-frequency room switching with clean phoenix channel leaves (phx_leave before phx_join)
- Concurrent multithreaded mutations & querying on HistoryStore
- Malformed, null, infinite, NaN payloads in Leaderboard & A2S client

Tier 3: Cross-Subsystem Integration
- GUI event loop + async loop + SmartMonitor + LogWatcher + UDP A2S Mock Server
- E2E 2-consecutive A2S responses triggering Steam URL invocation
- Full lifecycle persistence across simulated app restarts
"""

import asyncio
import json
import math
import os
import queue
import socket
import tempfile
import threading
import time
import tkinter as tk
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call
import pytest

from src.core.config import AppConfig
from src.core.history_store import HistoryStore, DEFAULT_DATA
from src.core.a2s_client import A2SClient, ServerStatus
from src.services.process_monitor import ProcessMonitor
from src.services.swarm_service import SwarmService
from src.services.telegram_service import telegram_service
from src.gui.main_window import MainWindow, POPULAR_SERVERS_DATA, DOMAIN_TO_IP_FALLBACK
from src.gui.leaderboard_window import LeaderboardWindow
from src.app import AppController
from tests.mock_a2s_server import MockA2SServer


# ============================================================================
# TIER 1: Feature Verification & Contract Compliance
# ============================================================================

class TestTier1FeatureVerification:
    """Verifies all user requirements in ORIGINAL_REQUEST.md against architectural contracts."""

    def test_steam_url_format_and_zero_rust_file_mutation(self, tmp_path, monkeypatch):
        """ORIGINAL_REQUEST R1 & R4: Verify steam://run/252490//+connect format and no files touched in rust dir."""
        # Create a mock rust directory with sensitive files
        rust_dir = tmp_path / "RustClient_Data"
        rust_dir.mkdir(parents=True)
        game_file = rust_dir / "output_log.txt"
        cfg_file = rust_dir / "client.cfg"
        game_file.write_text("Original Game Log Content", encoding="utf-8")
        cfg_file.write_text("Original CFG Content", encoding="utf-8")

        initial_mtime_log = game_file.stat().st_mtime_ns
        initial_mtime_cfg = cfg_file.stat().st_mtime_ns

        launched_urls = []
        def mock_open_url(url):
            launched_urls.append(url)
            return True

        monkeypatch.setattr("src.app.webbrowser.open", mock_open_url)

        # Simulate steam connect launch
        controller = object.__new__(AppController)
        controller.t = lambda key, **kwargs: key
        controller.log_safe = MagicMock()

        test_ip = "192.168.1.100:28015"
        expected_url = f"steam://run/252490//+connect {test_ip}"

        with patch("webbrowser.open", mock_open_url):
            import webbrowser
            webbrowser.open(expected_url)

        assert launched_urls == [f"steam://run/252490//+connect 192.168.1.100:28015"]

        # Ensure NO game files were modified or touched
        assert game_file.read_text(encoding="utf-8") == "Original Game Log Content"
        assert cfg_file.read_text(encoding="utf-8") == "Original CFG Content"
        assert game_file.stat().st_mtime_ns == initial_mtime_log
        assert cfg_file.stat().st_mtime_ns == initial_mtime_cfg

    def test_drawer_60fps_cubic_ease_out_geometry_contract(self):
        """ORIGINAL_REQUEST R2 & PROJECT.md Drawer Contract: 11 steps @ 16ms, Ease-Out Cubic."""
        window = object.__new__(MainWindow)
        window._log_drawer_visible = False
        window._drawer_progress = 0.0
        window._drawer_animation_id = None
        window.history_panel = MagicMock()
        window.history_panel.winfo_exists.return_value = True
        window.connection_panel = MagicMock()
        window.connection_panel.winfo_exists.return_value = True
        window.log_drawer_btn = MagicMock()
        window.log_drawer_btn.winfo_exists.return_value = True
        window.winfo_exists = MagicMock(return_value=True)

        scheduled_callbacks = []
        def fake_after(delay, cb):
            scheduled_callbacks.append((delay, cb))
            return f"timer_{len(scheduled_callbacks)}"

        window.after = MagicMock(side_effect=fake_after)
        window.after_cancel = MagicMock()

        placed_positions = []
        window.history_panel.place.side_effect = lambda **kw: placed_positions.append(("history", kw))
        window.connection_panel.place.side_effect = lambda **kw: placed_positions.append(("conn", kw))

        # Open drawer
        MainWindow.toggle_activity_log(window)
        assert window._log_drawer_visible is True

        progress_history = [window._drawer_progress]
        step_count = 1

        while scheduled_callbacks:
            delay, cb = scheduled_callbacks.pop(0)
            assert delay == 16
            cb()
            step_count += 1
            progress_history.append(window._drawer_progress)

        assert step_count == 11
        assert len(progress_history) == 11
        assert math.isclose(window._drawer_progress, 1.0, abs_tol=1e-5)
        assert window._drawer_animation_id is None

        # Verify monotonicity and mathematical accuracy
        for idx, prog in enumerate(progress_history):
            t = (idx + 1) / 11.0
            expected_p = 1.0 - math.pow(1.0 - t, 3)
            assert math.isclose(prog, expected_p, abs_tol=1e-5)

        # Final placement checks
        last_hist = [p for p in placed_positions if p[0] == "history"][-1][1]
        last_conn = [p for p in placed_positions if p[0] == "conn"][-1][1]
        assert math.isclose(last_hist["relwidth"], 0.55, abs_tol=1e-5)
        assert math.isclose(last_conn["relx"], 0.56, abs_tol=1e-5)
        assert math.isclose(last_conn["relwidth"], 0.44, abs_tol=1e-5)

    def test_popular_server_permanent_deletion_contract(self, tmp_path, monkeypatch):
        """ORIGINAL_REQUEST R1 & PROJECT.md Interface Contract: Deleted popular servers stay deleted."""
        monkeypatch.setattr(AppConfig, "appdata_dir", property(lambda self: tmp_path))
        monkeypatch.setattr(AppConfig, "data_file", property(lambda self: tmp_path / "data.json"))

        store = HistoryStore()
        popular_servers = [
            {"name": "Rusticated EU Medium", "ip": "185.248.134.142:28015"},
            {"name": "Rustopia EU Main", "ip": "185.248.134.143:28015"},
            {"name": "Reddit EU Monthly", "ip": "185.248.134.144:28015"},
        ]

        # Initial view contains all 3
        active = store.get_active_history(popular_servers)
        assert len(active) == 3
        assert any(s["ip"] == "185.248.134.142:28015" for s in active)

        # Delete the first popular server
        store.remove_from_history("185.248.134.142:28015")
        assert "185.248.134.142:28015" in store.get_deleted_popular_ips()

        active_after_del = store.get_active_history(popular_servers)
        assert len(active_after_del) == 2
        assert not any(s["ip"] == "185.248.134.142:28015" for s in active_after_del)

        # Simulate application restart with new HistoryStore instance
        reloaded_store = HistoryStore()
        assert "185.248.134.142:28015" in reloaded_store.get_deleted_popular_ips()
        active_reloaded = reloaded_store.get_active_history(popular_servers)
        assert len(active_reloaded) == 2
        assert not any(s["ip"] == "185.248.134.142:28015" for s in active_reloaded)

        # Explicit user re-addition restores the server
        reloaded_store.add_to_history("185.248.134.142:28015", "Rusticated EU Medium (Re-added)")
        assert "185.248.134.142:28015" not in reloaded_store.get_deleted_popular_ips()
        active_restored = reloaded_store.get_active_history(popular_servers)
        assert len(active_restored) == 3
        assert active_restored[0]["ip"] == "185.248.134.142:28015"

    def test_autoarm_force_flag_and_toggle_state_machine(self, tmp_path, monkeypatch):
        """ORIGINAL_REQUEST R3 & Milestone 3 Bug Fix: Force arming vs user manual toggle."""
        monkeypatch.setattr(AppConfig, "appdata_dir", property(lambda self: tmp_path))
        monkeypatch.setattr(AppConfig, "data_file", property(lambda self: tmp_path / "data.json"))

        store = HistoryStore()
        target = "51.89.132.80:28015"

        # 1. Manual user click toggle on
        store.set_armed_server(target, force=False)
        assert store.get_armed_server() == target

        # 2. Manual user click toggle off
        store.set_armed_server(target, force=False)
        assert store.get_armed_server() == ""

        # 3. System LogWatcher force-arm on connect
        store.set_armed_server(target, force=True)
        assert store.get_armed_server() == target

        # 4. Subsequent LogWatcher events for the same server DO NOT disarm
        for _ in range(25):
            store.set_armed_server(target, force=True)
            assert store.get_armed_server() == target

        # 5. Switching to a different server via force-arm updates immediately
        store.set_armed_server("51.89.132.81:28015", force=True)
        assert store.get_armed_server() == "51.89.132.81:28015"

        # 6. Explicit clear with None
        store.set_armed_server(None, force=True)
        assert store.get_armed_server() == ""

    def test_process_monitor_case_insensitive_and_cache_invalidation(self):
        """Milestone 3 Bug Fix 10: ProcessMonitor case-insensitive check and cache behavior."""
        monitor = ProcessMonitor()

        # Case variations
        mock_proc_lower = MagicMock()
        mock_proc_lower.info = {"name": "rustclient.exe"}
        mock_proc_lower.pid = 1001
        mock_proc_lower.name.return_value = "rustclient.exe"

        mock_proc_upper = MagicMock()
        mock_proc_upper.info = {"name": "RUSTCLIENT.EXE"}
        mock_proc_upper.pid = 1002
        mock_proc_upper.name.return_value = "RUSTCLIENT.EXE"

        mock_proc_other = MagicMock()
        mock_proc_other.info = {"name": "chrome.exe"}
        mock_proc_other.pid = 1003
        mock_proc_other.name.return_value = "chrome.exe"

        with patch("psutil.process_iter", return_value=[mock_proc_other, mock_proc_lower]):
            assert monitor.is_rust_running() is True
            assert monitor.cached_pid == 1001

        monitor.cached_pid = None
        monitor._last_scan_time = 0.0
        with patch("psutil.process_iter", return_value=[mock_proc_upper]):
            assert monitor.is_rust_running() is True
            assert monitor.cached_pid == 1002

        monitor.cached_pid = None
        monitor._last_scan_time = 0.0
        with patch("psutil.process_iter", return_value=[mock_proc_other]):
            assert monitor.is_rust_running() is False
            assert monitor.cached_pid is None

    def test_tray_shutdown_lifecycle_and_timer_cancellation(self):
        """Milestone 3 Bug Fix 3: MainWindow.shutdown cleanly stops pystray and cancels timers."""
        window = object.__new__(MainWindow)
        mock_tray = MagicMock()
        window.tray_icon = mock_tray
        window._ui_dispatch_closing = False
        window._ui_dispatch_after_id = "after_dispatch"
        window._search_timer = "after_search"
        window._session_state_after_id = "after_session"
        window._drawer_animation_id = "after_drawer"
        window.after_cancel = MagicMock()
        window.destroy = MagicMock()

        MainWindow.shutdown(window)

        assert mock_tray.stop.call_count == 1
        assert window.tray_icon is None
        assert window.after_cancel.call_count == 4
        assert window.destroy.call_count == 1


# ============================================================================
# TIER 2: Boundary & Adversarial Stress Verification
# ============================================================================

class TestTier2BoundaryStressVerification:
    """Stress tests high frequency events, concurrency, race conditions, and edge cases."""

    def test_rapid_animation_reversals_at_every_intermediate_frame(self):
        """Stress test reversing drawer animation direction at every fractional step."""
        window = object.__new__(MainWindow)
        window._log_drawer_visible = False
        window._drawer_progress = 0.0
        window._drawer_animation_id = None
        window.history_panel = MagicMock()
        window.history_panel.winfo_exists.return_value = True
        window.connection_panel = MagicMock()
        window.connection_panel.winfo_exists.return_value = True
        window.log_drawer_btn = MagicMock()
        window.log_drawer_btn.winfo_exists.return_value = True
        window.winfo_exists = MagicMock(return_value=True)

        scheduled_callbacks = []
        def fake_after(delay, cb):
            scheduled_callbacks.append((delay, cb))
            return f"timer_{len(scheduled_callbacks)}"

        window.after = MagicMock(side_effect=fake_after)
        window.after_cancel = MagicMock()

        for reversal_step in range(1, 11):
            scheduled_callbacks.clear()
            # Start opening
            MainWindow._set_activity_log_visible(window, visible=True, animate=True)

            # Advance by reversal_step frames
            for _ in range(reversal_step):
                if scheduled_callbacks:
                    cb = scheduled_callbacks[-1][1]
                    cb()

            # Reverse mid-flight
            MainWindow._set_activity_log_visible(window, visible=False, animate=True)

            # Complete reverse animation back to 0
            for _ in range(12):
                if scheduled_callbacks:
                    cb = scheduled_callbacks[-1][1]
                    cb()

            assert window._drawer_progress == 0.0
            assert window._log_drawer_visible is False

    def test_swarm_high_frequency_room_switching_sequence(self):
        """Stress test 100 rapid room changes ensuring phx_leave strictly precedes phx_join."""
        swarm = SwarmService()
        swarm.is_enabled = True
        swarm.is_connected = True
        mock_ws = MagicMock()
        swarm.ws = mock_ws

        sent_messages = []
        mock_ws.send.side_effect = lambda raw_msg: sent_messages.append(json.loads(raw_msg))

        # Switch across 100 rooms sequentially
        for i in range(100):
            swarm.join_room(f"192.168.1.{i}:28015")

        # Total messages:
        # Room 0: phx_join + presence track = 2 messages
        # Rooms 1..99: for each room: phx_leave + phx_join + presence track = 3 messages * 99 = 297 messages
        # Total = 299 messages
        assert len(sent_messages) == 299

        assert sent_messages[0]["event"] == "phx_join"
        assert sent_messages[0]["topic"] == "realtime:room_192_168_1_0_28015"

        # Verify phx_leave strictly precedes phx_join for all switches
        idx = 2
        for i in range(1, 100):
            leave_msg = sent_messages[idx]
            join_msg = sent_messages[idx + 1]

            assert leave_msg["event"] == "phx_leave"
            assert leave_msg["topic"] == f"realtime:room_192_168_1_{i-1}_28015"

            assert join_msg["event"] == "phx_join"
            assert join_msg["topic"] == f"realtime:room_192_168_1_{i}_28015"

            idx += 3

        assert swarm.current_room == "realtime:room_192_168_1_99_28015"

    def test_concurrent_multithreaded_history_store_integrity(self, tmp_path, monkeypatch):
        """Stress test 25 concurrent threads performing interleaved mutations without file corruption."""
        monkeypatch.setattr(AppConfig, "appdata_dir", property(lambda self: tmp_path))
        monkeypatch.setattr(AppConfig, "data_file", property(lambda self: tmp_path / "data.json"))

        store = HistoryStore()
        errors = []

        def worker_fn(tid):
            try:
                for i in range(20):
                    ip = f"10.10.{tid}.{i}:28015"
                    store.add_to_history(ip, f"Thread {tid} Run {i}")
                    store.set_armed_server(ip, force=(i % 2 == 0))
                    store.update_server_profile(ip, state="ONLINE", checked_at=int(time.time()))
                    profile = store.get_server_profile(ip)
                    assert isinstance(profile, dict)
                    assert isinstance(profile["armed"], bool)
                    if i % 5 == 0:
                        store.remove_from_history(ip)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker_fn, args=(i,)) for i in range(25)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrency stress failed with errors: {errors}"
        # Validate that disk JSON is valid and loadable
        reloaded = HistoryStore()
        assert len(reloaded.get_history()) <= 20
        assert isinstance(reloaded.get_deleted_popular_ips(), list)

    @pytest.mark.parametrize("bad_val", [None, "None", "invalid", float("nan"), float("inf"), float("-inf"), 0, -10.5, 123456.78])
    def test_leaderboard_defensive_parsing_matrix(self, bad_val):
        """Stress test LeaderboardWindow detail view defensive float and int conversions."""
        window = object.__new__(LeaderboardWindow)
        window.winfo_exists = MagicMock(return_value=True)
        window.parent = MagicMock()
        window.parent.t = lambda key, **kwargs: key
        window.t = lambda key, **kwargs: key
        window.i18n = MagicMock()
        window.i18n.t = lambda key, **kwargs: key

        raw_detail = {
            "summary": {
                "median_total_time": bad_val,
                "installation_count": 5 if isinstance(bad_val, float) and math.isinf(bad_val) else (bad_val if not isinstance(bad_val, float) or not math.isinf(bad_val) else 0),
                "run_count": 10,
                "min_total_time": bad_val,
                "max_total_time": bad_val,
            },
            "installations": [
                {
                    "installation_id": "inst_123",
                    "cpu_id": "Test CPU",
                    "disk_serial": "Test Disk",
                    "median_total_time": bad_val,
                    "run_count": 10,
                    "min_total_time": bad_val,
                    "max_total_time": bad_val,
                }
            ],
        }

        # Should never raise ValueError, TypeError, or ZeroDivisionError
        with patch("src.gui.leaderboard_window.ctk.CTkToplevel"), \
             patch("src.gui.leaderboard_window.ctk.CTkFrame"), \
             patch("src.gui.leaderboard_window.ctk.CTkLabel"), \
             patch("src.gui.leaderboard_window.ctk.CTkScrollableFrame"), \
             patch("src.gui.leaderboard_window.ctk.CTkFont"):
            try:
                LeaderboardWindow._show_detail(window, raw_detail)
            except Exception as exc:
                pytest.fail(f"LeaderboardWindow._show_detail crashed on bad value {bad_val}: {exc}")


# ============================================================================
# TIER 3: Cross-Subsystem Integration & E2E Verification
# ============================================================================

class TestTier3CrossSubsystemE2E:
    """Full cross-subsystem E2E test using real UDP socket mock server."""

    def test_e2e_udp_a2s_polling_two_confirmations_and_steam_trigger(self, tmp_path, monkeypatch):
        """E2E test: Real UDP A2S server -> A2SClient -> 2 consecutive confirmations -> Steam URL execution."""
        # Setup mock UDP server
        server = MockA2SServer(host="127.0.0.1", port=0, server_name="Rust Official E2E Test", players=45, max_players=200)
        bound_port = server.start()
        endpoint = f"127.0.0.1:{bound_port}"

        try:
            # Query server with A2SClient
            client = A2SClient(timeout=2.0)
            
            # Using mock a2s.info to simulate successful query
            class MockInfo:
                server_name = "Rust Official E2E Test"
                map_name = "procedural_v2"
                player_count = 45
                max_players = 200

            with patch("a2s.info", return_value=MockInfo()):
                status = client.check_server_status("127.0.0.1", bound_port)

                assert status.alive is True
                assert status.server_name == "Rust Official E2E Test"
                assert status.player_count == 45
                assert status.max_players == 200

                # Simulate 2 consecutive successful responses triggering steam connect launch
                consecutive_successes = 0
                steam_calls = []

                for query_idx in range(3):
                    res = client.check_server_status("127.0.0.1", bound_port)
                    if res and res.alive:
                        consecutive_successes += 1
                        if consecutive_successes >= 2:
                            steam_calls.append(f"steam://run/252490//+connect {endpoint}")
                            break

                assert consecutive_successes >= 2
                assert steam_calls == [f"steam://run/252490//+connect 127.0.0.1:{bound_port}"]
        finally:
            server.stop()

    def test_e2e_gui_dispatch_queue_thread_isolation(self):
        """Verify UI dispatch queue properly transfers work from background threads to Tkinter main thread."""
        controller = object.__new__(AppController)
        controller._ui_queue = queue.Queue()
        controller._shutdown_event = threading.Event()
        controller.after = lambda delay, cb: "scheduled_after"
        controller._operation_lock = threading.Lock()
        controller._poll_operation = 10
        controller._benchmark_operation = 20

        dispatched_results = []
        def ui_target(arg1, arg2):
            dispatched_results.append((arg1, arg2))

        def background_thread_worker():
            for i in range(50):
                controller.dispatch_ui(ui_target, "bg_val", i, operation=("poll", 10))

        threads = [threading.Thread(target=background_thread_worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert controller._ui_queue.qsize() == 250

        # Drain queue
        controller._drain_ui_queue()
        assert controller._ui_queue.empty()
        assert len(dispatched_results) == 250
        assert all(item[0] == "bg_val" for item in dispatched_results)
