"""Empirical Adversarial Stress Tests for Milestone 3 Subsystem Hardening.

Challenger: challenger_m3_1
Target subsystems:
1. A2SClient.get_rustmaps_url event loop & concurrency stress testing.
2. SwarmService.join_room rapid topic switching & leave/join sequence invariants.
3. LeaderboardWindow float parsing stress testing with corrupt, null, and boundary JSON.
4. ProcessMonitor case-insensitivity, caching, and concurrent process scanning.
5. TelegramService latency, timeout, malformed payloads, and non-blocking UI dispatch.
"""

import asyncio
import concurrent.futures
import json
import math
import socket
import threading
import time
import urllib.error
from unittest.mock import MagicMock, patch, call
import pytest

from src.core.a2s_client import A2SClient
from src.services.swarm_service import SwarmService
from src.gui.leaderboard_window import LeaderboardWindow
from src.services.process_monitor import ProcessMonitor
from src.services.telegram_service import TelegramService
from src.gui.main_window import MainWindow


# ============================================================================
# Dimension 1: A2SClient.get_rustmaps_url Stress Testing
# ============================================================================

class TestA2SRustMapsStress:
    """Stress tests for A2SClient.get_rustmaps_url across sync, async, and concurrent loops."""

    def test_rustmaps_url_regex_adversarial_inputs(self):
        """Test URL conversion against edge cases, casing, and malformed strings."""
        client = A2SClient()

        # Valid 32-char hex hashes
        assert client.rustmaps_view_url("http://maps.rustmaps.com/12345/abcdef1234567890abcdef1234567890/") == "https://rustmaps.com/map/abcdef1234567890abcdef1234567890"
        assert client.rustmaps_view_url("https://maps.rustmaps.com/0/ABCDEF1234567890ABCDEF1234567890/") == "https://rustmaps.com/map/abcdef1234567890abcdef1234567890"

        # Invalid / boundary inputs
        assert client.rustmaps_view_url(None) == ""
        assert client.rustmaps_view_url(12345) == ""
        assert client.rustmaps_view_url("") == ""
        assert client.rustmaps_view_url("http://maps.rustmaps.com/12345/short_hash/") == ""
        assert client.rustmaps_view_url("http://google.com/test") == ""
        assert client.rustmaps_view_url("http://maps.rustmaps.com/12345/zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz/") == ""

    def test_rustmaps_query_port_boundaries(self):
        """Test query port range checks (1 to 65535)."""
        client = A2SClient()
        invalid_ports = [-100, -1, 0, 65536, 70000, 100000]
        for port in invalid_ports:
            assert client.get_rustmaps_url("127.0.0.1", port) == ""

    def test_rustmaps_url_sync_100_iterations(self):
        """Stress test synchronous calls over 100 iterations."""
        client = A2SClient()
        start = time.perf_counter()
        with patch.object(client, "_get_rustmaps_url_async", return_value="https://rustmaps.com/map/abcdef1234567890abcdef1234567890"):
            for i in range(100):
                url = client.get_rustmaps_url("127.0.0.1", 28015 + (i % 10))
                assert url == "https://rustmaps.com/map/abcdef1234567890abcdef1234567890"
        elapsed = time.perf_counter() - start
        assert elapsed < 2.0, f"100 sync iterations took {elapsed:.2f}s"

    def test_rustmaps_url_concurrent_async_event_loop_50_tasks(self):
        """Stress test 50 concurrent async tasks inside an active running event loop."""
        client = A2SClient()

        async def worker_task(idx):
            with patch.object(client, "_get_rustmaps_url_async", return_value=f"https://rustmaps.com/map/{idx:032x}"):
                return client.get_rustmaps_url("127.0.0.1", 28015)

        async def run_suite():
            tasks = [worker_task(i) for i in range(50)]
            return await asyncio.gather(*tasks)

        start = time.perf_counter()
        results = asyncio.run(run_suite())
        elapsed = time.perf_counter() - start

        assert len(results) == 50
        for i, res in enumerate(results):
            assert res == f"https://rustmaps.com/map/{i:032x}"
        assert elapsed < 5.0, f"50 async tasks took {elapsed:.2f}s"

    def test_rustmaps_url_multithreaded_separate_event_loops(self):
        """Stress test 10 concurrent threads each running their own active asyncio loop."""
        client = A2SClient()

        def thread_worker(thread_id, results_dict):
            async def async_inner():
                inner_tasks = []
                for j in range(10):
                    with patch.object(client, "_get_rustmaps_url_async", return_value=f"https://rustmaps.com/map/{thread_id}_{j}"):
                        url = client.get_rustmaps_url("127.0.0.1", 28015)
                        inner_tasks.append(url)
                return inner_tasks

            results = asyncio.run(async_inner())
            results_dict[thread_id] = results

        threads = []
        results_dict = {}
        start = time.perf_counter()
        for i in range(10):
            t = threading.Thread(target=thread_worker, args=(i, results_dict))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=5.0)

        elapsed = time.perf_counter() - start
        assert len(results_dict) == 10
        for i in range(10):
            assert len(results_dict[i]) == 10
        assert elapsed < 5.0

    def test_rustmaps_url_exception_handling_in_loop(self):
        """Verify exceptions inside async handler do not crash get_rustmaps_url."""
        client = A2SClient()

        async def test_exceptions():
            # Test timeout error
            with patch.object(client, "_get_rustmaps_url_async", side_effect=asyncio.TimeoutError("timeout")):
                assert client.get_rustmaps_url("127.0.0.1", 28015) == ""

            # Test OS / socket error
            with patch.object(client, "_get_rustmaps_url_async", side_effect=OSError("connection refused")):
                assert client.get_rustmaps_url("127.0.0.1", 28015) == ""

            # Test arbitrary runtime error
            with patch.object(client, "_get_rustmaps_url_async", side_effect=RuntimeError("internal crash")):
                assert client.get_rustmaps_url("127.0.0.1", 28015) == ""

        asyncio.run(test_exceptions())


