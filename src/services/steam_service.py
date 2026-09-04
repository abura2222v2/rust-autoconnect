import json
import os
import re
import urllib.request
import winreg
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Optional


def build_connect_url(endpoint: str, app_id: int = 252490) -> str:
    """Return the only game-launch integration used by AutoConnect."""
    if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}:\d{1,5}", endpoint):
        raise ValueError("invalid endpoint")
    return f"steam://run/{app_id}//+connect {endpoint}"


def dispatch_launch(endpoint: str, app_id: int) -> None:
    """Send Rust to `endpoint`, launching the game first if it isn't running.

    Verified empirically against a real Rust client (2026-09-04): the same
    steam://run//+connect URL works in BOTH states - it launches a closed
    Rust and connects it, and it also redirects an already-running client
    that sits in the main menu (the log answers with "Connecting: ip:port"
    about a second later). An earlier measurement (2026-09-03) concluded the
    opposite and made this function refuse to send anything while Rust was
    open; that reading was wrong - it was taken while the log-path bug was
    still present, so the client's reaction was being written to a file
    nobody was reading.
    """
    url = build_connect_url(endpoint, app_id)
    if os.name == "nt":
        os.startfile(url)
    else:
        import webbrowser
        webbrowser.open(url)

def get_steam_path() -> str:
    steam_path = r"C:\Program Files (x86)\Steam"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            steam_path, _ = winreg.QueryValueEx(key, "SteamPath")
    except Exception:
        pass
    return steam_path

FORCE_WIPE_ZONE = ZoneInfo("Europe/London")
FORCE_WIPE_UTC_HOUR = 18


def next_force_wipe_at(now_utc: Optional[datetime] = None) -> datetime:
    """Return the next official force-wipe instant in UTC.

    The application uses the published global schedule: first Thursday at
    18:00 UTC.  The displayed local time is derived from this instant.
    """
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    local = now.astimezone(timezone.utc)
    first = local.replace(day=1, hour=FORCE_WIPE_UTC_HOUR, minute=0, second=0, microsecond=0)
    first += timedelta(days=(3 - first.weekday()) % 7)
    if first.astimezone(timezone.utc) <= now:
        next_month = (local.replace(day=28) + timedelta(days=4)).replace(day=1)
        first = next_month.replace(hour=FORCE_WIPE_UTC_HOUR, minute=0, second=0, microsecond=0)
        first += timedelta(days=(3 - first.weekday()) % 7)
    return first.astimezone(timezone.utc)


def relevant_force_wipe_at(now_utc: Optional[datetime] = None) -> datetime:
    """Return this month's wipe while its post-wipe watch window is active."""
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    local = now.astimezone(timezone.utc)
    current = local.replace(day=1, hour=FORCE_WIPE_UTC_HOUR, minute=0, second=0, microsecond=0)
    current += timedelta(days=(3 - current.weekday()) % 7)
    current_utc = current.astimezone(timezone.utc)
    if current_utc + timedelta(minutes=30) >= now:
        return current_utc
    return next_force_wipe_at(now)


def force_wipe_poll_interval(now_utc: Optional[datetime] = None) -> float:
    """Return the low-cost build-check cadence around force wipe."""
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    upcoming = relevant_force_wipe_at(now)
    if upcoming - timedelta(minutes=30) <= now <= upcoming + timedelta(minutes=30):
        return 60.0
    return 1800.0


def is_force_wipe_window(now_utc: Optional[datetime] = None) -> bool:
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    upcoming = relevant_force_wipe_at(now)
    return upcoming - timedelta(minutes=30) <= now <= upcoming + timedelta(minutes=30)


@dataclass(frozen=True)
class BuildInfo:
    buildid: Optional[str]
    server_date: Optional[str]

def parse_acf_buildid(content: str) -> Optional[str]:
    """Extract buildid string from appmanifest content."""
    match = re.search(r'"buildid"\s+"(\d+)"', content)
    return match.group(1) if match else None

def find_local_manifest_path() -> Optional[Path]:
    """Locate local appmanifest_252490.acf file."""
    steam_path = r"C:\Program Files (x86)\Steam"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            steam_path, _ = winreg.QueryValueEx(key, "SteamPath")
    except Exception:
        pass
        
    manifest_path = Path(steam_path) / "steamapps" / "appmanifest_252490.acf"
    if manifest_path.exists():
        return manifest_path

    lib_folders = Path(steam_path) / "steamapps" / "libraryfolders.vdf"
    if lib_folders.exists():
        try:
            with open(lib_folders, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    match = re.search(r'"path"\s+"([^"]+)"', line)
                    if match:
                        p = match.group(1).replace("\\\\", "\\")
                        test_path = Path(p) / "steamapps" / "appmanifest_252490.acf"
                        if test_path.exists():
                            return test_path
        except Exception:
            pass

    return None

def get_local_buildid() -> Optional[str]:
    """Read local appmanifest and return buildid."""
    manifest_path = find_local_manifest_path()
    if manifest_path and manifest_path.exists():
        try:
            with open(manifest_path, "r", encoding="utf-8", errors="ignore") as f:
                return parse_acf_buildid(f.read())
        except Exception:
            pass
    return None

def fetch_latest_build_info() -> BuildInfo:
    try:
        req = urllib.request.Request("https://api.steamcmd.net/v1/info/252490", headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5.0) as res:
            data = json.loads(res.read().decode('utf-8'))
            buildid = data['data']['252490']['depots']['branches']['public']['buildid']
            return BuildInfo(str(buildid), res.headers.get("Date"))
    except Exception:
        return BuildInfo(None, None)


def fetch_latest_buildid() -> Optional[str]:
    """Compatibility wrapper for callers that only need the build id."""
    return fetch_latest_build_info().buildid


def open_steam_downloads() -> bool:
    """Ask Steam to show its Downloads page without launching Rust."""
    try:
        url = "steam://open/downloads"
        if os.name == "nt":
            os.startfile(url)
        else:
            import webbrowser
            webbrowser.open(url)
        return True
    except OSError:
        return False

def find_rust_install_path() -> Optional[str]:
    """Auto-detect Rust installation path via Steam registry and library folders."""
    steam_path = r"C:\Program Files (x86)\Steam"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            steam_path, _ = winreg.QueryValueEx(key, "SteamPath")
    except Exception:
        pass

    # Check default steamapps/common/Rust
    rust_path = Path(steam_path) / "steamapps" / "common" / "Rust"
    if rust_path.exists() and (rust_path / "RustClient.exe").exists():
        return str(rust_path)

    # Check all Steam library folders
    lib_folders = Path(steam_path) / "steamapps" / "libraryfolders.vdf"
    if lib_folders.exists():
        try:
            with open(lib_folders, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    match = re.search(r'"path"\s+"([^"]+)"', line)
                    if match:
                        p = match.group(1).replace("\\\\", "\\")
                        test_path = Path(p) / "steamapps" / "common" / "Rust"
                        if test_path.exists() and (test_path / "RustClient.exe").exists():
                            return str(test_path)
        except Exception:
            pass

    return None
