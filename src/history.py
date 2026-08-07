"""
Server History Storage Manager for Rust Autoconnect GUI Utility.
Provides atomic JSON persistence, deduplication, schema validation, and corrupted file recovery.
"""

from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Union


def format_server_entry(server: Dict[str, Any]) -> str:
    """
    Format a server entry dictionary into a standardized display string.
    Returns '[IP:Port] (Server Name)' if name is non-empty, otherwise '[IP:Port]'.
    """
    ip = str(server.get("ip", "")).strip()
    port = str(server.get("port", "")).strip()
    name = str(server.get("name", "")).strip()

    base = f"[{ip}:{port}]"
    if name:
        return f"{base} ({name})"
    return base


class HistoryManager:
    """
    Manages server connection history persistence in JSON format.
    """

    def __init__(self, filepath: Union[str, Path] = "servers.json", max_entries: int = 50):
        self.filepath = Path(filepath)
        self.max_entries = max(1, max_entries)
        self._history: List[Dict[str, Any]] = []
        self._load_history()

    def get_history(self) -> List[Dict[str, Any]]:
        """Return a copy of the current server history list."""
        return [dict(entry) for entry in self._history]

    def add_server(self, ip: str, port: Union[int, str], name: str = "") -> Dict[str, Any]:
        """
        Add or update a server in history. Moves matching IP+Port to index 0 (top).
        If name is empty and existing entry has a name, existing name is preserved.
        Truncates history to max_entries and saves atomically.
        """
        clean_ip = str(ip).strip()
        if not clean_ip:
            raise ValueError("IP address cannot be empty.")

        try:
            port_num = int(port)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid port: {port}") from e

        if not (1 <= port_num <= 65535):
            raise ValueError(f"Port must be between 1 and 65535, got {port_num}")

        clean_name = str(name).strip() if name is not None else ""

        # Check for existing entry matching IP and Port
        existing_index = -1
        existing_entry = None
        for idx, entry in enumerate(self._history):
            if entry["ip"].lower() == clean_ip.lower() and int(entry["port"]) == port_num:
                existing_index = idx
                existing_entry = entry
                break

        if existing_index >= 0:
            self._history.pop(existing_index)
            final_name = clean_name if clean_name else existing_entry.get("name", "")
        else:
            final_name = clean_name

        new_entry = {
            "ip": clean_ip,
            "port": port_num,
            "name": final_name
        }

        self._history.insert(0, new_entry)

        if len(self._history) > self.max_entries:
            self._history = self._history[:self.max_entries]

        self._save_history()
        return dict(new_entry)

    def remove_server(self, ip: str, port: Union[int, str]) -> bool:
        """Remove entry with matching IP and Port from history. Returns True if removed."""
        clean_ip = str(ip).strip()
        try:
            port_num = int(port)
        except (ValueError, TypeError):
            return False

        found_idx = -1
        for idx, entry in enumerate(self._history):
            if entry["ip"].lower() == clean_ip.lower() and int(entry["port"]) == port_num:
                found_idx = idx
                break

        if found_idx >= 0:
            self._history.pop(found_idx)
            self._save_history()
            return True
        return False

    def clear_history(self) -> None:
        """Clear all server entries from history and persist."""
        self._history = []
        self._save_history()

    def format_entry(self, server: Dict[str, Any]) -> str:
        """Format server dictionary to display string."""
        return format_server_entry(server)

    def _load_history(self) -> None:
        """
        Load history from JSON file.
        If file is missing, initializes empty list.
        If corrupted or invalid schema, backs up file to `.corrupted_<timestamp>` and resets.
        """
        if not self.filepath.exists():
            self._history = []
            return

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, list):
                raise ValueError("JSON root is not a list")

            valid_history = []
            for item in data:
                if not isinstance(item, dict):
                    raise ValueError("List item is not a dict")
                if "ip" not in item or "port" not in item:
                    raise ValueError("Item missing required 'ip' or 'port' field")

                ip = str(item["ip"]).strip()
                port = int(item["port"])
                name = str(item.get("name", "")).strip()

                if not ip or not (1 <= port <= 65535):
                    raise ValueError(f"Invalid entry values: ip={ip}, port={port}")

                valid_history.append({"ip": ip, "port": port, "name": name})

            self._history = valid_history

        except Exception as err:
            self._handle_corrupted_file(err)

    def _handle_corrupted_file(self, err: Exception) -> None:
        """Backup corrupted file to `.corrupted_<timestamp>` and initialize empty history."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_path = Path(str(self.filepath) + f".corrupted_{timestamp}")

        try:
            if self.filepath.exists():
                os.replace(self.filepath, backup_path)
        except Exception:
            pass

        self._history = []
        self._save_history()

    def _save_history(self) -> None:
        """Atomically write history list to JSON file using temporary file and os.replace."""
        try:
            if self.filepath.parent:
                self.filepath.parent.mkdir(parents=True, exist_ok=True)

            tmp_path = Path(str(self.filepath) + ".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._history, f, indent=2, ensure_ascii=False)

            os.replace(tmp_path, self.filepath)
        except Exception as e:
            tmp_path = Path(str(self.filepath) + ".tmp")
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            raise IOError(f"Failed to save server history: {e}") from e
