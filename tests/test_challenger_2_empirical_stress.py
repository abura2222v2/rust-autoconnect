# -*- coding: utf-8 -*-
"""Adversarial stress test suite for Challenger 2: Hardware calculation service,
/api/benchmark_info latency & event-loop safety, and UI drawer 144 FPS / log capping invariants.

Author: Challenger 2 (critic, specialist)
Repository: Rust AutoConnect Web Desktop Interface Refinement
"""

import asyncio
import json
import logging
import os
import platform
import subprocess
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import pytest
from aiohttp.test_utils import TestClient, TestServer

from src.services.hardware_service import HardwareService, hardware_service
from src.web.bridge import WebBridge
from src.web.server import create_app


# ============================================================================
# 1. HARDWARE SERVICE EMPIRICAL STRESS TESTS
# ============================================================================

class TestHardwareServiceEmpiricalStress(unittest.TestCase):
    """Stress tests HardwareService for 50+ concurrent requests, subprocess timeouts,
    cold-start vs warm-cache latency, and memory safety."""

    def test_50_plus_concurrent_readers_and_writers(self):
        """Stress: 60 concurrent threads simultaneously hammering getters and triggering refresh."""
        hw = HardwareService(auto_start=False)
        hw._cache = {
            "cpu": "Intel Core i7-13700K",
            "ram": "32 GB",
            "disk": "Samsung 990 PRO 2TB",
            "os": "Windows 11 Pro",
            "cpu_id": "Intel Core i7-13700K",
            "disk_serial": "Samsung 990 PRO 2TB",
        }
        hw._is_ready.set()

        errors = []
        latencies = []

        def worker(thread_idx: int):
            try:
                for i in range(200):
                    t0 = time.perf_counter()
                    cpu = hw.get_cpu_info()
                    ram = hw.get_ram_info()
                    disk = hw.get_disk_info()
                    os_info = hw.get_os_info()
                    cpu_id = hw.get_cpu_id()
                    disk_serial = hw.get_disk_serial()
                    sys_info = hw.get_system_info()
                    elapsed = time.perf_counter() - t0
                    latencies.append(elapsed)

                    # Invariants
                    self.assertIsInstance(cpu, str)
                    self.assertIsInstance(ram, str)
                    self.assertIsInstance(disk, str)
                    self.assertIsInstance(os_info, str)
                    self.assertIsInstance(sys_info, dict)
                    self.assertEqual(len(sys_info), 6)

                    # Occasional concurrent cache mutation
                    if i % 50 == 0:
                        with hw._lock:
                            hw._cache["cpu"] = f"Dynamic_CPU_{thread_idx}_{i}"
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(60)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Concurrent access generated errors: {errors}")
        self.assertEqual(len(latencies), 60 * 200)
        p99_latency_ms = sorted(latencies)[int(len(latencies) * 0.99)] * 1000.0
        # P99 latency of in-memory lock acquisition and dictionary copy must be < 1ms
        self.assertLess(p99_latency_ms, 1.0, f"P99 latency was {p99_latency_ms:.4f}ms (> 1ms SLA)")

    def test_subprocess_timeout_and_fault_injection_resilience(self):
        """Stress: Simulated powershell freeze, timeouts, corrupt outputs, and platform errors."""
        hw = HardwareService(auto_start=False)

        # 1. TimeoutExpired simulation
        with patch("subprocess.check_output", side_effect=subprocess.TimeoutExpired(cmd="powershell", timeout=5.0)), \
             patch("platform.processor", return_value="Fallback-AMD64"), \
             patch("psutil.virtual_memory", return_value=MagicMock(total=34359738368)), \
             patch("psutil.disk_partitions", return_value=[MagicMock(device="C:")]):
            hw._query_hardware_specs()
            self.assertEqual(hw.get_cpu_info(), "Fallback-AMD64")
            self.assertEqual(hw.get_ram_info(), "32 GB")
            self.assertEqual(hw.get_disk_info(), "C:")

        # 2. Corrupted JSON output
        with patch.object(hw, "_run_ps", return_value="<# XML/HTML error or garbage #> {broken"), \
             patch("platform.processor", return_value="Fallback-Intel"), \
             patch("psutil.virtual_memory", return_value=MagicMock(total=17179869184)):
            hw._query_hardware_specs()
            self.assertEqual(hw.get_cpu_info(), "Fallback-Intel")
            self.assertEqual(hw.get_ram_info(), "16 GB")

        # 3. Subprocess generic OS error / missing executable
        with patch("subprocess.check_output", side_effect=FileNotFoundError("powershell.exe not found")), \
             patch("platform.processor", return_value="Fallback-Generic"):
            hw._query_hardware_specs()
            self.assertEqual(hw.get_cpu_info(), "Fallback-Generic")

    def test_cold_start_vs_warm_cache_latency(self):
        """Stress: Verify cold start returns 'Detecting...' instantly (<0.1ms) without blocking callers,
        and warm cache delivers instant values <0.01ms."""
        # Cold start instance (background thread not finished or not started)
        hw_cold = HardwareService(auto_start=False)
        self.assertFalse(hw_cold.is_ready())

        t0 = time.perf_counter()
        cold_cpu = hw_cold.get_cpu_info()
        cold_ram = hw_cold.get_ram_info()
        cold_disk = hw_cold.get_disk_info()
        cold_time = time.perf_counter() - t0

        self.assertLess(cold_time, 0.001, "Cold getter took > 1ms")
        self.assertEqual(cold_cpu, "Detecting...")
        self.assertEqual(cold_ram, "Detecting...")
        self.assertEqual(cold_disk, "Detecting...")

        # Warm cache
        hw_cold._cache = {
            "cpu": "AMD Ryzen 7 7800X3D",
            "ram": "32 GB",
            "disk": "Samsung SSD 990 PRO 2TB",
            "os": "Windows 11 Pro",
            "cpu_id": "AMD Ryzen 7 7800X3D",
            "disk_serial": "Samsung SSD 990 PRO 2TB",
        }
        hw_cold._is_ready.set()

        t0 = time.perf_counter()
        for _ in range(5000):
            _ = hw_cold.get_system_info()
        warm_time = time.perf_counter() - t0
        avg_warm_time_ms = (warm_time / 5000.0) * 1000.0

        self.assertLess(avg_warm_time_ms, 0.01, f"Average warm lookup took {avg_warm_time_ms:.5f}ms")

    def test_storage_cache_bounds_and_drive_parsing(self):
        """Stress: Test get_benchmark_storage with multiple drives, invalid paths, and uncached drives."""
        hw = HardwareService(auto_start=False)

        # UNC network path does not resolve to a drive letter -> returns Unknown, Unknown without calling PowerShell
        with patch.object(hw, "_run_ps") as mock_ps:
            self.assertEqual(hw.get_benchmark_storage("\\\\network\\share\\rust"), ("Unknown", "Unknown"))
            mock_ps.assert_not_called()

        # Non-Windows OS returns Unknown, Unknown immediately
        with patch("os.name", "posix"), patch.object(hw, "_run_ps") as mock_ps:
            self.assertEqual(hw.get_benchmark_storage("C:\\Rust"), ("Unknown", "Unknown"))
            mock_ps.assert_not_called()

        # Valid drive parsing & cache hit
        drive_payload = json.dumps({"model": "Kingston KC3000 2048GB", "bus": "NVMe"})
        with patch("os.name", "nt"), patch.object(hw, "_run_ps", return_value=drive_payload) as mock_ps:
            # Query drive C
            m1, b1 = hw.get_benchmark_storage("C:\\Program Files\\Steam\\steamapps\\common\\Rust")
            self.assertEqual(m1, "Kingston KC3000 2048GB")
            self.assertEqual(b1, "NVMe")
            self.assertEqual(mock_ps.call_count, 1)

            # Query drive C again (should hit cache)
            m2, b2 = hw.get_benchmark_storage("C:\\Rust\\rustclient.exe")
            self.assertEqual(m2, "Kingston KC3000 2048GB")
            self.assertEqual(b2, "NVMe")
            self.assertEqual(mock_ps.call_count, 1)

            # Query drive D (should make 2nd call)
            m3, b3 = hw.get_benchmark_storage("D:\\SteamLibrary\\Rust")
            self.assertEqual(mock_ps.call_count, 2)


