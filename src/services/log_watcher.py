import os
import asyncio
import threading
import concurrent.futures
from pathlib import Path
from typing import Callable, Optional

from ..core.config import config
from ..core.logger import app_logger


class LogWatcher:
    """Read appended Rust log lines from a cancellable asyncio background task."""

    def __init__(self, on_disconnect: Callable[[str], None], on_error: Callable[[str], None],
                 on_event: Optional[Callable[[str], None]] = None, 
                 on_queue_update: Optional[Callable[[int], None]] = None,
                 seek_end: bool = True,
                 target_log_path: Optional[Path] = None):
        self.on_disconnect = on_disconnect
        self.on_error = on_error
        self.on_event = on_event
        self.on_queue_update = on_queue_update
        self.seek_end = seek_end
        self.target_log_path = target_log_path
        self.is_monitoring = False
        self._task: Optional[asyncio.Task] = None
        self._stop_event = threading.Event()
        self._task_future = None
        self._last_error = ""

    def start(self, loop=None) -> None:
        if self.is_monitoring:
            return
        self._stop_event.clear()
        self.is_monitoring = True
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                pass
        if loop is not None:
            try:
                running_loop = asyncio.get_running_loop()
            except RuntimeError:
                running_loop = None
            if loop is running_loop:
                self._task = loop.create_task(self._watch_loop(), name="rust-log-watcher")
            else:
                self._task_future = asyncio.run_coroutine_threadsafe(self._watch_loop(), loop)
        else:
            raise RuntimeError("LogWatcher requires an event loop.")

    def stop(self) -> None:
        self.is_monitoring = False
        self._stop_event.set()
        if self._task:
            loop = self._task.get_loop()
            if loop.is_closed():
                pass
            else:
                loop.call_soon_threadsafe(self._task.cancel)
        if getattr(self, '_task_future', None):
            self._task_future.cancel()

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

    async def _watch_loop(self) -> None:
        try:
            log_path: Optional[Path] = None
            while self.is_monitoring and not self._stop_event.is_set():
                if not log_path or not log_path.exists():
                    log_path = self._resolve_log_path()
                    if not log_path.exists():
                        for _ in range(10):
                            if self._stop_event.is_set(): break
                            await asyncio.sleep(0.1)
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
                                for _ in range(5):
                                    if self._stop_event.is_set(): break
                                    await asyncio.sleep(0.1)
                                continue
                            buffer = (buffer + new_data)[-1024 * 1024:]
                            lines = buffer.split("\n")
                            buffer = lines.pop()
                            for line in lines:
                                if self._stop_event.is_set() or not self.is_monitoring:
                                    return
                                if self.on_event:
                                    self.on_event(line)
                                if self.on_queue_update:
                                    # Typical rust logs: "Position 15 of 200" or "[Queue] Position: 15 / 200"
                                    # Fallback simple search: look for "queue" and some number pattern
                                    line_lower = line.lower()
                                    if "queue" in line_lower or "position" in line_lower:
                                        import re
                                        m = re.search(r'(?:position|queue)[^\d]+(\d+)(?:\s*(?:of|/)\s*(\d+))?', line_lower)
                                        if m:
                                            try:
                                                pos = int(m.group(1))
                                                self.on_queue_update(pos)
                                            except ValueError:
                                                pass
                                if any(keyword in line for keyword in config.DISCONNECT_KEYWORDS) or (" " not in line.strip() and "|0x" in line and line.rstrip().endswith("|-1")):
                                    self.is_monitoring = False
                                    self.on_disconnect(line.strip())
                                    return
                except OSError as error:
                    self._report_error(error)
                    for _ in range(10):
                            if self._stop_event.is_set(): break
                            await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        finally:
            self.is_monitoring = False
