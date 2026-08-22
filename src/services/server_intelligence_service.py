"""Client for the shared, server-side GameMonitoring cache.

The desktop client talks only to the project's Edge Function.  It never sends
provider credentials, scrapes web pages, or waits for a provider response
before it can begin its local A2S check.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from ..core.logger import app_logger
from ..core.public_config import get_public_config


@dataclass(frozen=True)
class ServerSnapshot:
    wipe_at: Optional[int] = None
    source: str = ""
    confidence: str = "unknown"
    online: Optional[bool] = None
    players: Optional[int] = None
    max_players: Optional[int] = None
    checked_at: Optional[datetime] = None
    fresh: bool = False
    status: str = "no_data"
    server_id: Optional[int] = None
    query_port: Optional[int] = None
    name: str = ""
    map_name: str = ""
    map_seed: Optional[int] = None
    map_size: Optional[int] = None
    map_revision: Optional[int] = None
    map_url: str = ""
    rustmaps_url: str = ""
    banner_url: str = ""
    version: str = ""
    fps: Optional[int] = None
    fps_avg: Optional[int] = None
    entities_count: Optional[int] = None
    country: str = ""
    city: str = ""
    description: str = ""
    website: str = ""
    links: tuple[str, ...] = ()
    last_wipe_at: Optional[int] = None
    pve: Optional[bool] = None


# Backwards-compatible name used by wipe_intelligence_service.
WipeSchedule = ServerSnapshot


class ServerIntelligenceService:
    """Read shared cache and register interest through the Edge Function."""

    def __init__(self) -> None:
        public_config = get_public_config()
        self.api_url = public_config["SERVER_INTELLIGENCE_URL"].rstrip("/")
        self.public_key = public_config["SUPABASE_PUBLISHABLE_KEY"]
        self._cache: dict[tuple[str, bool, Optional[int]], tuple[float, ServerSnapshot]] = {}
        self._cache_lock = threading.Lock()

    @property
    def is_configured(self) -> bool:
        return bool(self.api_url and self.public_key)

    def _request(self, path: str, data: Optional[dict] = None) -> Optional[dict]:
        if not self.is_configured:
            return None
        body = json.dumps(data).encode("utf-8") if data is not None else None
        request = urllib.request.Request(
            f"{self.api_url}{path}", data=body,
            method="POST" if body is not None else "GET",
            headers={
                "Accept": "application/json", "Content-Type": "application/json",
                "apikey": self.public_key, "Authorization": f"Bearer {self.public_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=4) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return payload if isinstance(payload, dict) else None
        except (OSError, ValueError, urllib.error.URLError) as error:
            app_logger.info(f"Server intelligence request failed: {type(error).__name__}")
            return None

    @staticmethod
    def _snapshot(payload: dict) -> ServerSnapshot:
        checked_at = payload.get("checked_at")
        try:
            parsed_checked_at = datetime.fromisoformat(checked_at.replace("Z", "+00:00")) if isinstance(checked_at, str) else None
        except ValueError:
            parsed_checked_at = None
        wipe_at = payload.get("wipe_at")
        def positive_int(*keys: str) -> Optional[int]:
            value = next((payload.get(key) for key in keys if payload.get(key) is not None), None)
            return value if isinstance(value, int) and value >= 0 else None

        def text(*keys: str, limit: int = 4096) -> str:
            value = next((payload.get(key) for key in keys if payload.get(key) is not None), None)
            return value.strip()[:limit] if isinstance(value, str) else ""

        return ServerSnapshot(
            wipe_at=wipe_at if isinstance(wipe_at, int) and wipe_at > 0 else None,
            source=payload.get("source", "") if isinstance(payload.get("source"), str) else "",
            confidence=payload.get("confidence", "unknown") if isinstance(payload.get("confidence"), str) else "unknown",
            online=payload.get("online") if isinstance(payload.get("online"), bool) else None,
            players=payload.get("players") if isinstance(payload.get("players"), int) and payload.get("players") >= 0 else None,
            max_players=payload.get("max_players") if isinstance(payload.get("max_players"), int) and payload.get("max_players") >= 0 else None,
            checked_at=parsed_checked_at,
            fresh=bool(payload.get("fresh")),
            status=text("status", limit=32) or "no_data",
            server_id=positive_int("server_id"), query_port=positive_int("query_port"),
            name=text("name", limit=160), map_name=text("map_name", "map", limit=160),
            map_seed=positive_int("map_seed", "seed"), map_size=positive_int("map_size"),
            map_revision=positive_int("map_revision"), map_url=text("map_url", limit=512),
            banner_url=text("banner_url", limit=512),
            version=text("version", limit=64), fps=positive_int("fps"), fps_avg=positive_int("fps_avg"),
            entities_count=positive_int("entities_count", "entity_count"), country=text("country", limit=80), city=text("city", limit=80),
            description=text("description"), website=text("website", limit=512),
            last_wipe_at=positive_int("last_wipe_at", "last_wipe"),
            pve=payload.get("pve") if isinstance(payload.get("pve"), bool) else None,
            links=tuple(item for item in payload.get("links", []) if isinstance(item, str) and len(item) <= 512) if isinstance(payload.get("links"), list) else (),
        )

    def observe_endpoint(
        self, endpoint: str, *, active: bool, query_port: Optional[int] = None, force_refresh: bool = False,
    ) -> ServerSnapshot:
        """Return shared cache while signalling active interest to the backend."""
        cache_key = (endpoint, active, query_port)
        now = time.monotonic()
        ttl = 55 if active else 300
        with self._cache_lock:
            cached = self._cache.get(cache_key)
        if cached and not force_refresh and now - cached[0] < ttl:
            return cached[1]
        body = {"endpoint": endpoint, "active": active}
        if isinstance(query_port, int) and 1 <= query_port <= 65535:
            body["query_port"] = query_port
        payload = self._request("/server-intelligence/observe", body) or {}
        snapshot = self._snapshot(payload)
        with self._cache_lock:
            self._cache[cache_key] = (now, snapshot)
        return snapshot

    def get_schedule(self, endpoint: str) -> ServerSnapshot:
        """Compatibility wrapper for callers that only need wipe scheduling."""
        return self.observe_endpoint(endpoint, active=False)

    def share_saved_endpoints(self, endpoints: list[str]) -> bool:
        safe_endpoints = [endpoint for endpoint in dict.fromkeys(endpoints) if isinstance(endpoint, str)][:20]
        if not safe_endpoints:
            return True
        response = self._request("/server-intelligence/share", {"endpoints": safe_endpoints})
        return bool(response and response.get("accepted"))

    def report_available(self, endpoint: str) -> None:
        self._request("/server-intelligence/availability", {"endpoint": endpoint})


server_intelligence_service = ServerIntelligenceService()