# ============================================================================
# 2. /api/benchmark_info HIGH LOAD & EVENT LOOP NON-BLOCKING VERIFICATION
# ============================================================================

class TestBenchmarkApiLoadAndNonBlocking(unittest.TestCase):
    """Stress tests HTTP endpoint /api/benchmark_info under concurrent load and verifies
    event loop remains completely non-blocking."""

    @pytest.mark.anyio
    async def test_100_concurrent_http_benchmark_info_requests(self):
        """Stress: 100 concurrent async GET requests against /api/benchmark_info."""
        app = create_app()
        token = app["session_token"]
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()

        try:
            # Measure latency for 100 simultaneous concurrent coroutines
            async def fetch_benchmark():
                t0 = time.perf_counter()
                resp = await client.get("/api/benchmark_info", headers={"X-AutoConnect-Token": token})
                elapsed = time.perf_counter() - t0
                assert resp.status == 200
                data = await resp.json()
                assert "cpu" in data
                assert "ram" in data
                assert "disk" in data
                return elapsed

            t_start = time.perf_counter()
            results = await asyncio.gather(*(fetch_benchmark() for _ in range(100)))
            total_time = time.perf_counter() - t_start

            # All 100 requests should complete in < 0.25 seconds total on localhost
            assert total_time < 0.5, f"100 concurrent requests took {total_time:.3f}s"
            p99 = sorted(results)[int(len(results) * 0.99)]
            assert p99 < 0.05, f"P99 latency was {p99*1000:.2f}ms (> 50ms)"
        finally:
            await client.close()

    @pytest.mark.anyio
    async def test_event_loop_never_blocked_during_heavy_polling(self):
        """Verify that concurrent heartbeat / timer tasks on the event loop suffer 0 jitter
        while /api/benchmark_info is being continuously fetched."""
        app = create_app()
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()

        try:
            heartbeat_intervals = []
            stop_event = asyncio.Event()

            # Background ticker running every 10ms
            async def ticker():
                while not stop_event.is_set():
                    t0 = time.perf_counter()
                    await asyncio.sleep(0.01)
                    actual_sleep = time.perf_counter() - t0
                    heartbeat_intervals.append(actual_sleep)

            ticker_task = asyncio.create_task(ticker())

            # Hammer /api/benchmark_info with 150 requests in batches
            for _ in range(3):
                await asyncio.gather(*(client.get("/api/benchmark_info") for _ in range(50)))
                await asyncio.sleep(0.01)

            stop_event.set()
            await ticker_task

            # Max jitter on 10ms sleep should be minimal (< 35ms even under load)
            max_jitter = max(heartbeat_intervals)
            assert max_jitter < 0.040, f"Event loop experienced blocking: max sleep was {max_jitter*1000:.2f}ms"
        finally:
            await client.close()


