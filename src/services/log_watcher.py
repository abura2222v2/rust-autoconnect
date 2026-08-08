import os
import time
import threading
from typing import Callable
from ..core.config import config
from .process_monitor import process_monitor

class LogWatcher:
    def __init__(self, on_disconnect: Callable[[str], None], on_error: Callable[[str], None], on_event: Callable[[str], None] = None):
        self.on_disconnect = on_disconnect
        self.on_error = on_error
        self.on_event = on_event
        self.is_monitoring = False
        self._thread = None

    def start(self):
        if self.is_monitoring:
            return
        self.is_monitoring = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.is_monitoring = False

    def _watch_loop(self):
        log_path = config.rust_log_path
        # Wait for log file to exist
        while self.is_monitoring and not log_path.exists():
            time.sleep(1.0)
            
        if not self.is_monitoring:
            return
            
        try:
            with open(log_path, 'rb') as f:
                f.seek(0, 2)
                buffer = ""
                while self.is_monitoring:
                    new_data_bytes = f.read(4096)
                    if not new_data_bytes:
                        time.sleep(0.5)
                        continue
                        
                    try:
                        buffer += new_data_bytes.decode('utf-8', errors='ignore')
                    except Exception:
                        pass
                        
                    lines = buffer.split('\n')
                    buffer = lines.pop() # Keep the last incomplete line
                    
                    for line in lines:
                        if self.on_event:
                            self.on_event(line)
                            
                        if any(kw in line for kw in config.DISCONNECT_KEYWORDS):
                            reason = line.strip()
                            self.is_monitoring = False
                            self.on_disconnect(reason)
                            return
        except Exception as e:
            if self.is_monitoring:
                self.on_error(str(e))
