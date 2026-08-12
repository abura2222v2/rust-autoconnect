"""Monotonic UTC clock anchored by a recent HTTPS server-time sample."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import threading
import time
from typing import Optional


class NetworkClock:
    """Keep scheduling independent from later changes to the Windows clock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._anchor_utc: Optional[datetime] = None
        self._anchor_monotonic = 0.0
        self._system_offset_seconds: Optional[float] = None

    def observe_http_date(self, value: object, *, received_monotonic: Optional[float] = None) -> bool:
        if not isinstance(value, str):
            return False
        try:
            server_time = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return False
        if server_time.tzinfo is None:
            server_time = server_time.replace(tzinfo=timezone.utc)
        server_time = server_time.astimezone(timezone.utc)
        received = time.monotonic() if received_monotonic is None else received_monotonic
        system_time = datetime.now(timezone.utc)
        with self._lock:
            self._anchor_utc = server_time
            self._anchor_monotonic = received
            self._system_offset_seconds = (server_time - system_time).total_seconds()
        return True

    def now(self) -> datetime:
        with self._lock:
            anchor = self._anchor_utc
            elapsed = time.monotonic() - self._anchor_monotonic
        if anchor is None:
            return datetime.now(timezone.utc)
        return anchor + timedelta(seconds=max(0.0, elapsed))

    @property
    def is_synced(self) -> bool:
        with self._lock:
            return self._anchor_utc is not None

    @property
    def system_offset_seconds(self) -> Optional[float]:
        with self._lock:
            return self._system_offset_seconds
