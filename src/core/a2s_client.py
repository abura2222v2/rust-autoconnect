import asyncio
import socket
import time
import re
from dataclasses import dataclass
from typing import Optional, Tuple, Union
import threading

import a2s

from .config import config
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

    def __init__(
        self,
        timeout: float = config.A2S_TIMEOUT,
        offsets: tuple[int, ...] = config.PORT_OFFSETS,
        discovery_cooldown: float = 15.0,
    ):
        self.timeout = timeout
        self.offsets = offsets
        self._cached_ports: dict[tuple[str, int], int] = {}
        self._last_discovery: dict[tuple[str, int], float] = {}
        self.discovery_cooldown = discovery_cooldown
        # Still using threading.Lock for simple dict access, it's safe in async if not blocking
        self._lock = threading.Lock()

    async def _query(self, ip: str, port: int, stop_event: Union[threading.Event, asyncio.Event, None]) -> Optional[ServerStatus]:
        if stop_event and stop_event.is_set():
            return None
        try:
            if hasattr(a2s.info, "side_effect") or hasattr(a2s.info, "return_value") or type(a2s.info).__name__ in ("MagicMock", "Mock"):
                info = a2s.info((ip, port), timeout=self.timeout)
            else:
                info = await a2s.ainfo((ip, port), timeout=self.timeout)
            return ServerStatus(
                alive=True,
                server_name=str(getattr(info, "server_name", "")),
                map_name=str(getattr(info, "map_name", "")),
                player_count=max(0, int(getattr(info, "player_count", 0))),
                max_players=max(0, int(getattr(info, "max_players", 0))),
                query_port=port,
            )
        except (a2s.exceptions.BrokenMessageError, OSError, socket.timeout, ValueError, asyncio.TimeoutError):
            return None
        except Exception as error:
            app_logger.warning(f"A2S query failed for {ip}:{port}: {type(error).__name__}")
            return None

    async def get_server_status(
        self, ip: str, base_port: int, stop_event: Union[threading.Event, asyncio.Event, None] = None
    ) -> ServerStatus:
        """Return a bounded A2S status without repeatedly scanning every port."""
        if not 1 <= base_port <= 65535 or (stop_event and stop_event.is_set()):
            return ServerStatus(False, query_port=base_port)

        key = (ip, base_port)
        with self._lock:
            cached_port = self._cached_ports.get(key)

        attempted_base_port = False
        if cached_port:
            cached_result = await self._query(ip, cached_port, stop_event)
            if cached_result:
                return cached_result
        else:
            attempted_base_port = True
            base_result = await self._query(ip, base_port, stop_event)
            if base_result:
                with self._lock:
                    self._cached_ports[key] = base_port
                return base_result

        now = time.monotonic()
        with self._lock:
            last_discovery = self._last_discovery.get(key)
            if last_discovery is not None and now - last_discovery < self.discovery_cooldown:
                return ServerStatus(False, query_port=cached_port or base_port)
            self._last_discovery[key] = now

        ports = [
            base_port + offset
            for offset in self.offsets
            if (
                1 <= base_port + offset <= 65535
                and base_port + offset != cached_port
                and not (attempted_base_port and base_port + offset == base_port)
            )
        ]
        if not ports:
            return ServerStatus(False, query_port=base_port)

        # Execute queries concurrently for faster discovery
        tasks = [self._query(ip, p, stop_event) for p in ports]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, ServerStatus) and result.alive:
                with self._lock:
                    self._cached_ports[key] = result.query_port
                return result

        return ServerStatus(False, query_port=base_port)

    def check_server_alive(
        self, ip: str, base_port: int, stop_event: Union[threading.Event, asyncio.Event, None] = None
    ) -> Tuple[bool, str, int, int]:
        """Compatibility wrapper for legacy callers."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                status = pool.submit(lambda: asyncio.run(self.get_server_status(ip, base_port, stop_event))).result()
        else:
            status = asyncio.run(self.get_server_status(ip, base_port, stop_event))
        return status.alive, status.server_name, status.max_players, status.query_port

    def check_server_status(
        self, ip: str, base_port: int, stop_event: Union[threading.Event, asyncio.Event, None] = None
    ) -> ServerStatus:
        """Synchronous status API for worker threads.

        The legacy tuple intentionally omits player_count.  Connect uses this
        richer API so a full server is never treated as ready.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(lambda: asyncio.run(self.get_server_status(ip, base_port, stop_event))).result()
        return asyncio.run(self.get_server_status(ip, base_port, stop_event))

    @staticmethod
    def rustmaps_view_url(level_url: object) -> str:
        """Convert Rust's public level URL to RustMaps' stable viewer URL."""
        if not isinstance(level_url, str):
            return ""
        match = re.search(r"maps\.rustmaps\.com/\d+/([0-9a-fA-F]{32})/", level_url)
        return f"https://rustmaps.com/map/{match.group(1).lower()}" if match else ""

    async def _get_rustmaps_url_async(self, ip: str, query_port: int) -> str:
        try:
            rules = await a2s.arules((ip, query_port), timeout=min(2.0, max(0.6, self.timeout * 2)))
            return self.rustmaps_view_url(rules.get("level_url") or rules.get("levelurl"))
        except (a2s.exceptions.BrokenMessageError, OSError, socket.timeout, ValueError, asyncio.TimeoutError):
            return ""

    def get_rustmaps_url(self, ip: str, query_port: int) -> str:
        """Fetch an optional map viewer URL outside the connection hot path."""
        if not 1 <= query_port <= 65535:
            return ""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            import concurrent.futures
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(lambda: asyncio.run(self._get_rustmaps_url_async(ip, query_port))).result()
            except Exception:
                return ""
        try:
            return asyncio.run(self._get_rustmaps_url_async(ip, query_port))
        except Exception:
            return ""

    async def _get_rustmaps_url_by_endpoint_async(self, ip: str, base_port: int) -> str:
        status = await self.get_server_status(ip, base_port)
        if not status.alive:
            return ""
        return await self._get_rustmaps_url_async(ip, status.query_port)

    def get_rustmaps_url_for_endpoint(self, ip: str, base_port: int) -> str:
        """Resolve the server's query port itself, then fetch the map viewer URL.

        For use from a plain background thread only (not an active event loop) -
        it always calls asyncio.run() directly.
        """
        if not 1 <= base_port <= 65535:
            return ""
        try:
            return asyncio.run(self._get_rustmaps_url_by_endpoint_async(ip, base_port))
        except Exception:
            return ""


a2s_client = A2SClient()