# ============================================================================
# Dimension 2: SwarmService Room Switching & Invariant Stress Testing
# ============================================================================

class TestSwarmServiceStress:
    """Stress tests for SwarmService room management, leave/join ordering, and concurrency."""

    def test_rapid_room_switching_100_rooms(self):
        """Switch through 100 distinct rooms and verify strict leave-before-join sequence."""
        service = SwarmService()
        service.is_enabled = True
        service.is_connected = True
        mock_ws = MagicMock()
        service.ws = mock_ws

        sent_messages = []
        mock_ws.send.side_effect = lambda msg: sent_messages.append(json.loads(msg))

        start = time.perf_counter()
        num_rooms = 100
        for i in range(num_rooms):
            endpoint = f"10.0.0.{i}:28015"
            service.join_room(endpoint)

        elapsed = time.perf_counter() - start

        # Analysis of sent events
        event_types = [m.get("event") for m in sent_messages]
        topics = [m.get("topic") for m in sent_messages]

        # First room has no prior room to leave, so 1 join + 1 presence
        # Subsequent 99 rooms have: 1 leave + 1 join + 1 presence
        expected_leaves = num_rooms - 1
        expected_joins = num_rooms

        actual_leaves = event_types.count("phx_leave")
        actual_joins = event_types.count("phx_join")

        assert actual_leaves == expected_leaves, f"Expected {expected_leaves} leaves, got {actual_leaves}"
        assert actual_joins == expected_joins, f"Expected {expected_joins} joins, got {actual_joins}"

        # Verify ordering: for each room switch k -> k+1:
        # Message for leaving room k must occur before joining room k+1
        leave_indices = [idx for idx, ev in enumerate(event_types) if ev == "phx_leave"]
        join_indices = [idx for idx, ev in enumerate(event_types) if ev == "phx_join"]

        for k in range(len(leave_indices)):
            leave_idx = leave_indices[k]
            join_idx = join_indices[k + 1]
            assert leave_idx < join_idx, f"Leave at {leave_idx} was not before join at {join_idx}"
            assert topics[leave_idx] == f"realtime:room_10_0_0_{k}_28015"
            assert topics[join_idx] == f"realtime:room_10_0_0_{k+1}_28015"

        # Final state check
        assert service.current_ip_port == f"10.0.0.{num_rooms-1}:28015"
        assert service.current_room == f"realtime:room_10_0_0_{num_rooms-1}_28015"
        assert elapsed < 1.0, f"100 room switches took {elapsed:.2f}s"

    def test_rejoining_same_room_does_not_trigger_leave(self):
        """Calling join_room with the identical room repeatedly must not send leave."""
        service = SwarmService()
        service.is_enabled = True
        service.is_connected = True
        mock_ws = MagicMock()
        service.ws = mock_ws

        sent_messages = []
        mock_ws.send.side_effect = lambda msg: sent_messages.append(json.loads(msg))

        service.join_room("127.0.0.1:28015")
        initial_count = len(sent_messages)

        # Call join_room with same endpoint 50 times
        for _ in range(50):
            service.join_room("127.0.0.1:28015")

        # Must never send phx_leave for the same room
        leave_events = [m for m in sent_messages if m.get("event") == "phx_leave"]
        assert len(leave_events) == 0

    def test_leave_room_when_disconnected_or_disabled(self):
        """Verifies state is properly cleared even if WebSocket is disconnected."""
        service = SwarmService()
        service.is_enabled = True
        service.is_connected = False
        service.ws = None
        service.current_room = "realtime:room_127_0_0_1_28015"
        service.current_ip_port = "127.0.0.1:28015"

        presence_updated = []
        service.on_presence_update = lambda count: presence_updated.append(count)

        service.leave_room()

        assert service.current_room is None
        assert service.current_ip_port is None
        assert presence_updated == [0]

    def test_concurrent_room_switching_stress(self):
        """Stress test 10 concurrent threads switching rooms."""
        service = SwarmService()
        service.is_enabled = True
        service.is_connected = True
        mock_ws = MagicMock()
        service.ws = mock_ws

        lock = threading.Lock()
        sent_messages = []

        def safe_send(msg):
            with lock:
                sent_messages.append(json.loads(msg))

        mock_ws.send.side_effect = safe_send

        def worker(thread_idx):
            for i in range(20):
                service.join_room(f"192.168.{thread_idx}.{i}:28015")
                time.sleep(0.001)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(10)]
        start = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.perf_counter() - start

        assert len(sent_messages) > 0
        assert elapsed < 5.0


