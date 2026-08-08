import os
import time
import threading
from typing import Callable
from ..core.config import config
from .process_monitor import process_monitor

class LogWatcher:
    def __init__(self, on_disconnect: Callable[[str], None], on_error: Callable[[str], None], on_event: Callable[[str], None] = None, seek_end: bool = True, target_log_path = None):
        self.on_disconnect = on_disconnect
        self.on_error = on_error
        self.on_event = on_event
        self.seek_end = seek_end
        self.target_log_path = target_log_path
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
        if self.target_log_path:
            log_path = self.target_log_path
        else:
            log_path = config.rust_log_path
            
            # Check alternate log path
            from ..core.history_store import history_store
            from pathlib import Path
            rust_path = history_store.get_rust_path()
            if rust_path:
                alt_log = Path(rust_path) / "output_log.txt"
                if alt_log.exists():
                    if not log_path.exists() or os.path.getmtime(alt_log) > os.path.getmtime(log_path):
                        log_path = alt_log
                        from ..core.logger import app_logger
                        app_logger.info(f"[*] Using alternate log file: {log_path}")

        # Wait for log file to exist
        while self.is_monitoring and not log_path.exists():
            time.sleep(1.0)
            
        if not self.is_monitoring:
            return
            
        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                if self.seek_end:
                    f.seek(0, 2)
                buffer = ""
                last_inode = os.stat(log_path).st_ino
                last_size = os.stat(log_path).st_size
                
                while self.is_monitoring:
                    try:
                        current_stat = os.stat(log_path)
                        if current_stat.st_ino != last_inode or current_stat.st_size < last_size:
                            f.close()
                            f = open(log_path, 'r', encoding='utf-8', errors='ignore')
                            buffer = ""
                        last_inode = current_stat.st_ino
                        last_size = current_stat.st_size
                    except FileNotFoundError:
                        time.sleep(1)
                        continue

                    new_data = f.read(4096)
                    if not new_data:
                        time.sleep(0.5)
                        continue
                        
                    buffer += new_data
                    
                    if len(buffer) > 1024 * 1024:
                        buffer = ""
                        
                    lines = buffer.split('\n')
                    buffer = lines.pop()
                    
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
