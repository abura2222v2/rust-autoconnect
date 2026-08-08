import os
import time
import threading
from typing import Callable
from ..core.config import config
from .process_monitor import process_monitor

class LogWatcher:
    def __init__(self, on_disconnect: Callable[[str], None], on_error: Callable[[str], None]):
        self.on_disconnect = on_disconnect
        self.on_error = on_error
        self.is_monitoring = False
        self._thread = None
        self.grace_period_until = 0

    def start(self):
        if self.is_monitoring:
            return
        self.is_monitoring = True
        self.grace_period_until = time.time() + 20.0 # BUG-02: 20s grace period for launch
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.is_monitoring = False

    def _watch_loop(self):
        log_path = config.rust_log_path
        if not log_path.exists():
            return
            
        try:
            where = log_path.stat().st_size
        except Exception as e:
            self.on_error(f"Failed to read log size: {e}")
            self.is_monitoring = False
            return

        while self.is_monitoring:
            try:
                current_size = log_path.stat().st_size
                if current_size == where:
                    # File didn't grow
                    if time.time() > self.grace_period_until:
                        if not process_monitor.is_rust_running():
                            # Crash detected
                            self.on_disconnect("Crash detected")
                            break
                    time.sleep(1.0) # Optimized from 0.5s to 1s
                    continue
                elif current_size < where:
                    # Log truncated
                    where = current_size
                    continue
                    
                with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    f.seek(where)
                    new_data = f.read()
                    where = f.tell()
                    
                    for kw in config.DISCONNECT_KEYWORDS:
                        if kw in new_data:
                            self.on_disconnect(f"Keyword: {kw}")
                            return # Stop monitoring, caller handles reconnect
                            
            except Exception as e:
                # BUG-08: Log error instead of silent pass
                self.on_error(f"Log read error: {e}")
                time.sleep(1.0)