# ============================================================================
# Dimension 3: LeaderboardWindow Float & Null Parsing Stress Testing
# ============================================================================

class TestLeaderboardNullFloatParsingStress:
    """Stress tests for LeaderboardWindow parsing dirty, null, boundary, and corrupt JSON."""

    @pytest.mark.parametrize("med_total, inst_cnt, run_cnt, min_t, max_t", [
        (None, None, None, None, None),
        (0, 0, 0, 0, 0),
        (0.0, 0, 0, 0.0, 0.0),
        (-5.5, -1, -10, -10.0, -1.0),
        (123.456789, 10000, 50000, 10.0, 500.0),
        (1e6, 999999, 999999, 1e5, 2e6),
        (float("inf"), 1, 1, float("inf"), float("inf")),
        (float("nan"), 0, 0, float("nan"), float("nan")),
        ("12.34", "5", "10", "1.2", "34.5"),
    ])
    def test_show_detail_summary_matrix(self, med_total, inst_cnt, run_cnt, min_t, max_t):
        """Test matrix of summary float fields with explicit null and boundary values without crashing."""
        window = object.__new__(LeaderboardWindow)
        window.winfo_exists = MagicMock(return_value=True)
        window.parent = MagicMock()
        window.parent.t = lambda key, **kwargs: key

        detail = {
            "summary": {
                "median_total_time": med_total,
                "installation_count": inst_cnt,
                "run_count": run_cnt,
                "min_total_time": min_t,
                "max_total_time": max_t,
            },
            "installations": []
        }

        with patch("src.gui.leaderboard_window.ctk.CTkFont"), \
             patch("src.gui.leaderboard_window.ctk.CTkToplevel"), \
             patch("src.gui.leaderboard_window.ctk.CTkLabel") as mock_label, \
             patch("src.gui.leaderboard_window.ctk.CTkScrollableFrame"):

            LeaderboardWindow._show_detail(window, detail)
            assert mock_label.called

    def test_show_detail_adversarial_installations_list(self):
        """Stress test with 100 dirty installation entries containing missing, None, and corrupt fields."""
        window = object.__new__(LeaderboardWindow)
        window.winfo_exists = MagicMock(return_value=True)
        window.parent = MagicMock()
        window.parent.t = lambda key, **kwargs: key

        installations = []
        for i in range(100):
            inst = {}
            if i % 2 == 0:
                inst["median_total_time"] = None
            elif i % 3 == 0:
                inst["median_total_time"] = float(i * 1.5)
            elif i % 5 == 0:
                inst["median_total_time"] = 0
            # else: missing median_total_time

            if i % 4 == 0:
                inst["run_count"] = None
            elif i % 7 == 0:
                inst["run_count"] = i
            # else: missing run_count

            installations.append(inst)

        detail = {
            "summary": {"median_total_time": 45.2, "installation_count": 100, "run_count": 500},
            "installations": installations
        }

        with patch("src.gui.leaderboard_window.ctk.CTkFont"), \
             patch("src.gui.leaderboard_window.ctk.CTkToplevel"), \
             patch("src.gui.leaderboard_window.ctk.CTkLabel") as mock_label, \
             patch("src.gui.leaderboard_window.ctk.CTkScrollableFrame"):

            LeaderboardWindow._show_detail(window, detail)
            # Should render summary label + 100 installation labels
            assert mock_label.call_count >= 101

    def test_show_detail_empty_detail_object(self):
        """Verify None or empty detail dict handle gracefully."""
        window = object.__new__(LeaderboardWindow)
        window.winfo_exists = MagicMock(return_value=True)
        window.parent = MagicMock()

        # None detail
        LeaderboardWindow._show_detail(window, None)

        # Empty dict
        with patch("src.gui.leaderboard_window.ctk.CTkFont"), \
             patch("src.gui.leaderboard_window.ctk.CTkToplevel"), \
             patch("src.gui.leaderboard_window.ctk.CTkLabel"), \
             patch("src.gui.leaderboard_window.ctk.CTkScrollableFrame"):

            LeaderboardWindow._show_detail(window, {})

    @pytest.mark.parametrize("payload", [
        [{"configuration_key": "k1", "median_total_time": None, "cpu": "i7", "storage": "SSD"}],
        [{"configuration_key": "k2", "median_total_time": "", "cpu": "i7", "storage": "SSD"}],
        [{"configuration_key": "k3", "total_time": None}],
        [{"configuration_key": "k4", "total_time": ""}],
        [{"configuration_key": "k5", "median_total_time": 0.0}],
        [{"configuration_key": "k6", "median_total_time": 1e-9}],
        [{"configuration_key": "k7", "median_total_time": 99999999.9}],
        [{}],
        [{"other_unexpected_key": 123}],
        [{"configuration_key": "k8", "median_total_time": None, "installation_count": None, "run_count": None}],
    ])
    def test_render_data_and_render_rows_matrix(self, payload):
        """Stress test _render_data and _render_rows with explicit null, None, empty string, missing keys, and boundary float values."""
        window = object.__new__(LeaderboardWindow)
        window.winfo_exists = MagicMock(return_value=True)
        window.parent = MagicMock()
        window.parent.t = lambda key, **kwargs: key
        window._load_generation = 1
        window.search_btn = MagicMock()
        window.load_more_btn = MagicMock()
        window.scroll = MagicMock()
        window.scroll.winfo_children.return_value = []
        window.current_data = []
        window.offset = 0
        window.limit = 20

        with patch("src.gui.leaderboard_window.ctk.CTkFont"), \
             patch("src.gui.leaderboard_window.ctk.CTkFrame"), \
             patch("src.gui.leaderboard_window.ctk.CTkLabel"), \
             patch("src.gui.leaderboard_window.ctk.CTkButton"):

            LeaderboardWindow._render_data(window, payload, is_new_search=True, generation=1)


