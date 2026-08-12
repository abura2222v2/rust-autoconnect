"""Compatibility facade for the backend-managed wipe schedule cache.

Provider lookup belongs to the server side.  This module intentionally makes
no direct requests to BattleMetrics or scraping sites from player machines.
"""

from typing import Any, Dict, Optional

from .server_intelligence_service import server_intelligence_service

class WipeIntelligenceService:
    def get_wipe_schedule(self, ip_port: str) -> Optional[Dict[str, Any]]:
        cached = server_intelligence_service.get_schedule(ip_port)
        if cached.wipe_at:
            return {"wipe_at": cached.wipe_at, "source": cached.source}
        return None

wipe_intelligence_service = WipeIntelligenceService()
