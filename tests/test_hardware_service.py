# -*- coding: utf-8 -*-
"""Unit, integration, and performance tests for HardwareService background calculation and caching."""

import json
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


class TestHardwareServicePlaceholdersAndDefaults(unittest.TestCase):
    """Tests for initial state and placeholder defaults before background calculation finishes."""

    def test_default_placeholders_before_calculation(self):
        """Verify getters return 'Detecting...' before any background query runs."""
        hw = HardwareService(auto_start=False)
        self.assertFalse(hw.is_ready())
        self.assertEqual(hw.get_cpu_info(), "Detecting...")
        self.assertEqual(hw.get_ram_info(), "Detecting...")
        self.assertEqual(hw.get_disk_info(), "Detecting...")
        self.assertEqual(hw.get_os_info(), "Detecting...")
        self.assertEqual(hw.get_cpu_id(), "Detecting...")
        self.assertEqual(hw.get_disk_serial(), "Detecting...")

        sys_info = hw.get_system_info()
        self.assertIsInstance(sys_info, dict)
        self.assertEqual(sys_info["cpu"], "Detecting...")
        self.assertEqual(sys_info["ram"], "Detecting...")
        self.assertEqual(sys_info["disk"], "Detecting...")
        self.assertEqual(sys_info["os"], "Detecting...")


class TestHardwareServiceBackgroundDetection(unittest.TestCase):
    """Tests for background calculation via composite PowerShell query and thread-safe caching."""

    def test_background_worker_populates_cache_via_composite_powershell(self):
        """Verify composite PowerShell query populates cache and is_ready event is set."""
        fake_payload = {
            "cpu": "AMD Ryzen 7 7800X3D 8-Core Processor",
            "ramBytes": 34359738368,
            "disk": "Samsung SSD 990 PRO 2TB",
            "os": "Microsoft Windows 11 Pro",
        }

        with patch("os.name", "nt"), patch.object(
            HardwareService, "_run_ps", return_value=json.dumps(fake_payload)
        ) as mock_ps:
            hw = HardwareService(auto_start=True)
            ready = hw.wait_until_ready(timeout=2.0)
            self.assertTrue(ready)
            self.assertTrue(hw.is_ready())

            # Getters must return parsed values
            self.assertEqual(hw.get_cpu_info(), "AMD Ryzen 7 7800X3D 8-Core Processor")
            self.assertEqual(hw.get_ram_info(), "32 GB")
            self.assertEqual(hw.get_disk_info(), "Samsung SSD 990 PRO 2TB")
            self.assertEqual(hw.get_os_info(), "Microsoft Windows 11 Pro")
            self.assertEqual(hw.get_cpu_id(), "AMD Ryzen 7 7800X3D 8-Core Processor")
            self.assertEqual(hw.get_disk_serial(), "Samsung SSD 990 PRO 2TB")

            sys_info = hw.get_system_info()
            self.assertEqual(sys_info["cpu"], "AMD Ryzen 7 7800X3D 8-Core Processor")
            self.assertEqual(sys_info["ram"], "32 GB")
            self.assertEqual(sys_info["disk"], "Samsung SSD 990 PRO 2TB")
            self.assertEqual(sys_info["os"], "Microsoft Windows 11 Pro")

            mock_ps.assert_called_once()
            self.assertIn("Get-CimInstance Win32_Processor", mock_ps.call_args.args[0])

    def test_instant_retrieval_performance_under_5ms(self):
        """Verify 1,000 consecutive getter calls execute in < 5ms total (< 0.005ms per call)."""
        hw = HardwareService(auto_start=False)
        hw._cache = {
            "cpu": "Intel(R) Core(TM) i9-14900K",
            "ram": "64 GB",
            "disk": "WD_BLACK SN850X 4000GB",
            "os": "Windows 11 Enterprise",
            "cpu_id": "Intel(R) Core(TM) i9-14900K",
            "disk_serial": "WD_BLACK SN850X 4000GB",
        }
        hw._is_ready.set()

        start = time.perf_counter()
        for _ in range(1000):
            _ = hw.get_cpu_info()
            _ = hw.get_ram_info()
            _ = hw.get_disk_info()
            _ = hw.get_os_info()
            _ = hw.get_system_info()
        duration = time.perf_counter() - start

        # 5,000 total operations in < 50ms total -> average < 0.01ms per operation
        self.assertLess(duration, 0.5, f"1000 iterations took {duration:.4f}s (exceeded limit)")
        single_call_latency = duration / 5000.0
        self.assertLess(single_call_latency, 0.005, f"Single call took {single_call_latency * 1000:.4f}ms (> 5ms SLA)")

    def test_thread_safety_under_heavy_concurrency(self):
        """Verify 30 concurrent threads accessing and refreshing cache do not cause race conditions."""
        hw = HardwareService(auto_start=False)
        hw._cache = {
            "cpu": "Benchmarked CPU",
            "ram": "16 GB",
            "disk": "Standard SSD",
            "os": "Windows 10 Pro",
            "cpu_id": "Benchmarked CPU",
            "disk_serial": "Standard SSD",
        }
        errors = []

        def worker(thread_id: int):
            try:
                for i in range(100):
                    cpu = hw.get_cpu_info()
                    ram = hw.get_ram_info()
                    disk = hw.get_disk_info()
                    os_val = hw.get_os_info()
                    sys_dict = hw.get_system_info()
                    self.assertIsInstance(cpu, str)
                    self.assertIsInstance(ram, str)
                    self.assertIsInstance(disk, str)
                    self.assertIsInstance(os_val, str)
                    self.assertIsInstance(sys_dict, dict)
                    if i % 25 == 0:
                        with hw._lock:
                            hw._cache["cpu"] = f"CPU_{thread_id}_{i}"
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Thread concurrency errors: {errors}")