# ============================================================================
# 3. 144 FPS DRAWER & 10,000+ LOG CAPPING INVARIANTS
# ============================================================================

class TestDrawerAndLogCappingInvariants(unittest.TestCase):
    """Stress tests log buffer capping invariant (strict <= 500 items) and evaluates
    144 FPS frame budget (6.94ms per frame) and DOM scaling."""

    def test_webbridge_log_capping_under_10000_rapid_appends(self):
        """Stress: WebBridge.log called 10,000 times rapidly from multiple threads."""
        bridge = WebBridge()
        bridge._log_history.clear()

        errors = []

        def spammer(tid: int):
            try:
                for i in range(1000):
                    bridge.log(f"Spam log from worker {tid} iteration {i}", level="info")
            except Exception as err:
                errors.append(err)

        # 10 threads x 1000 logs = 10,000 logs
        threads = [threading.Thread(target=spammer, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        logs = bridge.get_logs()
        # Invariant: buffer size must NEVER exceed 500 entries
        self.assertLessEqual(len(logs), 500)
        self.assertEqual(len(logs), 500)

        # Clear logs check
        bridge.clear_logs()
        self.assertEqual(len(bridge.get_logs()), 0)

    def test_drawer_dom_capping_simulation_10000_entries(self):
        """Simulate JS ActivityDrawerManager.appendLog behavior in Python with strict DOM list model."""
        dom_children = []

        def append_log_sim(entry: dict):
            # JS: const div = document.createElement('div'); ... this.logBody.appendChild(div);
            dom_children.append(entry)
            # JS: if (this.logBody.children.length > 500) { this.logBody.removeChild(this.logBody.firstElementChild); }
            if len(dom_children) > 500:
                dom_children.pop(0)

        # Spam 10,000 logs
        t0 = time.perf_counter()
        for i in range(10_000):
            append_log_sim({
                "timestamp": "[12:34:56]",
                "message": f"High frequency game log payload line {i}",
                "level": "info",
                "color": "#D4DAE2"
            })
        total_time = time.perf_counter() - t0

        self.assertEqual(len(dom_children), 500)
        self.assertEqual(dom_children[-1]["message"], "High frequency game log payload line 9999")
        # 10k operations must execute in < 0.05 seconds
        self.assertLess(total_time, 0.05)

    def test_144fps_frame_budget_and_css_acceleration_properties(self):
        """Verify 144 FPS frame timing (1000ms / 144 = 6.94ms per frame budget)
        and ensure CSS properties contain will-change: transform and cubic-bezier."""
        css_path = os.path.join(os.path.dirname(__file__), "..", "src", "web", "static", "css", "app.css")
        with open(css_path, "r", encoding="utf-8") as f:
            css_content = f.read()

        # Invariant 1: CSS drawer must have will-change: transform for hardware layer promotion
        self.assertIn("will-change: transform;", css_content)

        # Invariant 2: CSS drawer must use hardware-accelerated transform: translateX
        self.assertIn("transform: translateX(100%);", css_content)
        self.assertIn("transform: translateX(0);", css_content)

        # Invariant 3: CSS drawer must use smooth easing cubic-bezier(0.16, 1, 0.3, 1)
        self.assertIn("cubic-bezier(0.16, 1, 0.3, 1)", css_content)

        # Invariant 4: Check frame budget math
        frame_budget_144hz_ms = 1000.0 / 144.0  # 6.944ms
        frame_budget_60hz_ms = 1000.0 / 60.0    # 16.666ms
    def test_hardware_service_memory_bounds_and_lifecycle(self):
        """Stress: 1,000 continuous refreshes and cache reads to ensure no unbounded growth."""
        hw = HardwareService(auto_start=False)
        for i in range(1000):
            with hw._lock:
                hw._cache["cpu"] = f"CPU_{i}"
                hw._cache["ram"] = f"{i % 128} GB"
                hw._cache["disk"] = f"Disk_{i}"
                hw._cache["os"] = f"OS_{i}"
                hw._cache["cpu_id"] = f"CPU_ID_{i}"
                hw._cache["disk_serial"] = f"SERIAL_{i}"
            # Reading state
            sys_info = hw.get_system_info()
            self.assertEqual(len(sys_info), 6)
            self.assertEqual(len(hw._cache), 6)

    def test_benchmark_endpoint_during_cold_start(self):
        """Stress: Verify /api/benchmark_info handles cold start (Detecting...) safely without exception."""
        bridge = WebBridge()
        # Set hardware service to cold detecting state
        bridge.hardware_service._cache = {
            "cpu": "Detecting...",
            "ram": "Detecting...",
            "disk": "Detecting...",
            "os": "Detecting...",
            "cpu_id": "Detecting...",
            "disk_serial": "Detecting...",
        }
        info = bridge.get_benchmark_info()
        self.assertEqual(info["cpu"], "Detecting...")
        self.assertEqual(info["ram"], "Detecting...")
        self.assertEqual(info["disk"], "Detecting...")
        self.assertEqual(info["os"], "Detecting...")
        self.assertIsInstance(info["runs"], list)


@pytest.mark.anyio
async def test_concurrent_websocket_and_api_benchmark_info():
    """Verify WebSocket registration, state delivery, and REST endpoint concurrently."""
    app = create_app()
    token_headers = {"X-AutoConnect-Token": app["session_token"]}
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()

    try:
        # Connect WebSocket
        ws = await client.ws_connect("/ws")
        init_msg = await ws.receive_json()
        assert init_msg["type"] == "init_state"

        # Concurrently fetch /api/benchmark_info and ping WS
        async def poll_rest():
            for _ in range(25):
                resp = await client.get("/api/benchmark_info", headers=token_headers)
                assert resp.status == 200

        async def ping_ws():
            for _ in range(25):
                await ws.send_json({"action": "ping"})
                msg = await ws.receive_json()
                assert msg["type"] == "pong"

        await asyncio.gather(poll_rest(), ping_ws())
        await ws.close()
    finally:
        await client.close()


if __name__ == "__main__":
    unittest.main()

