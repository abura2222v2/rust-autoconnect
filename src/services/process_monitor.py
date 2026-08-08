import psutil
import subprocess
import threading
import time

class ProcessMonitor:
    def __init__(self):
        self.cached_pid = None
        self._lock = threading.Lock()
        self._last_scan_time = 0.0

    def is_rust_running(self) -> bool:
        with self._lock:
            # Check cached PID first (O(1) OS check)
            if self.cached_pid is not None:
                try:
                    p = psutil.Process(self.cached_pid)
                    if p.name() == 'RustClient.exe':
                        return True
                    else:
                        self.cached_pid = None
                except Exception:
                    self.cached_pid = None
            
            current_time = time.time()
            if current_time - self._last_scan_time < 1.5:
                return self.cached_pid is not None
            self._last_scan_time = current_time
            
            # Slow path: iterate processes
            try:
                for p in psutil.process_iter(['name']):
                    if p.info['name'] == 'RustClient.exe':
                        self.cached_pid = p.pid
                        return True
            except Exception:
                pass
            
            return False
        
    def force_kill_rust(self):
        with self._lock:
            try:
                subprocess.run(["taskkill", "/F", "/IM", "RustClient.exe"], creationflags=subprocess.CREATE_NO_WINDOW)
            except Exception as e:
                from ..core.logger import app_logger
                app_logger.error(f"Failed to kill Rust: {e}")
            self.cached_pid = None

process_monitor = ProcessMonitor()
