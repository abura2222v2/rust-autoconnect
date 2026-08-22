# -*- coding: utf-8 -*-
"""Hardware service for detecting system specs silently in the background with thread-safe caching."""

import json
import logging
import os
import platform
import re
import subprocess
import threading
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("rust_autoconnect.hardware")


class HardwareService:
    """Manages non-blocking hardware specification detection and caching."""

    COMPOSITE_PS_SCRIPT = (
        "$ErrorActionPreference = 'SilentlyContinue'; "
        "$cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1).Name; "
        "if (-not $cpu) { $cpu = (Get-WmiObject Win32_Processor | Select-Object -First 1).Name }; "
        "$ramBytes = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory; "
        "if (-not $ramBytes) { $ramBytes = (Get-WmiObject Win32_ComputerSystem).TotalPhysicalMemory }; "
        "$disk = (Get-PhysicalDisk | Select-Object -First 1).FriendlyName; "
        "if (-not $disk) { $disk = (Get-CimInstance Win32_DiskDrive | Select-Object -First 1).Model }; "
        "$os = (Get-CimInstance Win32_OperatingSystem).Caption; "
        "if (-not $os) { $os = (Get-WmiObject Win32_OperatingSystem).Caption }; "
        "@{cpu=$cpu; ramBytes=$ramBytes; disk=$disk; os=$os} | ConvertTo-Json -Compress"
    )

    def __init__(self, auto_start: bool = True):
        self._lock = threading.Lock()
        self._is_ready = threading.Event()
        self._cache: Dict[str, str] = {
            "cpu": "Detecting...",
            "ram": "Detecting...",
            "disk": "Detecting...",
            "os": "Detecting...",
            "cpu_id": "Detecting...",
            "disk_serial": "Detecting...",
        }
        self._storage_cache: Dict[str, Tuple[str, str]] = {}
        self._worker_thread: Optional[threading.Thread] = None
        self._last_updated: float = 0.0

        if auto_start:
            self.start_background_scan()

    def start_background_scan(self) -> None:
        """Starts background daemon worker thread to detect hardware specifications."""
        with self._lock:
            if self._worker_thread and self._worker_thread.is_alive():
                return
            self._worker_thread = threading.Thread(
                target=self._background_worker,
                daemon=True,
                name="HardwareServiceDaemon",
            )
            self._worker_thread.start()

    def _background_worker(self) -> None:
        """Worker thread entrypoint that executes the hardware queries and updates cache."""
        try:
            self._query_hardware_specs()
        except Exception as err:
            logger.debug(f"Background hardware query encountered an error: {err}")
        finally:
            self._is_ready.set()

    def _run_ps(self, cmd: str) -> str:
        """Execute a PowerShell command safely with timeout and no console window."""
        if os.name != "nt":
            return "Unknown"
        try:
            res = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", cmd],
                timeout=5.0,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            return res.decode("utf-8", errors="ignore").strip()
        except subprocess.TimeoutExpired:
            return "Unknown"
        except Exception:
            return "Unknown"

    def _query_hardware_specs(self) -> None:
        """Query CPU, RAM, Disk, OS via single composite PowerShell query on Windows or fallback."""
        cpu = ""
        ram = ""
        disk = ""
        os_name = ""

        if os.name == "nt":
            raw = self._run_ps(self.COMPOSITE_PS_SCRIPT)
            if raw and raw != "Unknown":
                try:
                    payload = json.loads(raw)
                    if isinstance(payload, dict):
                        cpu = str(payload.get("cpu") or "").strip()
                        ram_bytes = payload.get("ramBytes")
                        if ram_bytes:
                            try:
                                gb = round(int(ram_bytes) / (1024**3))
                                ram = f"{gb} GB"
                            except Exception:
                                pass
                        disk = str(payload.get("disk") or "").strip()
                        os_name = str(payload.get("os") or "").strip()
                except Exception as json_err:
                    logger.debug(f"Failed to parse composite PowerShell JSON: {json_err}")

        # Fallback for missing/non-Windows fields
        if not cpu or cpu == "Unknown":
            cpu = self._fallback_cpu()
        if not ram or ram == "Unknown":
            ram = self._fallback_ram()
        if not disk or disk == "Unknown":
            disk = self._fallback_disk()
        if not os_name or os_name == "Unknown":
            os_name = self._fallback_os()

        with self._lock:
            self._cache["cpu"] = cpu or "Unknown"
            self._cache["ram"] = ram or "Unknown"
            self._cache["disk"] = disk or "Unknown"
            self._cache["os"] = os_name or "Unknown"
            self._cache["cpu_id"] = cpu or "Unknown"
            self._cache["disk_serial"] = disk or "Unknown"
            self._last_updated = time.time()

    def _fallback_cpu(self) -> str:
        try:
            val = platform.processor().strip()
            if val:
                return val
            val = platform.machine().strip()
            if val:
                return val
        except Exception:
            pass
        return "Unknown"

    def _fallback_ram(self) -> str:
        try:
            import psutil
            mem = psutil.virtual_memory()
            gb = round(mem.total / (1024**3))
            return f"{gb} GB"
        except Exception:
            pass
        return "Unknown"

    def _fallback_disk(self) -> str:
        try:
            import psutil
            parts = psutil.disk_partitions()
            if parts:
                return parts[0].device
        except Exception:
            pass
        return "Unknown"

    def _fallback_os(self) -> str:
        try:
            sys_name = platform.system()
            release = platform.release()
            if sys_name:
                return f"{sys_name} {release}".strip()
        except Exception:
            pass
        return "Unknown"

    def is_ready(self) -> bool:
        """Return True if background hardware detection has completed at least once."""
        return self._is_ready.is_set()

    def wait_until_ready(self, timeout: Optional[float] = None) -> bool:
        """Wait for background calculation to complete. Useful in tests and sync startup."""
        return self._is_ready.wait(timeout=timeout)

    def refresh(self) -> None:
        """Synchronously trigger hardware re-detection (or run in thread)."""
        self._query_hardware_specs()

    # =========================================================================
    # FAST NON-BLOCKING GETTERS (< 5ms SLA)
    # =========================================================================

    def get_cpu_info(self) -> str:
        with self._lock:
            return self._cache.get("cpu", "Detecting...")

    def get_ram_info(self) -> str:
        with self._lock:
            return self._cache.get("ram", "Detecting...")

    def get_disk_info(self) -> str:
        with self._lock:
            return self._cache.get("disk", "Detecting...")

    def get_os_info(self) -> str:
        with self._lock:
            return self._cache.get("os", "Detecting...")

    def get_cpu_id(self) -> str:
        with self._lock:
            return self._cache.get("cpu_id", "Detecting...")

    def get_disk_serial(self) -> str:
        with self._lock:
            return self._cache.get("disk_serial", "Detecting...")

    def get_system_info(self) -> Dict[str, str]:
        with self._lock:
            return dict(self._cache)

    def get_benchmark_storage(self, rust_path: str) -> Tuple[str, str]:
        """Return model and bus type for volume containing Rust, with caching."""
        if os.name != "nt":
            return "Unknown", "Unknown"
        drive_match = re.match(r"^([A-Za-z]):", os.path.abspath(rust_path))
        if not drive_match:
            return "Unknown", "Unknown"
        drive_letter = drive_match.group(1).upper()

        with self._lock:
            if drive_letter in self._storage_cache:
                return self._storage_cache[drive_letter]

        script = (
            f"$partition = Get-Partition -DriveLetter '{drive_letter}' -ErrorAction Stop; "
            "$disk = Get-Disk -Number $partition.DiskNumber -ErrorAction Stop; "
            "@{model=$disk.FriendlyName; bus=$disk.BusType} | ConvertTo-Json -Compress"
        )
        raw = self._run_ps(script)
        try:
            payload = json.loads(raw)
            model = str(payload.get("model") or "Unknown")
            bus = str(payload.get("bus") or "Unknown")
            res = (model, bus)
            with self._lock:
                self._storage_cache[drive_letter] = res
            return res
        except (TypeError, ValueError, json.JSONDecodeError):
            return "Unknown", "Unknown"


hardware_service = HardwareService(auto_start=True)