# ============================================================================
# Dimension 4: ProcessMonitor Case-Insensitivity & Concurrency Stress Testing
# ============================================================================

class TestProcessMonitorStress:
    """Stress tests for ProcessMonitor case permutations, caching, and concurrent scans."""

    def test_process_monitor_case_permutations(self):
        """Test all combinations of casing for RustClient.exe."""
        monitor = ProcessMonitor()
        cases = [
            "RustClient.exe",
            "rustclient.exe",
            "RUSTCLIENT.EXE",
            "rUsTcLiEnT.eXe",
            "RUSTCLIENT.exe",
            "rustclient.EXE",
            "Rustclient.Exe",
        ]

        for case_name in cases:
            monitor.cached_pid = None
            monitor._last_scan_time = 0.0

            mock_proc = MagicMock()
            mock_proc.pid = 9999
            mock_proc.info = {"name": case_name}
            mock_proc.name.return_value = case_name

            with patch("psutil.process_iter", return_value=[mock_proc]), \
                 patch("psutil.Process", return_value=mock_proc):
                assert monitor.is_rust_running() is True, f"Failed on case: {case_name}"
                assert monitor.cached_pid == 9999

                # Test cached PID path
                assert monitor.is_rust_running() is True

                # Test get_rust_pids
                assert monitor.get_rust_pids() == {9999}

    def test_process_monitor_non_matching_names(self):
        """Test that false positives / partial matches are rejected."""
        monitor = ProcessMonitor()
        non_matches = [
            "RustClient.exe.bak",
            "NotRustClient.exe",
            "RustDedicated.exe",
            "Rust.exe",
            "rustclient",
            "RustClient.dll",
            "",
            None,
        ]

        for bad_name in non_matches:
            monitor.cached_pid = None
            monitor._last_scan_time = 0.0

            mock_proc = MagicMock()
            mock_proc.pid = 1111
            mock_proc.info = {"name": bad_name}
            mock_proc.name.return_value = bad_name

            with patch("psutil.process_iter", return_value=[mock_proc]):
                assert monitor.is_rust_running() is False, f"False positive on: {bad_name}"
                assert monitor.get_rust_pids() == set()

    def test_process_monitor_cache_invalidation_on_process_termination(self):
        """Verify cached PID invalidates when process terminates or changes name."""
        monitor = ProcessMonitor()
        monitor.cached_pid = 4321

        with patch("psutil.Process", side_effect=Exception("NoSuchProcess")):
            monitor._last_scan_time = time.time()  # Within 1.5s
            running = monitor.is_rust_running()
            assert running is False
            assert monitor.cached_pid is None

    def test_process_monitor_concurrent_access_stress(self):
        """Stress test 20 threads simultaneously calling is_rust_running and get_rust_pids."""
        monitor = ProcessMonitor()

        mock_proc_1 = MagicMock()
        mock_proc_1.pid = 1001
        mock_proc_1.info = {"name": "RUSTCLIENT.EXE"}
        mock_proc_1.name.return_value = "RUSTCLIENT.EXE"

        mock_proc_2 = MagicMock()
        mock_proc_2.pid = 1002
        mock_proc_2.info = {"name": "rustclient.exe"}
        mock_proc_2.name.return_value = "rustclient.exe"

        def mock_get_process(pid):
            if pid == 1001:
                return mock_proc_1
            elif pid == 1002:
                return mock_proc_2
            raise Exception("NoSuchProcess")

        results = []

        def worker():
            for _ in range(50):
                with patch("psutil.process_iter", return_value=[mock_proc_1, mock_proc_2]), \
                     patch("psutil.Process", side_effect=mock_get_process):
                    is_run = monitor.is_rust_running()
                    pids = monitor.get_rust_pids()
                    results.append((is_run, pids))

        threads = [threading.Thread(target=worker) for _ in range(20)]
        start = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.perf_counter() - start

        assert len(results) == 1000
        for is_run, pids in results:
            assert is_run is True
            assert pids == {1001, 1002}
        assert elapsed < 5.0


