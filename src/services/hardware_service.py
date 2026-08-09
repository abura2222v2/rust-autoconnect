import subprocess
import os
import json
import re

class HardwareService:
    def _run_ps(self, cmd: str) -> str:
        if os.name != 'nt':
            return "Unknown"
        try:
            res = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", cmd],
                timeout=5.0,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return res.decode('utf-8', errors='ignore').strip()
        except subprocess.TimeoutExpired:
            return "Unknown"
        except Exception:
            return "Unknown"

    def get_cpu_info(self) -> str:
        return self._run_ps("(Get-WmiObject Win32_Processor).Name")

    def get_ram_info(self) -> str:
        try:
            bytes_str = self._run_ps("(Get-WmiObject Win32_ComputerSystem).TotalPhysicalMemory")
            gb = round(int(bytes_str) / (1024**3))
            return f"{gb} GB"
        except Exception:
            return "Unknown"

    def get_disk_info(self) -> str:
        return self._run_ps("(Get-PhysicalDisk | Select-Object -First 1).FriendlyName")
        
    def get_cpu_id(self) -> str:
        return self._run_ps("(Get-WmiObject Win32_Processor).Name")
        
    def get_disk_serial(self) -> str:
        return self._run_ps("(Get-PhysicalDisk | Select-Object -First 1).FriendlyName")

    def get_benchmark_storage(self, rust_path: str) -> tuple[str, str]:
        """Return only the model and bus type for the volume containing Rust."""
        if os.name != "nt":
            return "Unknown", "Unknown"
        drive_match = re.match(r"^([A-Za-z]):", os.path.abspath(rust_path))
        if not drive_match:
            return "Unknown", "Unknown"
        drive_letter = drive_match.group(1).upper()
        script = (
            f"$partition = Get-Partition -DriveLetter '{drive_letter}' -ErrorAction Stop; "
            "$disk = Get-Disk -Number $partition.DiskNumber -ErrorAction Stop; "
            "@{model=$disk.FriendlyName; bus=$disk.BusType} | ConvertTo-Json -Compress"
        )
        raw = self._run_ps(script)
        try:
            payload = json.loads(raw)
            return str(payload.get("model") or "Unknown"), str(payload.get("bus") or "Unknown")
        except (TypeError, ValueError, json.JSONDecodeError):
            return "Unknown", "Unknown"

hardware_service = HardwareService()
