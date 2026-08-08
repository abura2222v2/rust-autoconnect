import psutil
import subprocess
import threading
import time

class ProcessMonitor:
    def __init__(self):
        self.cached_pid = None
        self._lock = threading.Lock()

    def is_rust_running(self) -> bool:
        with self._lock:
            # Check cached PID first (O(1) OS check)
            if self.cached_pid is not None:
                try:
                    if psutil.pid_exists(self.cached_pid):
                        return True
                    else:
                        self.cached_pid = None # Process died
                except Exception:
                    self.cached_pid = None
            
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
        try:
            subprocess.run('taskkill /F /IM RustClient.exe', shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception:
            pass

process_monitor = ProcessMonitor()
