"""Multi-source wipe intelligence fetcher."""

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

from ..core.logger import app_logger
from .server_intelligence_service import server_intelligence_service

class WipeIntelligenceService:
    def __init__(self):
        pass

    def _request(self, url: str) -> Optional[Dict[str, Any]]:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as response:
                payload = json.loads(response.read().decode('utf-8'))
                return payload if isinstance(payload, dict) else None
        except Exception as e:
            app_logger.info(f"Wipe fetcher request failed for {url}: {e}")
            return None

    def _fetch_just_wiped(self, ip_port: str) -> Optional[int]:
        # Example placeholder, no free direct IP search known for v1 without key
        return None

    def _fetch_battlemetrics(self, ip_port: str) -> Optional[int]:
        try:
            ip, port = ip_port.split(":")
            payload = self._request(f"https://api.battlemetrics.com/servers?filter[search]={ip}&filter[game]=rust")
            if not payload or "data" not in payload:
                return None
            for server in payload["data"]:
                attrs = server.get("attributes", {})
                if attrs.get("ip") == ip and str(attrs.get("port")) == port:
                    details = attrs.get("details", {})
                    rust_wipe = details.get("rust_last_wipe")
                    if rust_wipe:
                        import datetime
                        dt = datetime.datetime.strptime(rust_wipe[:19], "%Y-%m-%dT%H:%M:%S")
                        return int(dt.replace(tzinfo=datetime.timezone.utc).timestamp())
            return None
        except Exception as e:
            app_logger.info(f"BattleMetrics fetch failed: {e}")
            return None

    def get_wipe_schedule(self, ip_port: str) -> Optional[Dict[str, Any]]:
        # 1. Check Supabase Cache first
        cached = server_intelligence_service.get_schedule(ip_port)
        if cached and cached.wipe_at:
            return {"wipe_at": cached.wipe_at, "source": cached.source}

        # 2. Try BattleMetrics
        bm_wipe = self._fetch_battlemetrics(ip_port)
        if bm_wipe:
            threading.Thread(target=server_intelligence_service.report_available, args=(ip_port, bm_wipe, "battlemetrics"), daemon=True).start()
            return {"wipe_at": bm_wipe, "source": "battlemetrics"}

        # 3. Try JustWiped
        jw_wipe = self._fetch_just_wiped(ip_port)
        if jw_wipe:
            threading.Thread(target=server_intelligence_service.report_available, args=(ip_port, jw_wipe, "just-wiped"), daemon=True).start()
            return {"wipe_at": jw_wipe, "source": "just-wiped"}

        return None

wipe_intelligence_service = WipeIntelligenceService()
