import json
import os
import shutil
import time
from pathlib import Path
from typing import Dict, List, Any
from .config import config

class HistoryStore:
    def __init__(self):
        self.data: Dict[str, Any] = {"lang": "RU", "history": [], "favorites": [], "auto_update": True, "minimize_to_tray": False, "rust_path": "", "swarm_enabled": True}
        self.load()

    def load(self):
        os.makedirs(config.appdata_dir, exist_ok=True)
        data_file = config.data_file

        old_data_file = Path("data.json")
        if old_data_file.exists() and not data_file.exists():
            try:
                shutil.copy2(old_data_file, data_file)
            except Exception:
                pass

        if data_file.exists():
            try:
                with open(data_file, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except json.JSONDecodeError:
                # Corrupted file handling (BUG-03 fix)
                corrupted_file = data_file.with_name(f"data.json.corrupted_{int(time.time())}")
                try:
                    shutil.copy2(data_file, corrupted_file)
                except Exception:
                    pass
                self.data = {"lang": "RU", "history": [], "favorites": [], "auto_update": True, "minimize_to_tray": False, "rust_path": ""}
            except Exception:
                pass
        elif Path("history.json").exists():
            try:
                with open("history.json", "r", encoding="utf-8") as f:
                    self.data["history"] = json.load(f)
            except Exception:
                pass

    def save(self):
        os.makedirs(config.appdata_dir, exist_ok=True)
        data_file = config.data_file
        tmp_file = data_file.with_suffix('.tmp')
        
        # Limit history to 20
        if "history" in self.data:
            self.data["history"] = self.data["history"][:20]

        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=4)
            # Atomic replace (BUG-03 fix)
            os.replace(tmp_file, data_file)
        except Exception:
            # If temp write fails, clean it up
            if tmp_file.exists():
                try:
                    os.remove(tmp_file)
                except:
                    pass

    def add_to_history(self, ip_port: str, name: str):
        history = self.data.get("history", [])
        history = [h for h in history if h["ip"] != ip_port]
        history.insert(0, {"ip": ip_port, "name": name, "added_at": int(time.time())})
        self.data["history"] = history
        self.save()
        
    def remove_from_history(self, ip_port: str):
        history = self.data.get("history", [])
        self.data["history"] = [h for h in history if h["ip"] != ip_port]
        self.save()

    def toggle_favorite(self, ip_port: str, name: str):
        favs = self.data.get("favorites", [])
        is_fav = any(f.get("ip") == ip_port for f in favs)
        if is_fav:
            favs = [f for f in favs if f.get("ip") != ip_port]
        else:
            favs.append({"name": name, "ip": ip_port})
        self.data["favorites"] = favs
        self.save()

    def update_server_name(self, ip_port: str, new_name: str):
        for h in self.data.get("history", []):
            if h.get("ip") == ip_port:
                h["name"] = new_name
        for f in self.data.get("favorites", []):
            if f.get("ip") == ip_port:
                f["name"] = new_name
        self.save()

    def get_history(self) -> List[Dict[str, Any]]:
        return self.data.get("history", [])

    def get_favorites(self) -> List[Dict[str, Any]]:
        return self.data.get("favorites", [])

    def get_lang(self) -> str:
        return self.data.get("lang", "RU")

    def set_lang(self, code: str):
        self.data["lang"] = code
        self.save()

    def get_auto_update(self) -> bool:
        return self.data.get("auto_update", True)

    def set_auto_update(self, val: bool):
        self.data["auto_update"] = val
        self.save()

    def get_minimize_to_tray(self) -> bool:
        return self.data.get("minimize_to_tray", False)

    def set_minimize_to_tray(self, val: bool):
        self.data["minimize_to_tray"] = val
        self.save()

    def get_rust_path(self) -> str:
        return self.data.get("rust_path", "")

    def get_swarm_enabled(self) -> bool:
        return self.data.get("swarm_enabled", True)

    def set_swarm_enabled(self, val: bool):
        self.data["swarm_enabled"] = val
        self.save()

    def set_rust_path(self, val: str):
        self.data["rust_path"] = val
        self.save()
        
    def get_armed_server(self) -> str:
        return self.data.get("armed_server", "")
        
    def set_armed_server(self, ip_port: str):
        if self.data.get("armed_server") == ip_port:
            self.data["armed_server"] = "" # Toggle off
        else:
            self.data["armed_server"] = ip_port
        self.save()

history_store = HistoryStore()
