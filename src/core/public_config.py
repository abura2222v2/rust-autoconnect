"""Public runtime configuration bundled with the application.

Only values that are safe to expose in source code and an executable belong
here.  Elevated Supabase credentials are intentionally not supported.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


DEFAULTS = {
    "SUPABASE_WS_URL": "wss://eznuyydoanefceqmqxqi.supabase.co/realtime/v1/websocket",
    "SUPABASE_PUBLISHABLE_KEY": "",
    "BENCHMARK_API_URL": "",
    "SERVER_INTELLIGENCE_URL": "",
}


def _assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "assets"
    return Path(__file__).resolve().parents[2] / "assets"


def get_public_config() -> dict[str, str]:
    """Return bundled public values, with optional local developer overrides."""
    values = dict(DEFAULTS)
    config_path = _assets_dir() / "public-config.json"
    try:
        data: Any = json.loads(config_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for key in values:
                if isinstance(data.get(key), str):
                    values[key] = data[key].strip()
    except (OSError, json.JSONDecodeError):
        pass

    # .env.local is a developer convenience only.  The legacy variable is
    # retained for existing local setups, but is never treated as a secret.
    for key in values:
        if os.environ.get(key):
            values[key] = os.environ[key].strip()
    if os.environ.get("SUPABASE_KEY") and not values["SUPABASE_PUBLISHABLE_KEY"]:
        values["SUPABASE_PUBLISHABLE_KEY"] = os.environ["SUPABASE_KEY"].strip()
    return values
