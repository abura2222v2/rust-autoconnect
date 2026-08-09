import socket
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Tuple

import a2s

from .logger import app_logger


class A2SClient:
    """Bounded A2S server probe with a per-server successful-port cache."""

    def __init__(self, timeout: float = 0.6, offsets: tuple[int, ...] = (0, 15, 5, 10, 3, 1, 123)):
        self.timeout = timeout
        self.offsets = offsets
        self._cached_ports: dict[tuple[str, int], int] = {}
        self._lock = threading.Lock()

    def _query(self, ip: str, port: int, stop_event: Optional[threading.Event]) -> Optional[tuple[str, int, int]]:
        if stop_event and stop_event.is_set():
            return None
        try:
            info = a2s.info((ip, port), timeout=self.timeout)
            return info.server_name, info.max_players, port
        except (a2s.exceptions.BrokenMessageError, OSError, socket.timeout, ValueError):
            return None
        except Exception as error:
            app_logger.warning(f"A2S query failed for {ip}:{port}: {type(error).__name__}")
            return None

    def check_server_alive(
        self, ip: str, base_port: int, stop_event: Optional[threading.Event] = None
    ) -> Tuple[bool, str, int, int]:
        """Return ``(alive, name, max_players, actual_query_port)``.

        A cached query port is tried first. Remaining allowed offsets are probed
        concurrently with bounded workers and abandoned after the first answer.
        """
        if not 1 <= base_port <= 65535 or (stop_event and stop_event.is_set()):
            return False, "", 0, base_port

        key = (ip, base_port)
        with self._lock:
            cached_port = self._cached_ports.get(key)

        if cached_port:
            cached_result = self._query(ip, cached_port, stop_event)
            if cached_result:
                name, max_players, query_port = cached_result
                return True, name, max_players, query_port

        ports = [
            base_port + offset
            for offset in self.offsets
            if 1 <= base_port + offset <= 65535 and base_port + offset != cached_port
        ]
        if not ports:
            return False, "", 0, base_port

        executor = ThreadPoolExecutor(max_workers=min(4, len(ports)), thread_name_prefix="a2s-query")
        futures = {executor.submit(self._query, ip, port, stop_event): port for port in ports}
        try:
            for future in as_completed(futures):
                if stop_event and stop_event.is_set():
                    break
                result = future.result()
                if result:
                    name, max_players, query_port = result
                    with self._lock:
                        self._cached_ports[key] = query_port
                    return True, name, max_players, query_port
        finally:
            for future in futures:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)

        return False, "", 0, base_port


a2s_client = A2SClient()
