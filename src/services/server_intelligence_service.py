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


# Backwards-compatible name used by wipe_intelligence_service.
WipeSchedule = ServerSnapshot


class ServerIntelligenceService:
    """Read shared cache and register interest through the Edge Function."""

    def __init__(self) -> None:
        public_config = get_public_config()
        self.api_url = public_config["SERVER_INTELLIGENCE_URL"].rstrip("/")
        self.public_key = public_config["SUPABASE_PUBLISHABLE_KEY"]
        self._cache: dict[tuple[str, bool], tuple[float, ServerSnapshot]] = {}
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
        return ServerSnapshot(
            wipe_at=wipe_at if isinstance(wipe_at, int) and wipe_at > 0 else None,
            source=payload.get("source", "") if isinstance(payload.get("source"), str) else "",
            confidence=payload.get("confidence", "unknown") if isinstance(payload.get("confidence"), str) else "unknown",
            online=payload.get("online") if isinstance(payload.get("online"), bool) else None,
            players=payload.get("players") if isinstance(payload.get("players"), int) and payload.get("players") >= 0 else None,
            max_players=payload.get("max_players") if isinstance(payload.get("max_players"), int) and payload.get("max_players") >= 0 else None,
            checked_at=parsed_checked_at,
            fresh=bool(payload.get("fresh")),
        )

    def observe_endpoint(self, endpoint: str, *, active: bool) -> ServerSnapshot:
        """Return shared cache while signalling active interest to the backend."""
        cache_key = (endpoint, active)
        now = time.monotonic()
        ttl = 55 if active else 300
        with self._cache_lock:
            cached = self._cache.get(cache_key)
        if cached and now - cached[0] < ttl:
            return cached[1]
        payload = self._request("/server-intelligence/observe", {"endpoint": endpoint, "active": active}) or {}
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
