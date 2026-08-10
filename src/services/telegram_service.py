import json
import os
import random
import uuid
import urllib.request
import urllib.error
from typing import Optional

from ..core.config import config
from ..core.public_config import get_public_config

class TelegramService:
    def __init__(self):
        self.data_file = config.appdata_dir / "telegram.json"
        self._load()
        # Initialize client_id if not present
        if not getattr(self, "client_id", None):
            self.client_id = str(uuid.uuid4())
            self._save()

    def _load(self):
        self.client_id = None
        self.link_code = None
        if self.data_file.exists():
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.client_id = data.get("client_id")
                    self.link_code = data.get("link_code")
            except Exception:
                pass

    def _save(self):
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.data_file, "w", encoding="utf-8") as f:
            json.dump({
                "client_id": self.client_id,
                "link_code": self.link_code
            }, f)

    def generate_link_code(self) -> str:
        """Generates a 4-digit code and attempts to register it with Supabase if possible."""
        self.link_code = str(random.randint(1000, 9999))
        self._save()
        # Note: in a fully integrated environment, we would also insert this client_id + link_code
        # into the Supabase database. For now, since we only have public HTTP keys,
        # we expect the Supabase table `telegram_links` to have Row Level Security allowing anonymous INSERTS.
        try:
            public_config = get_public_config()
            supabase_url = public_config.get("SERVER_INTELLIGENCE_URL", "").replace("/functions/v1", "/rest/v1/telegram_links")
            supabase_key = public_config.get("SUPABASE_PUBLISHABLE_KEY", "")
            
            if supabase_url and supabase_key:
                req = urllib.request.Request(
                    supabase_url,
                    data=json.dumps({"client_id": self.client_id, "link_code": self.link_code}).encode("utf-8"),
                    headers={
                        "apikey": supabase_key,
                        "Authorization": f"Bearer {supabase_key}",
                        "Content-Type": "application/json",
                        "Prefer": "resolution=merge-duplicates"
                    },
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=5):
                    pass
        except Exception as e:
            # Silently fail if Supabase is not configured yet
            pass
            
        return self.link_code

    def get_threshold(self) -> int:
        return 5

    def notify_queue(self, position: int, server_name: str) -> bool:
        """Insert notification into Supabase which triggers the Edge Function."""
        if not self.client_id:
            return False
            
        try:
            public_config = get_public_config()
            supabase_url = public_config.get("SERVER_INTELLIGENCE_URL", "").replace("/functions/v1", "/rest/v1/tg_notifications")
            supabase_key = public_config.get("SUPABASE_PUBLISHABLE_KEY", "")
            
            if not supabase_url or not supabase_key:
                return False

            msg = f"Готовься! Ты {position}-й в очереди на сервер {server_name}."
            
            req = urllib.request.Request(
                supabase_url,
                data=json.dumps({
                    "client_id": self.client_id,
                    "message": msg
                }).encode("utf-8"),
                headers={
                    "apikey": supabase_key,
                    "Authorization": f"Bearer {supabase_key}",
                    "Content-Type": "application/json"
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=5):
                return True
        except Exception as e:
            return False

telegram_service = TelegramService()
