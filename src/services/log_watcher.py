import os
import threading
from pathlib import Path
from typing import Callable, Optional

from ..core.config import config
from ..core.logger import app_logger


class LogWatcher:
    """Read appended Rust log lines from a cancellable background thread."""

    def __init__(self, on_disconnect: Callable[[str], None], on_error: Callable[[str], None],
                 on_event: Optional[Callable[[str], None]] = None, seek_end: bool = True,
                 target_log_path: Optional[Path] = None):
        self.on_disconnect = on_disconnect
        self.on_error = on_error
        self.on_event = on_event
        self.seek_end = seek_end
        self.target_log_path = target_log_path
        self.is_monitoring = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread_finished = threading.Event()
        self._thread_finished.set()
        self._last_error = ""

    def start(self) -> None:
        with self._lock:
            if self.is_monitoring:
                return
            self._thread_finished.wait()
            self._stop_event.clear()
            self.is_monitoring = True
            self._thread_finished.clear()
            self._thread = threading.Thread(target=self._watch_loop, daemon=True, name="rust-log-watcher")
            self._thread.start()

    def stop(self) -> None:
        self.is_monitoring = False
        self._stop_event.set()

    def _resolve_log_path(self) -> Path:
        if self.target_log_path:
            return Path(self.target_log_path)
        log_path = config.rust_log_path
        from ..core.history_store import history_store
        rust_path = history_store.get_rust_path()
        if rust_path:
            alternate = Path(rust_path) / "output_log.txt"
            if alternate.exists() and (not log_path.exists() or alternate.stat().st_mtime > log_path.stat().st_mtime):
                app_logger.info(f"Using alternate log file: {alternate}")
                return alternate
        return log_path

    def _report_error(self, error: OSError) -> None:
        message = str(error)
        if message != self._last_error and "PermissionError" not in message and "[WinError 32]" not in message:
            self.on_error(message)
        self._last_error = message

    def _watch_loop(self) -> None:
        try:
            log_path: Optional[Path] = None
            while self.is_monitoring and not self._stop_event.is_set():
                if not log_path or not log_path.exists():
                    log_path = self._resolve_log_path()
                    if not log_path.exists():
                        self._stop_event.wait(1.0)
                        continue
                try:
                    with log_path.open("r", encoding="utf-8", errors="ignore") as file:
                        self._last_error = ""
                        if self.seek_end:
                            file.seek(0, os.SEEK_END)
                            self.seek_end = False
                        last_size = log_path.stat().st_size
                        buffer = ""
                        while self.is_monitoring and not self._stop_event.is_set():
                            try:
                                current_size = log_path.stat().st_size
                            except FileNotFoundError:
                                break
                            if current_size < last_size:
                                self.seek_end = True
                                break
                            last_size = current_size
                            new_data = file.read(4096)
                            if not new_data:
                                self._stop_event.wait(0.5)
                                continue
                            buffer = (buffer + new_data)[-1024 * 1024:]
                            lines = buffer.split("\n")
                            buffer = lines.pop()
                            for line in lines:
                                if self._stop_event.is_set() or not self.is_monitoring:
                                    return
                                if self.on_event:
                                    self.on_event(line)
                                if any(keyword in line for keyword in config.DISCONNECT_KEYWORDS) or (" " not in line.strip() and "|0x" in line and line.rstrip().endswith("|-1")):
                                    self.is_monitoring = False
                                    self.on_disconnect(line.strip())
                                    return
                except OSError as error:
                    self._report_error(error)
                    self._stop_event.wait(1.0)
        finally:
            self.is_monitoring = False
            self._thread_finished.set()
