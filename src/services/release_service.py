"""Fetch public application version metadata without uploading local data."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Optional

from ..core.logger import app_logger


RELEASES_URL = "https://api.github.com/repos/abura2222v2/rust-autoconnect/releases/latest"
# This must match the release tag used for the distributed installer.
LOCAL_VERSION = "v0.6.1"


def is_newer_version(candidate: str, current: str) -> bool:
    """Return whether a GitHub release tag is newer than the installed version."""
    def parse(value: str) -> tuple[int, ...] | None:
        match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", value.strip())
        if not match:
            return None
        return tuple(int(part) for part in match.group(1).split("."))

    candidate_parts = parse(candidate)
    current_parts = parse(current)
    if candidate_parts is None or current_parts is None:
        return False
    width = max(len(candidate_parts), len(current_parts))
    return candidate_parts + (0,) * (width - len(candidate_parts)) > current_parts + (0,) * (width - len(current_parts))


class ReleaseService:
    def fetch_latest_version(self, timeout: float = 3.0) -> Optional[str]:
        request = urllib.request.Request(
            RELEASES_URL,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "RustAutoConnect"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as error:
            app_logger.info(f"GitHub release check unavailable: {type(error).__name__}")
            return None
        tag_name = payload.get("tag_name") if isinstance(payload, dict) else None
        return tag_name.strip()[:64] if isinstance(tag_name, str) and tag_name.strip() else None


release_service = ReleaseService()