# ============================================================================
# Dimension 5: TelegramService Latency, Timeout & UI Thread Isolation Stress
# ============================================================================

class TestTelegramServiceLatencyAndIsolationStress:
    """Stress tests for TelegramService error recovery, timeout, and async UI dispatch."""

    def test_telegram_generate_link_code_timeouts_and_network_errors(self):
        """Stress test generate_link_code with timeouts, HTTP errors, and malformed responses."""
        service = TelegramService()

        # Simulate None return on network error
        with patch.object(service, "_request", return_value=None):
            code = service.generate_link_code("EN")
            assert code is None

        # Simulate malformed payloads
        malformed_cases = [
            {},
            {"status": "ok"},
            {"code": None},
            {"code": ""},
            {"code": 12345},
            {"other_key": "123456"},
            {"accepted": False},
            {"accepted": True, "notification_token": None},
            {"accepted": True, "notification_token": ""},
        ]

        for payload in malformed_cases:
            with patch.object(service, "_request", return_value=payload if isinstance(payload, dict) else None):
                code = service.generate_link_code("EN")
                assert code is None

    def test_telegram_link_click_ui_isolation_under_latency(self):
        """Verify UI thread is never blocked even when API takes 1.0s to respond."""
        window = object.__new__(MainWindow)
        window.lang = "en"
        window.t = lambda key, **kwargs: key
        window.tg_link_btn = MagicMock()
        window.tg_status_lbl = MagicMock()
        window.dispatch_ui = MagicMock()
        window._finish_telegram_link = MagicMock()

        def slow_generate(lang):
            time.sleep(0.3)
            return "654321"

        with patch("src.gui.main_window.telegram_service.generate_link_code", side_effect=slow_generate):
            start = time.perf_counter()
            MainWindow._on_tg_link_click(window)
            ui_dispatch_latency = time.perf_counter() - start

            # UI thread call MUST return immediately (under 50ms)
            assert ui_dispatch_latency < 0.05, f"_on_tg_link_click blocked UI thread for {ui_dispatch_latency:.3f}s"

            # Wait for background thread to complete
            time.sleep(0.4)
            window.dispatch_ui.assert_called_once_with(window._finish_telegram_link, "654321")

    def test_telegram_concurrent_link_generation_stress(self):
        """Stress test 20 concurrent threads calling generate_link_code."""
        service = TelegramService()

        def mock_request(path, payload):
            time.sleep(0.01)
            return {"accepted": True, "notification_token": "token_12345"}

        codes = []

        def worker():
            with patch.object(service, "_request", side_effect=mock_request), \
                 patch.object(service, "_save"):
                c = service.generate_link_code("EN")
                codes.append(c)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        start = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.perf_counter() - start

        assert len(codes) == 20
        for c in codes:
            assert isinstance(c, str) and len(c) == 8
        assert elapsed < 3.0
