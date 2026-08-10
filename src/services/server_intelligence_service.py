"""Client for the optional server-side wipe schedule cache.

The desktop client never contacts schedule providers directly.  This keeps
provider tokens out of the executable and lets many players share one cached
answer for the same server.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional

from ..core.public_config import get_public_config
from ..core.logger import app_logger


@dataclass(frozen=True)
class WipeSchedule:
    wipe_at: Optional[int] = None
    source: str = ""
    confidence: str = "unknown"


class ServerIntelligenceService:
    """Read shared schedules and optionally report local availability."""

    def __init__(self) -> None:
        public_config = get_public_config()
        self.api_url = public_config["SERVER_INTELLIGENCE_URL"].rstrip("/")
        self.public_key = public_config["SUPABASE_PUBLISHABLE_KEY"]
        self._cache: dict[str, tuple[float, WipeSchedule]] = {}
        self._cache_lock = threading.Lock()

    @property
    def is_configured(self) -> bool:
        return bool(self.api_url and self.public_key)

    def _request(self, path: str, data: Optional[dict] = None) -> Optional[dict]:
        if not self.is_configured:
            return None
        body = json.dumps(data).encode("utf-8") if data is not None else None
        request = urllib.request.Request(
            f"{self.api_url}{path}",
            data=body,
            method="POST" if body is not None else "GET",
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "apikey": self.public_key,
                "authorization": f"Bearer {self.public_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=4) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return payload if isinstance(payload, dict) else None
        except (OSError, ValueError, urllib.error.URLError) as error:
            app_logger.info(f"Server intelligence request failed: {type(error).__name__}")
            return None

    def get_schedule(self, endpoint: str) -> WipeSchedule:
        now = time.monotonic()
        with self._cache_lock:
            cached = self._cache.get(endpoint)
        if cached and now - cached[0] < 300:
            return cached[1]

        encoded = urllib.parse.urlencode({"endpoint": endpoint})
        payload = self._request(f"/server-intelligence/schedule?{encoded}") or {}
        wipe_at = payload.get("wipe_at")
        schedule = WipeSchedule(
            wipe_at=wipe_at if isinstance(wipe_at, int) and wipe_at > 0 else None,
            source=payload.get("source", "") if isinstance(payload.get("source"), str) else "",
            confidence=payload.get("confidence", "unknown") if isinstance(payload.get("confidence"), str) else "unknown",
        )
        with self._cache_lock:
            self._cache[endpoint] = (now, schedule)
        return schedule

    def report_available(self, endpoint: str, wipe_at: Optional[int] = None, source: Optional[str] = None) -> None:
        """Send one opt-in, aggregate-only availability report."""
        payload = {"endpoint": endpoint}
        if wipe_at:
            payload["wipe_at"] = wipe_at
            if source:
                payload["source"] = source
        self._request("/server-intelligence/availability", payload)





server_intelligence_service = ServerIntelligenceService()

