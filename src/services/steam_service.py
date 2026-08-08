import json
import os
import re
import urllib.request
import winreg
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

def is_force_wipe_window(now_utc: Optional[datetime] = None) -> bool:
    """
    Force wipe is first Thursday of the month, ~18:00 UTC.
    We consider the window to be from Thursday 12:00 UTC to Friday 12:00 UTC.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    
    first_day = now_utc.replace(day=1)
    days_to_thursday = (3 - first_day.weekday() + 7) % 7
    first_thursday = first_day + timedelta(days=days_to_thursday)
    window_start = first_thursday.replace(hour=12, minute=0, second=0, microsecond=0)
    window_end = window_start + timedelta(days=1)
    return window_start <= now_utc <= window_end

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

def fetch_latest_buildid() -> Optional[str]:
    """Fetch latest Rust buildid from SteamCMD API."""
    try:
        req = urllib.request.Request("https://api.steamcmd.net/v1/info/252490", headers={'User-Agent': 'Mozilla/5.0'})
        res = urllib.request.urlopen(req, timeout=5.0)
        data = json.loads(res.read().decode('utf-8'))
        return data['data']['252490']['depots']['branches']['public']['buildid']
    except Exception:
        return None
