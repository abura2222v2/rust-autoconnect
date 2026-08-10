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


class BattleMetricsAPIClient:
    """Client for fetching server metrics and schedule from BattleMetrics API."""

    def __init__(self, api_token: Optional[str] = None) -> None:
        self.api_token = api_token

    def get_server_info(self, endpoint: str, port: Optional[int] = None, timeout: float = 5.0) -> Optional[dict]:
        """Query BattleMetrics for server info by endpoint or IP:port.

        Args:
            endpoint: Server IP or 'IP:port' string.
            port: Optional port if not included in endpoint.
            timeout: Request timeout in seconds.

        Returns:
            Dict containing players, maxPlayers, status, rust_wipe_time, etc., or None on failure.
        """
        if ":" not in endpoint and port is not None:
            search_query = f"{endpoint}:{port}"
        else:
            search_query = endpoint

        url = f"https://api.battlemetrics.com/servers?filter[search]={search_query}&game=rust"

        headers = {
            "Accept": "application/json",
            "User-Agent": "RustAutoConnect/1.0",
        }
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"

        request = urllib.request.Request(url, headers=headers, method="GET")

        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw_data = response.read().decode("utf-8")
                payload = json.loads(raw_data)
                if not isinstance(payload, dict) or "data" not in payload:
                    return None
                data_list = payload.get("data")
                if not isinstance(data_list, list) or len(data_list) == 0:
                    return None

                attributes = data_list[0].get("attributes", {})
                if not isinstance(attributes, dict):
                    return None

                details = attributes.get("details", {})
                rust_wipe_time = details.get("rust_wipe_time") if isinstance(details, dict) else None

                return {
                    "players": attributes.get("players"),
                    "maxPlayers": attributes.get("maxPlayers"),
                    "status": attributes.get("status"),
                    "rust_wipe_time": rust_wipe_time,
                    "details": details if isinstance(details, dict) else {},
                    "attributes": attributes,
                }
        except urllib.error.HTTPError as error:
            app_logger.warning(f"BattleMetrics API HTTP error {error.code}: {error.reason}")
            return None
        except urllib.error.URLError as error:
            app_logger.warning(f"BattleMetrics API URL error: {error.reason}")
            return None
        except (TimeoutError, OSError) as error:
            app_logger.warning(f"BattleMetrics API timeout/OS error: {error}")
            return None
        except Exception as error:
            app_logger.warning(f"BattleMetrics API error: {error}")
            return None


class ServerIntelligenceWorker(threading.Thread):
    """Worker thread polling BattleMetrics API every 60 seconds for server status."""

    def __init__(
        self,
        endpoint: str,
        api_token: Optional[str] = None,
        api_client: Optional[BattleMetricsAPIClient] = None,
        poll_interval: float = 60.0,
    ) -> None:
        super().__init__(daemon=True)
        self.endpoint = endpoint
        self.api_client = api_client or BattleMetricsAPIClient(api_token=api_token)
        self.poll_interval = poll_interval
        self._latest_status: dict = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    @property
    def latest_status(self) -> dict:
        """Thread-safe access to the latest server status."""
        with self._lock:
            return dict(self._latest_status)

    @latest_status.setter
    def latest_status(self, value: dict) -> None:
        with self._lock:
            self._latest_status = dict(value) if value else {}

    def stop(self) -> None:
        """Signal the worker thread to stop."""
        self._stop_event.set()

    def poll_now(self) -> Optional[dict]:
        """Perform an immediate poll and return updated status."""
        status = self.api_client.get_server_info(self.endpoint)
        if status is not None:
            with self._lock:
                self._latest_status = status
        return self.latest_status

    def run(self) -> None:
        """Main thread loop polling the API at poll_interval seconds."""
        while not self._stop_event.is_set():
            self.poll_now()
            if self._stop_event.wait(self.poll_interval):
                break


server_intelligence_service = ServerIntelligenceService()

