"""Client for the public benchmark API.

The desktop application never receives a Supabase service key and cannot write
directly to benchmark tables. A deployed Edge Function owns validation and
aggregation.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from ..core.logger import app_logger
from ..core.public_config import get_public_config


class LeaderboardService:
    def __init__(self) -> None:
        self.last_error: Optional[str] = None

    @property
    def api_url(self) -> str:
        return get_public_config()["BENCHMARK_API_URL"].rstrip("/")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_url)

    def _request(self, request: urllib.request.Request, timeout: float = 5.0) -> tuple[int, bytes]:
        if not self.is_configured:
            raise RuntimeError("Leaderboard API is not configured")
            
        public_key = get_public_config().get("SUPABASE_PUBLISHABLE_KEY", "")
        if public_key:
            if not request.has_header("apikey"):
                request.add_header("apikey", public_key)
            if not request.has_header("Authorization"):
                request.add_header("Authorization", f"Bearer {public_key}")
                
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.getcode(), response.read()

    def _set_error(self, error: Exception) -> None:
        if isinstance(error, urllib.error.HTTPError):
            try:
                body = error.read().decode("utf-8")
                self.last_error = json.loads(body).get("error", f"HTTP {error.code}")
            except Exception:
                self.last_error = f"HTTP {error.code}"
        else:
            self.last_error = type(error).__name__
        app_logger.warning(f"Leaderboard request failed: {self.last_error}")

    def submit_run(self, run: dict[str, Any]) -> bool:
        self.last_error = None
        if not self.is_configured:
            self.last_error = "Leaderboard API is not configured"
            return False
        allowed = {
            "id", "installation_id", "configuration_key", "cpu", "storage", "storage_bus",
            "benchmark_version", "time_to_menu", "demo_load_time",
        }
        payload = {key: value for key, value in run.items() if key in allowed}
        try:
            request = urllib.request.Request(
                f"{self.api_url}/benchmark/submit",
                data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            status, _ = self._request(request)
            return status in (200, 201, 202)
        except (OSError, ValueError, urllib.error.URLError) as error:
            self._set_error(error)
            return False

    def fetch_configurations(
        self, limit: int = 100, offset: int = 0, search_query: str = "", sort_order: str = "asc"
    ) -> list[dict[str, Any]]:
        self.last_error = None
        if not self.is_configured:
            self.last_error = "Leaderboard API is not configured"
            return []
        params = {
            "limit": str(max(1, min(int(limit), 100))),
            "offset": str(max(0, int(offset))),
            "sort": "desc" if sort_order == "desc" else "asc",
        }
        if search_query.strip():
            params["q"] = search_query.strip()[:100]
        try:
            request = urllib.request.Request(
                f"{self.api_url}/benchmark/configurations?{urllib.parse.urlencode(params)}"
            )
            _, body = self._request(request)
            payload = json.loads(body.decode("utf-8"))
            rows = payload.get("items", []) if isinstance(payload, dict) else []
            return [row for row in rows if isinstance(row, dict)]
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as error:
            self._set_error(error)
            return []

    def fetch_configuration_detail(self, configuration_key: str) -> dict[str, Any] | None:
        self.last_error = None
        if not self.is_configured or not configuration_key:
            self.last_error = "Leaderboard API is not configured"
            return None
        try:
            request = urllib.request.Request(
                f"{self.api_url}/benchmark/configurations/{urllib.parse.quote(configuration_key, safe='')}"
            )
            _, body = self._request(request)
            payload = json.loads(body.decode("utf-8"))
            return payload if isinstance(payload, dict) else None
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as error:
            self._set_error(error)
            return None


leaderboard_service = LeaderboardService()
