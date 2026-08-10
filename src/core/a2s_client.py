import socket
import threading
import time
from dataclasses import dataclass
from typing import Optional, Tuple

import a2s

from .logger import app_logger


@dataclass(frozen=True)
class ServerStatus:
    alive: bool
    server_name: str = ""
    map_name: str = ""
    player_count: int = 0
    max_players: int = 0
    query_port: int = 0

    @property
    def has_join_capacity(self) -> bool:
        return self.max_players > 0 and self.player_count < self.max_players


class A2SClient:
    """Bounded A2S server probe with a per-server successful-port cache."""

    def __init__(self, timeout: float = 0.6, offsets: tuple[int, ...] = (0, 15, 2, 3, 1, 5, 10, 123), discovery_cooldown: float = 15.0):
        self.timeout = timeout
        self.offsets = offsets
        self._cached_ports: dict[tuple[str, int], int] = {}
        self._last_discovery: dict[tuple[str, int], float] = {}
        self.discovery_cooldown = discovery_cooldown
        self._lock = threading.Lock()

    def _query(self, ip: str, port: int, stop_event: Optional[threading.Event]) -> Optional[ServerStatus]:
        if stop_event and stop_event.is_set():
            return None
        try:
            info = a2s.info((ip, port), timeout=self.timeout)
            return ServerStatus(
                alive=True,
                server_name=str(getattr(info, "server_name", "")),
                map_name=str(getattr(info, "map_name", "")),
                player_count=max(0, int(getattr(info, "player_count", 0))),
                max_players=max(0, int(getattr(info, "max_players", 0))),
                query_port=port,
            )
        except (a2s.exceptions.BrokenMessageError, OSError, socket.timeout, ValueError):
            return None
        except Exception as error:
            app_logger.warning(f"A2S query failed for {ip}:{port}: {type(error).__name__}")
            return None

    def get_server_status(
        self, ip: str, base_port: int, stop_event: Optional[threading.Event] = None
    ) -> ServerStatus:
        """Return a bounded A2S status without repeatedly scanning every port.

        A cached query port is tried first. Remaining allowed offsets are probed
        concurrently only for initial discovery and after a discovery cooldown.
        """
        if not 1 <= base_port <= 65535 or (stop_event and stop_event.is_set()):
            return ServerStatus(False, query_port=base_port)

        key = (ip, base_port)
        with self._lock:
            cached_port = self._cached_ports.get(key)

        if cached_port:
            cached_result = self._query(ip, cached_port, stop_event)
            if cached_result:
                return cached_result
        else:
            base_result = self._query(ip, base_port, stop_event)
            if base_result:
                with self._lock:
                    self._cached_ports[key] = base_port
                return base_result

        now = time.monotonic()
        with self._lock:
            last_discovery = self._last_discovery.get(key)
            if last_discovery is not None and now - last_discovery < self.discovery_cooldown:
                # The cached port (or base port) was already queried above. Do not do a full
                # offset discovery scan on every turbo tick while discovery is cooling down.
                return ServerStatus(False, query_port=cached_port or base_port)
            self._last_discovery[key] = now

        ports = [
            base_port + offset
            for offset in self.offsets
            if 1 <= base_port + offset <= 65535 and base_port + offset != cached_port
        ]
        if not ports:
            return ServerStatus(False, query_port=base_port)

        # Discovery is infrequent and intentionally serial.  This keeps one
        # in-flight UDP query per endpoint and avoids leftover workers after a
        # fast successful response.
        for query_port in ports:
            if stop_event and stop_event.is_set():
                break
            result = self._query(ip, query_port, stop_event)
            if result:
                with self._lock:
                    self._cached_ports[key] = result.query_port
                return result

        return ServerStatus(False, query_port=base_port)

    def check_server_alive(
        self, ip: str, base_port: int, stop_event: Optional[threading.Event] = None
    ) -> Tuple[bool, str, int, int]:
        """Compatibility wrapper for legacy callers."""
        status = self.get_server_status(ip, base_port, stop_event)
        return status.alive, status.server_name, status.max_players, status.query_port


a2s_client = A2SClient()
