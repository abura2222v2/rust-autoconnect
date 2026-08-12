"""Client for the optional Telegram Edge Function.

The desktop app never writes Supabase tables directly and never contains the
Telegram bot token.  A per-installation notification token can only send
events for the linked chat and is stored locally with the installation state.
"""

from __future__ import annotations

import json
import secrets
import string
import uuid
import urllib.error
import urllib.request
from typing import Optional

from ..core.config import config
from ..core.logger import app_logger
from ..core.public_config import get_public_config


class TelegramService:
    EVENT_NAMES = frozenset({"ready", "queue", "connected", "disconnect", "reconnect", "wipe", "swarm"})
    SUPPORTED_LOCALES = frozenset({"EN", "RU", "UK", "DE", "ES", "FR", "ZH"})

    def __init__(self):
        self.data_file = config.appdata_dir / "telegram.json"
        self._load()
        if not self.client_id:
            self.client_id = str(uuid.uuid4())
            self._save()

    def _load(self) -> None:
        self.client_id: Optional[str] = None
        self.link_code: Optional[str] = None
        self.notification_token: Optional[str] = None
        self.display_name: Optional[str] = None
        self.is_linked = False
        self.locale = "EN"
        if not self.data_file.exists():
            return
        try:
            with self.data_file.open("r", encoding="utf-8") as file:
                data = json.load(file)
            self.client_id = data.get("client_id") if isinstance(data.get("client_id"), str) else None
            self.link_code = data.get("link_code") if isinstance(data.get("link_code"), str) else None
            self.notification_token = data.get("notification_token") if isinstance(data.get("notification_token"), str) else None
            self.display_name = data.get("display_name") if isinstance(data.get("display_name"), str) else None
            self.is_linked = data.get("is_linked") is True
            saved_locale = data.get("locale")
            self.locale = saved_locale if saved_locale in self.SUPPORTED_LOCALES else "EN"
        except (OSError, ValueError, TypeError):
            app_logger.warning("Telegram link state could not be loaded")

    def _save(self) -> None:
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        with self.data_file.open("w", encoding="utf-8") as file:
            json.dump(
                {
                    "client_id": self.client_id,
                    "link_code": self.link_code,
                    "notification_token": self.notification_token,
                    "display_name": self.display_name,
                    "is_linked": self.is_linked,
                    "locale": self.locale,
                },
                file,
            )

    @staticmethod
    def _function_url(path: str) -> str:
        base = str(get_public_config().get("SERVER_INTELLIGENCE_URL", "")).rstrip("/")
        return f"{base}/telegram-bot/{path}" if base else ""

    def _request(self, path: str, payload: dict) -> Optional[dict]:
        url = self._function_url(path)
        public_key = str(get_public_config().get("SUPABASE_PUBLISHABLE_KEY", ""))
        if not url or not public_key:
            return None
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "apikey": public_key,
                "Authorization": f"Bearer {public_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=4) as response:
                data = json.loads(response.read().decode("utf-8"))
                return data if isinstance(data, dict) else None
        except (OSError, ValueError, urllib.error.URLError) as error:
            app_logger.info(f"Telegram service request failed: {type(error).__name__}")
            return None

    def generate_link_code(self, locale: str = "EN") -> Optional[str]:
        """Create a short-lived pairing code through the Edge Function."""
        self.locale = locale if locale in self.SUPPORTED_LOCALES else "EN"
        alphabet = string.ascii_uppercase + string.digits
        code = "".join(secrets.choice(alphabet) for _ in range(8))
        response = self._request("link", {"client_id": self.client_id, "code": code, "locale": self.locale})
        if not response or response.get("accepted") is not True:
            return None
        token = response.get("notification_token")
        if not isinstance(token, str) or not token:
            return None
        self.link_code = code
        self.is_linked = False
        self.notification_token = token
        self._save()
        return code

    def get_link_status(self) -> Optional[dict]:
        """Return the linked Telegram profile without exposing chat identifiers."""
        if not self.client_id or not self.notification_token:
            return {"linked": False, "display_name": None}
        response = self._request(
            "status",
            {"client_id": self.client_id, "notification_token": self.notification_token},
        )
        if not response or not isinstance(response.get("linked"), bool):
            return None
        display_name = response.get("display_name")
        self.display_name = display_name if isinstance(display_name, str) and display_name else None
        self.is_linked = response["linked"]
        if self.is_linked:
            self.link_code = None
        self._save()
        return {"linked": response["linked"], "display_name": self.display_name}

    def update_locale(self, locale: str) -> bool:
        """Keep the linked bot's messages and keyboard in the app language."""
        self.locale = locale if locale in self.SUPPORTED_LOCALES else "EN"
        self._save()
        if not self.client_id or not self.notification_token:
            return True
        response = self._request(
            "locale",
            {
                "client_id": self.client_id,
                "notification_token": self.notification_token,
                "locale": self.locale,
            },
        )
        return bool(response and response.get("accepted") is True)

    def unlink(self) -> bool:
        """Remove this installation's Telegram link and local notification token."""
        if not self.client_id or not self.notification_token:
            self.link_code = None
            self.display_name = None
            self.is_linked = False
            self._save()
            return True
        response = self._request(
            "unlink",
            {"client_id": self.client_id, "notification_token": self.notification_token},
        )
        if not response or response.get("accepted") is not True:
            return False
        self.link_code = None
        self.notification_token = None
        self.display_name = None
        self.is_linked = False
        self._save()
        return True

    def notify(self, event: str, server: str, details: Optional[dict] = None) -> bool:
        if event not in self.EVENT_NAMES or not self.client_id or not self.notification_token:
            return False
        payload = {
            "client_id": self.client_id,
            "notification_token": self.notification_token,
            "event": event,
            "server": str(server)[:253],
            "details": details or {},
        }
        response = self._request("notify", payload)
        return bool(response and response.get("accepted") is True)

    def notify_queue(
        self,
        position: int,
        server_name: str,
        *,
        level: int | None = None,
        queue_session_id: str | None = None,
    ) -> bool:
        details = {"position": max(0, int(position))}
        if isinstance(level, int) and level in {5, 30, 60, 90}:
            details["level"] = level
        if isinstance(queue_session_id, str) and len(queue_session_id) == 32 and queue_session_id.isalnum():
            details["queue_session_id"] = queue_session_id
        return self.notify("queue", server_name, details)


telegram_service = TelegramService()
