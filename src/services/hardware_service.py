import subprocess
import os

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

hardware_service = HardwareService()