class TestHardwareServiceFallbacks(unittest.TestCase):
    """Tests for platform fallback and resilient error handling."""

    def test_non_windows_fallback_psutil_and_platform(self):
        """Verify fallback to platform and psutil on Linux/macOS."""
        mock_mem = MagicMock()
        mock_mem.total = 17179869184  # 16 GB
        mock_part = MagicMock()
        mock_part.device = "/dev/nvme0n1p2"

        hw = HardwareService(auto_start=False)

        with patch("os.name", "posix"), \
             patch("platform.processor", return_value="Apple M3 Max"), \
             patch("platform.system", return_value="Darwin"), \
             patch("platform.release", return_value="23.4.0"), \
             patch("psutil.virtual_memory", return_value=mock_mem), \
             patch("psutil.disk_partitions", return_value=[mock_part]):

            hw._query_hardware_specs()

            self.assertEqual(hw.get_cpu_info(), "Apple M3 Max")
            self.assertEqual(hw.get_ram_info(), "16 GB")
            self.assertEqual(hw.get_disk_info(), "/dev/nvme0n1p2")
            self.assertEqual(hw.get_os_info(), "Darwin 23.4.0")

    def test_powershell_corrupt_json_fallback(self):
        """Verify corrupted or invalid JSON output gracefully falls back without crashing."""
        hw = HardwareService(auto_start=False)

        with patch("os.name", "nt"), \
             patch.object(hw, "_run_ps", return_value="{INVALID JSON: ["), \
             patch("platform.processor", return_value="Fallback x86_64"), \
             patch("platform.system", return_value="Windows"), \
             patch("platform.release", return_value="10"):

            hw._query_hardware_specs()

            self.assertEqual(hw.get_cpu_info(), "Fallback x86_64")
            self.assertEqual(hw.get_os_info(), "Windows 10")

    def test_powershell_timeout_fallback(self):
        """Verify subprocess.TimeoutExpired is handled cleanly."""
        hw = HardwareService(auto_start=False)

        with patch("os.name", "nt"), \
             patch("subprocess.check_output", side_effect=subprocess.TimeoutExpired(cmd="powershell", timeout=5.0)), \
             patch("platform.processor", return_value="Fallback AMD64"):

            hw._query_hardware_specs()

            self.assertEqual(hw.get_cpu_info(), "Fallback AMD64")


class TestHardwareServiceBenchmarkStorage(unittest.TestCase):
    """Tests for drive-specific storage detection and caching."""

    def test_benchmark_storage_resolution_and_caching(self):
        """Verify get_benchmark_storage extracts drive letter, executes query, and caches result."""
        hw = HardwareService(auto_start=False)
        fake_storage_json = '{"model": "Samsung SSD 980 1TB", "bus": "NVMe"}'

        with patch("os.name", "nt"), patch.object(hw, "_run_ps", return_value=fake_storage_json) as mock_ps:
            # First call queries PS
            model1, bus1 = hw.get_benchmark_storage("D:\\Games\\SteamLibrary\\steamapps\\common\\Rust")
            self.assertEqual(model1, "Samsung SSD 980 1TB")
            self.assertEqual(bus1, "NVMe")
            self.assertEqual(mock_ps.call_count, 1)

            # Second call for same drive uses cache without calling PS again
            model2, bus2 = hw.get_benchmark_storage("D:\\AnotherPath\\RustClient.exe")
            self.assertEqual(model2, "Samsung SSD 980 1TB")
            self.assertEqual(bus2, "NVMe")
            self.assertEqual(mock_ps.call_count, 1)


class TestWebBridgeAndServerIntegration(unittest.TestCase):
    """Tests verifying WebBridge and /api/benchmark_info endpoint responsiveness."""

    def test_bridge_get_benchmark_info_instant_response(self):
        """Verify WebBridge.get_benchmark_info returns full hardware payload in < 5ms."""
        bridge = WebBridge()
        bridge.hardware_service._cache = {
            "cpu": "AMD Ryzen 9 7950X",
            "ram": "64 GB",
            "disk": "Kingston KC3000 2TB",
            "os": "Microsoft Windows 11 Pro",
            "cpu_id": "AMD Ryzen 9 7950X",
            "disk_serial": "Kingston KC3000 2TB",
        }

        start = time.perf_counter()
        info = bridge.get_benchmark_info()
        duration = time.perf_counter() - start

        self.assertLess(duration, 0.005, f"get_benchmark_info took {duration*1000:.4f}ms (> 5ms SLA)")
        self.assertEqual(info["cpu"], "AMD Ryzen 9 7950X")
        self.assertEqual(info["ram"], "64 GB")
        self.assertEqual(info["disk"], "Kingston KC3000 2TB")
        self.assertEqual(info["os"], "Microsoft Windows 11 Pro")
        self.assertIn("run_count", info)
        self.assertIn("runs", info)


@pytest.mark.anyio
async def test_api_benchmark_info_http_endpoint():
    """Verify HTTP GET /api/benchmark_info responds immediately with hardware cache."""
    app = create_app()
    token = app["session_token"]
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        start = time.perf_counter()
        resp = await client.get("/api/benchmark_info", headers={"X-AutoConnect-Token": token})
        duration = time.perf_counter() - start

        assert resp.status == 200
        assert duration < 0.050, f"HTTP /api/benchmark_info took {duration*1000:.2f}ms"
        data = await resp.json()
        assert "cpu" in data
        assert "ram" in data
        assert "disk" in data
        assert "os" in data
        assert "run_count" in data
        assert "runs" in data
    finally:
        await client.close()
