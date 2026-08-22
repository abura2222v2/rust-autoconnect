# -*- coding: utf-8 -*-
"""Rust AutoConnect Modern Web Desktop Launcher."""
import os
import sys
from src.web.server import run_web_app

def _load_env_file(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key:
                os.environ[key] = value.strip()

def _load_local_environment() -> None:
    if getattr(sys, "frozen", False):
        base_path = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    _load_env_file(os.path.join(base_path, ".env.local"))

def main():
    _load_local_environment()
    print("Launching Rust AutoConnect Web UI (144 FPS Hardware Accelerated)...")
    run_web_app(open_window=True)

if __name__ == "__main__":
    main()
