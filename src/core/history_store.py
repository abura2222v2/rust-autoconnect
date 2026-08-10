import copy
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

from .config import config
from .logger import app_logger


DEFAULT_DATA: Dict[str, Any] = {
    "lang": "EN", "history": [], "favorites": [], "auto_update": True,
    "minimize_to_tray": False, "rust_path": "", "swarm_enabled": False,
    "leaderboard_enabled": True, "username": "", "client_id": "",
    "installation_id": "", "armed_server": "", "benchmark_runs": [],
    "home_splitter_width": 270, "bench_splitter_width": 270, "auto_arm": True,
}



class HistoryStore:
    def __init__(self):
        self._lock = threading.RLock()
        self.data: Dict[str, Any] = copy.deepcopy(DEFAULT_DATA)
        self.load()

    @staticmethod
    def _normalize(data: Any) -> Dict[str, Any]:
        if not isinstance(data, dict):
            raise ValueError("settings root must be an object")
        normalized = copy.deepcopy(data)
        for key, value in DEFAULT_DATA.items():
            normalized.setdefault(key, copy.deepcopy(value))
        if not all(isinstance(normalized[key], list) for key in ("history", "favorites", "benchmark_runs")):
            raise ValueError("history, favorites, and benchmark runs must be lists")
        normalized["history"] = [item for item in normalized["history"] if isinstance(item, dict) and isinstance(item.get("ip"), str)][:20]
        normalized["favorites"] = [item for item in normalized["favorites"] if isinstance(item, dict) and isinstance(item.get("ip"), str)]
        normalized["benchmark_runs"] = [
            item for item in normalized["benchmark_runs"]
            if isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("configuration_key"), str)
        ][-250:]
        return normalized

    def _backup_corrupted_file(self, data_file: Path) -> None:
        corrupted_file = data_file.with_name(f"{data_file.name}.corrupted_{int(time.time())}")
        try:
            shutil.copy2(data_file, corrupted_file)
        except OSError as error:
            app_logger.warning(f"Unable to back up corrupted settings: {error}")

    def load(self):
        with self._lock:
            config.appdata_dir.mkdir(parents=True, exist_ok=True)
            data_file = config.data_file
            if not data_file.exists():
                return
            try:
                with data_file.open("r", encoding="utf-8") as file:
                    self.data = self._normalize(json.load(file))
            except OSError as error:
                app_logger.warning(f"Unable to read settings file: {error}")
            except (json.JSONDecodeError, ValueError) as error:
                app_logger.warning(f"Settings corruption detected: {type(error).__name__}")
                self._backup_corrupted_file(data_file)
                self.data = copy.deepcopy(DEFAULT_DATA)
                self.save()
    def save(self) -> bool:
        """Atomically persist the current validated state."""
        with self._lock:
            config.appdata_dir.mkdir(parents=True, exist_ok=True)
            data_file = config.data_file
            tmp_file = data_file.with_suffix(".tmp")
            data_copy = self._normalize(self.data)
            try:
                with tmp_file.open("w", encoding="utf-8") as file:
                    json.dump(data_copy, file, ensure_ascii=False, indent=2)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(tmp_file, data_file)
                self.data = data_copy
                return True
            except OSError as error:
                app_logger.error(f"Unable to save settings: {error}")
                try:
                    tmp_file.unlink(missing_ok=True)
                except OSError:
                    pass
                return False

    def add_to_history(self, ip_port: str, name: str):
        with self._lock:
            previous = next((item for item in self.data["history"] if item.get("ip") == ip_port), {})
            history = [item for item in self.data["history"] if item.get("ip") != ip_port]
            history.insert(0, {**previous, "ip": ip_port, "name": name, "added_at": int(time.time())})
            self.data["history"] = history[:20]
            self.save()

    def remove_from_history(self, ip_port: str):
        with self._lock:
            self.data["history"] = [item for item in self.data["history"] if item.get("ip") != ip_port]
            self.save()

    def toggle_favorite(self, ip_port: str, name: str):
        with self._lock:
            favorites = self.data["favorites"]
            if any(item.get("ip") == ip_port for item in favorites):
                self.data["favorites"] = [item for item in favorites if item.get("ip") != ip_port]
            else:
                favorites.append({"name": name, "ip": ip_port})
            self.save()

    def update_server_name(self, ip_port: str, new_name: str):
        with self._lock:
            for items in (self.data["history"], self.data["favorites"]):
                for item in items:
                    if item.get("ip") == ip_port:
                        item["name"] = new_name
            self.save()

    def get_history(self) -> List[Dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self.data["history"])

    def get_favorites(self) -> List[Dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self.data["favorites"])

    def update_server_metadata(self, ip_port: str, tags: List[str], note: str) -> bool:
        clean_tags = []
        for tag in tags:
            tag = str(tag).strip()[:32]
            if tag and tag not in clean_tags:
                clean_tags.append(tag)
        with self._lock:
            for item in self.data["history"]:
                if item.get("ip") == ip_port:
                    item["tags"] = clean_tags[:8]
                    item["note"] = str(note).strip()[:512]
                    return self.save()
        return False

    def get_server_wipe_schedule(self, ip_port: str) -> Dict[str, Any]:
        """Return the optional user-confirmed wipe schedule for one server."""
        with self._lock:
            item = next((entry for entry in self.data["history"] if entry.get("ip") == ip_port), {})
            wipe_at = item.get("wipe_at")
            if not isinstance(wipe_at, int) or wipe_at <= 0:
                wipe_at = None
            source = item.get("wipe_source") if isinstance(item.get("wipe_source"), str) else ""
            return {"wipe_at": wipe_at, "wipe_source": source}

    def set_server_wipe_schedule(self, ip_port: str, wipe_at: int | None, source: str = "manual") -> bool:
        """Persist a manual UTC schedule. ``None`` clears it."""
        with self._lock:
            for item in self.data["history"]:
                if item.get("ip") == ip_port:
                    if wipe_at is None:
                        item.pop("wipe_at", None)
                        item.pop("wipe_source", None)
                    else:
                        item["wipe_at"] = max(1, int(wipe_at))
                        item["wipe_source"] = str(source).strip()[:32] or "manual"
                    return self.save()
        return False

    def export_server_library(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "format": "rust-autoconnect-server-library-v1",
                "servers": copy.deepcopy(self.data["history"]),
                "favorites": copy.deepcopy(self.data["favorites"]),
                "armed_server": self.data["armed_server"],
            }

    def import_server_library(self, payload: Any) -> tuple[int, int]:
        """Merge a validated library and return added and updated record counts."""
        if not isinstance(payload, dict) or payload.get("format") != "rust-autoconnect-server-library-v1":
            raise ValueError("unsupported server library")
        servers = payload.get("servers")
        favorites = payload.get("favorites", [])
        if not isinstance(servers, list) or not isinstance(favorites, list):
            raise ValueError("invalid server library")

        added = 0
        updated = 0
        with self._lock:
            current = {item.get("ip"): item for item in self.data["history"] if isinstance(item, dict)}
            for server in servers[:100]:
                if not isinstance(server, dict):
                    continue
                ip = server.get("ip")
                name = server.get("name")
                if not isinstance(ip, str) or not isinstance(name, str):
                    continue
                ip = ip.strip()
                if len(ip) > 255 or not re.fullmatch(r"[A-Za-z0-9.-]{1,253}:\d{1,5}", ip):
                    continue
                port = int(ip.rsplit(":", 1)[1])
                if not 1 <= port <= 65535:
                    continue
                try:
                    added_at = int(server.get("added_at", time.time()))
                except (TypeError, ValueError, OverflowError):
                    added_at = int(time.time())
                normalized = {
                    "ip": ip,
                    "name": name.strip()[:160] or "Rust Server",
                    "added_at": added_at,
                    "tags": [str(tag).strip()[:32] for tag in server.get("tags", [])[:8] if str(tag).strip()]
                    if isinstance(server.get("tags", []), list) else [],
                    "note": str(server.get("note", "")).strip()[:512],
                }
                if ip in current:
                    current[ip] = {**current[ip], **normalized}
                    updated += 1
                else:
                    current[ip] = normalized
                    added += 1
            def sort_time(item: Dict[str, Any]) -> int:
                try:
                    return int(item.get("added_at", 0))
                except (TypeError, ValueError, OverflowError):
                    return 0

            ordered = sorted(current.values(), key=sort_time, reverse=True)
            self.data["history"] = ordered[:20]
            
            merged_favorites = {
                item.get("ip"): {"ip": item.get("ip"), "name": str(item.get("name", "Rust Server"))[:160]}
                for item in self.data["favorites"]
                if isinstance(item, dict) and isinstance(item.get("ip"), str)
            }
            for item in favorites[:100]:
                if isinstance(item, dict) and isinstance(item.get("ip"), str):
                    merged_favorites[item["ip"]] = {
                        "ip": item["ip"],
                        "name": str(item.get("name", "Rust Server"))[:160],
                    }
            self.data["favorites"] = list(merged_favorites.values())
            imported_armed = payload.get("armed_server")
            if not self.data.get("armed_server") and imported_armed in current:
                self.data["armed_server"] = imported_armed
            self.save()
        return added, updated

    def add_benchmark_run(self, run: Dict[str, Any]) -> bool:
        with self._lock:
            if not isinstance(run.get("id"), str) or not isinstance(run.get("configuration_key"), str):
                raise ValueError("invalid benchmark run")
            normalized_run = copy.deepcopy(run)
            normalized_run.setdefault("sync_state", "pending")
            self.data["benchmark_runs"].append(normalized_run)
            self.data["benchmark_runs"] = self.data["benchmark_runs"][-250:]
            return self.save()

    def get_benchmark_runs(self, configuration_key: str = "") -> List[Dict[str, Any]]:
        with self._lock:
            runs = self.data["benchmark_runs"]
            if configuration_key:
                runs = [run for run in runs if run.get("configuration_key") == configuration_key]
            return copy.deepcopy(runs)

    def mark_benchmark_run_synced(self, run_id: str) -> bool:
        with self._lock:
            for run in self.data["benchmark_runs"]:
                if run.get("id") == run_id:
                    run["sync_state"] = "synced"
                    return self.save()
        return False

    def get_username(self) -> str:
        with self._lock:
            return self.data["username"]

    def get_client_id(self) -> str:
        with self._lock:
            client_id = self.data["client_id"]
            if not client_id:
                import uuid
                client_id = str(uuid.uuid4())
                self.data["client_id"] = client_id
                self.save()
            return client_id

    def get_installation_id(self) -> str:
        with self._lock:
            installation_id = self.data["installation_id"]
            if not installation_id:
                import uuid
                installation_id = str(uuid.uuid4())
                self.data["installation_id"] = installation_id
                self.save()
            return installation_id

    def reset_installation_id(self) -> str:
        with self._lock:
            import uuid
            installation_id = str(uuid.uuid4())
            self.data["installation_id"] = installation_id
            self.save()
            return installation_id

    def _set_value(self, key: str, value: Any) -> None:
        with self._lock:
            self.data[key] = value
            self.save()

    def set_username(self, name: str): self._set_value("username", name)
    def get_lang(self) -> str:
        with self._lock:
            return self.data["lang"]
    def set_lang(self, code: str): self._set_value("lang", code)
    def get_auto_update(self) -> bool:
        with self._lock:
            return bool(self.data["auto_update"])
    def set_auto_update(self, val: bool): self._set_value("auto_update", bool(val))
    def get_minimize_to_tray(self) -> bool:
        with self._lock:
            return bool(self.data["minimize_to_tray"])
    def set_minimize_to_tray(self, val: bool): self._set_value("minimize_to_tray", bool(val))
    def get_rust_path(self) -> str:
        with self._lock:
            return self.data["rust_path"]
    def set_rust_path(self, val: str): self._set_value("rust_path", val)
    def get_swarm_enabled(self) -> bool:
        with self._lock:
            return bool(self.data["swarm_enabled"])
    def set_swarm_enabled(self, val: bool): self._set_value("swarm_enabled", bool(val))
    def get_leaderboard_enabled(self) -> bool:
        with self._lock:
            return bool(self.data["leaderboard_enabled"])
    def set_leaderboard_enabled(self, val: bool): self._set_value("leaderboard_enabled", bool(val))
    def get_armed_server(self) -> str:
        with self._lock:
            return self.data["armed_server"]

    def get_auto_arm(self) -> bool:
        with self._lock:
            return bool(self.data.get("auto_arm", True))
            
    def set_auto_arm(self, val: bool):
        self._set_value("auto_arm", bool(val))

    def set_armed_server(self, ip_port: str):
        with self._lock:
            self.data["armed_server"] = "" if self.data["armed_server"] == ip_port else ip_port
            self.save()

    def get_home_splitter_width(self) -> int:
        with self._lock:
            return self.data.get("home_splitter_width", 270)
            
    def set_home_splitter_width(self, width: int):
        self._set_value("home_splitter_width", width)
        
    def get_bench_splitter_width(self) -> int:
        with self._lock:
            return self.data.get("bench_splitter_width", 270)
            
    def set_bench_splitter_width(self, width: int):
        self._set_value("bench_splitter_width", width)


history_store = HistoryStore()
