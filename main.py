import customtkinter as ctk
import os
import sys
from src.app import AppController

def _load_env_file(path: str) -> None:
    """Load a simple local env file without logging values."""
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
    # Frozen builds must read configuration beside the executable, not from
    # PyInstaller's temporary extraction directory.
    if getattr(sys, "frozen", False):
        base_path = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    _load_env_file(os.path.join(base_path, ".env.local"))

def main():
    _load_local_environment()
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = AppController()
    app.mainloop()

if __name__ == "__main__":
    main()
