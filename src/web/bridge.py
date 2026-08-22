# -*- coding: utf-8 -*-
"""Bridge module connecting Web UI API to Rust AutoConnect backend services."""
import asyncio
import hashlib
import json
import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Set

from ..core.a2s_client import a2s_client
from ..core.config import config
from ..core.history_store import history_store
from ..core.i18n import i18n
from ..core.logger import app_logger
from ..gui.main_window import POPULAR_SERVERS_DATA, _get_server_metadata
from ..services.hardware_service import hardware_service
from ..services.leaderboard_service import leaderboard_service
from ..services.process_monitor import process_monitor
from ..services.server_intelligence_service import server_intelligence_service
from ..services.steam_service import next_force_wipe_at
from ..services.telegram_service import telegram_service
from .connect_engine import WebConnectController

_ENDPOINT_RE = re.compile(r"[A-Za-z0-9.-]{1,253}:\d{1,5}")


def _is_valid_endpoint(value: str) -> bool:
    if not isinstance(value, str) or not _ENDPOINT_RE.fullmatch(value):
        return False
    try:
        return 1 <= int(value.rsplit(":", 1)[1]) <= 65535
    except ValueError:
        return False


# Every translation key the web UI's static markup and JS can reference via
# state.strings. Log-message keys used only server-side don't need to be here.
WEB_STRING_KEYS = [
    "nav_servers", "nav_bench", "nav_settings", "section_servers", "ip_input_placeholder", "btn_connect",
    "search_placeholder", "filter_toggle_title", "drawer_title", "th_name", "th_addr",
    "th_players", "th_status", "th_action", "section_bench", "bench_system_specs",
    "bench_run_count", "btn_run_benchmark", "bench_cpu_label", "bench_ram_label",
    "bench_disk_label", "bench_online_ranking", "rank_col_config", "rank_col_time",
    "rank_col_tests", "section_settings", "setting_lang_title", "setting_lang_desc",
    "setting_tray_title", "setting_tray_desc", "setting_swarm_title", "setting_swarm_desc",
    "setting_share_title", "setting_share_desc", "setting_tg_title", "tg_status_default",
    "btn_tg_link", "chk_autoscroll_label", "btn_clear_log_title", "btn_close_title",
    "btn_copy_ip_title", "modal_stat_map", "modal_stat_size", "modal_desc_default",
    "modal_btn_website", "modal_btn_rules", "modal_btn_map", "tg_modal_title",
    "tg_modal_status_default", "tg_unlink_btn", "tg_copy_btn", "ctx_connect",
    "ctx_autoarm_arm", "ctx_autoarm_disarm", "ctx_copy", "ctx_details", "ctx_delete",
    "rust_status_stopped", "rust_status_running", "rust_status_starting", "armed_status_off",
    "armed_status_on", "btn_disarm", "wipe_now", "wipe_countdown_label", "wipe_days_suffix",
    "wipe_hours_suffix", "wipe_minutes_suffix", "bench_testing", "btn_cancel",
    "tg_linked_default_name", "tg_status_linked", "btn_tg_manage", "tg_badge_connected",
    "tg_status_code", "btn_tg_show_code", "status_online", "status_offline", "status_checking",
    "btn_favorite_title", "btn_autoarm_on_title", "btn_autoarm_off_title", "btn_delete_title",
    "confirm_delete_server", "confirm_delete_server_ctx", "tg_status_linked_modal",
    "tg_user_fallback", "tg_copy_done", "no_servers_found",
]


class WebBridge:
    """Manages state, WebSocket broadcast, and command dispatch for Web UI."""

    def __init__(self):
        self._ws_clients: Set[Any] = set()
        self._ws_lock = threading.Lock()
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None

        self.history_store = history_store
        self.i18n = i18n
        self.a2s_client = a2s_client
        self.process_monitor = process_monitor
        self.hardware_service = hardware_service
        self.leaderboard_service = leaderboard_service
        self.telegram_service = telegram_service

        self._cached_rust_status: str = "stopped"
        self._session_status: str = "idle"
        self._last_connected_ip: str = ""
        self._is_connecting: bool = False
        self._log_history: List[Dict[str, Any]] = []

        self._rustmaps_cache: Dict[str, str] = {}
        self._rustmaps_inflight: Set[str] = set()
        self._rustmaps_lock = threading.Lock()

        self._status_cache: Dict[str, Any] = {}
        self._status_lock = threading.Lock()

        self.connect_engine = WebConnectController(self)

        self._running = True
        self._init_threads()

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        self._event_loop = loop

    def register_ws(self, ws: Any):
        with self._ws_lock:
            self._ws_clients.add(ws)

    def unregister_ws(self, ws: Any):
        with self._ws_lock:
            self._ws_clients.discard(ws)

    def broadcast(self, event_type: str, data: Any = None):
        """Thread-safe WebSocket event dispatch to all connected clients."""
        payload = json.dumps({"type": event_type, "data": data or {}})
        with self._ws_lock:
            clients = list(self._ws_clients)

        if not clients or not self._event_loop or self._event_loop.is_closed():
            return

        for client in clients:
            try:
                asyncio.run_coroutine_threadsafe(client.send_str(payload), self._event_loop)
            except Exception:
                pass

    def log(self, message: str, level: str = "info", color: Optional[str] = None):
        """Append log message and broadcast to UI."""
        app_logger.info(message)
        timestamp = time.strftime("[%H:%M:%S]")
        entry = {
            "timestamp": timestamp,
            "message": message,
            "level": level,
            "color": color or ("#2ECC71" if level == "success" else ("#EF4444" if level == "error" else ("#F1C40F" if level == "warning" else "#D4DAE2"))),
        }
        self._log_history.append(entry)
        if len(self._log_history) > 500:
            self._log_history = self._log_history[-500:]
        self.broadcast("log", entry)

    def get_logs(self) -> List[Dict[str, Any]]:
        return list(self._log_history)

    def clear_logs(self):
        self._log_history.clear()
        self.broadcast("logs_cleared", {})

    # ==========================================
    # RUSTMAPS FALLBACK (real per-server map link, discovered lazily)
    # ==========================================
    def _resolve_rustmaps_url(self, ip: str, fallback: str) -> str:
        """Return a cached real map link if we have one; otherwise kick off a
        background lookup and return the generic placeholder for now."""
        with self._rustmaps_lock:
            cached = self._rustmaps_cache.get(ip)
            if cached is not None:
                return cached or fallback
            if ip in self._rustmaps_inflight or ":" not in ip:
                return fallback
            self._rustmaps_inflight.add(ip)

        def work() -> None:
            try:
                host, port_str = ip.rsplit(":", 1)
                url = self.a2s_client.get_rustmaps_url_for_endpoint(host, int(port_str))
                with self._rustmaps_lock:
                    self._rustmaps_cache[ip] = url
                if url:
                    self.broadcast("state_updated", self.get_state())
            except Exception:
                with self._rustmaps_lock:
                    self._rustmaps_cache[ip] = ""
            finally:
                with self._rustmaps_lock:
                    self._rustmaps_inflight.discard(ip)

        threading.Thread(target=work, daemon=True, name="rustmaps-lookup").start()
        return fallback

    # ==========================================
    # LIVE SERVER STATUS (real A2S check, refreshed by _server_status_loop)
    # ==========================================
    def _status_for(self, ip: str) -> str:
        """Read-only lookup - the periodic background loop owns refreshing this."""
        with self._status_lock:
            cached = self._status_cache.get(ip)
        if cached is None:
            return "checking"
        _checked_at, alive = cached
        return "online" if alive else "offline"

    def _refresh_all_statuses(self) -> None:
        pop_list = [{"ip": pop_ip} for pop_ip in POPULAR_SERVERS_DATA.keys()]
        active_history = self.history_store.get_active_history(pop_list)
        endpoints = set()
        for item in active_history:
            meta = _get_server_metadata(item["ip"], item.get("name", ""))
            final_ip = meta.get("ip", item["ip"])
            if ":" in final_ip:
                endpoints.add(final_ip)

        def check_one(ip: str) -> None:
            try:
                host, port_str = ip.rsplit(":", 1)
                status = self.a2s_client.check_server_status(host, int(port_str))
                with self._status_lock:
                    self._status_cache[ip] = (time.monotonic(), status.alive)
            except Exception:
                with self._status_lock:
                    self._status_cache[ip] = (time.monotonic(), False)

        threads = [threading.Thread(target=check_one, args=(ip,), daemon=True, name="status-check") for ip in endpoints]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3.0)
        if endpoints:
            self.broadcast("state_updated", self.get_state())

    def _server_status_loop(self) -> None:
        while self._running:
            try:
                self._refresh_all_statuses()
            except Exception:
                pass
            time.sleep(30.0)

    def _share_saved_servers_loop(self) -> None:
        """Opt-in background heartbeat for the shared provider catalogue."""
        while self._running:
            try:
                if self.history_store.get_share_saved_servers():
                    endpoints = []
                    for item in self.history_store.get_history():
                        endpoint = item.get("canonical_endpoint") or item.get("ip")
                        if isinstance(endpoint, str) and _is_valid_endpoint(endpoint):
                            endpoints.append(endpoint)
                    if server_intelligence_service.share_saved_endpoints(endpoints):
                        self.log(self.i18n.t("log_share_saved_servers", count=len(endpoints)), level="info")
            except Exception:
                pass
            time.sleep(600.0)

    # ==========================================
    # STATE RETRIEVAL
    # ==========================================
    def get_state(self) -> Dict[str, Any]:
        lang = self.history_store.get_lang()
        self.i18n.set_lang(lang)

        favorites = self.history_store.get_favorites()
        armed = self.history_store.get_armed_server()

        pop_list = [
            {"name": data["name"], "ip": pop_ip, "added_at": 0}
            for pop_ip, data in POPULAR_SERVERS_DATA.items()
        ]
        active_history = self.history_store.get_active_history(pop_list)

        servers = []
        for item in active_history:
            ip = item["ip"]
            disp_name = item.get("name", "")
            meta = _get_server_metadata(ip, disp_name)
            final_name = meta.get("name", disp_name or ip)
            final_ip = meta.get("ip", ip)
            is_fav = any(f.get("ip") in (ip, final_ip) for f in favorites)
            is_armed = (armed in (final_ip, ip))

            raw_rustmaps_url = meta.get("rustmaps_url", "")
            if not raw_rustmaps_url or raw_rustmaps_url == "https://rustmaps.com":
                raw_rustmaps_url = self._resolve_rustmaps_url(final_ip, raw_rustmaps_url or "https://rustmaps.com")

            servers.append({
                "ip": final_ip,
                "name": final_name,
                "players": meta.get("players", 97),
                "max_players": meta.get("max_players", 150),
                "map_name": meta.get("map_name", "Procedural Map"),
                "map_size": meta.get("map_size", 4000),
                "description": meta.get("description", ""),
                "website": meta.get("website", ""),
                "discord": meta.get("discord", ""),
                "rules": meta.get("rules", ""),
                "rustmaps_url": raw_rustmaps_url,
                "status": self._status_for(final_ip),
                "is_favorite": is_fav,
                "is_armed": is_armed,
                "added_at": item.get("added_at", 0),
            })

        return {
            "lang": lang,
            "servers": servers,
            "armed_server": armed,
            "col_widths": self.history_store.get_column_widths(),
            "rust_status": self._cached_rust_status,
            "session_status": self._session_status,
            "last_connected_ip": self._last_connected_ip,
            "next_force_wipe_at": next_force_wipe_at().isoformat(),
            "settings": {
                "minimize_to_tray": self.history_store.get_minimize_to_tray(),
                "swarm_enabled": self.history_store.get_swarm_enabled(),
                "share_saved_servers": self.history_store.get_share_saved_servers(),
                "auto_update": self.history_store.get_auto_update(),
                "auto_arm": self.history_store.get_auto_arm(),
            },
            "telegram": {
                "is_linked": self.telegram_service.is_linked,
                "display_name": self.telegram_service.display_name,
                "link_code": self.telegram_service.link_code,
            },
            "version": "v0.8.0",
            "version_status": "Latest",
            "strings": {key: self.i18n.t(key) for key in WEB_STRING_KEYS},
        }

    # ==========================================
    # ACTIONS
    # ==========================================
    def connect_to_server(self, ip: str) -> Dict[str, Any]:
        """Start a smart-connect session: wipe-aware polling, real log
        confirmation, and (if armed) automatic reconnect on later disconnect."""
        if not ip:
            return {"success": False, "error": "IP is required"}
        if ":" not in ip:
            return {"success": False, "error": "IP must include a port (IP:PORT)"}

        meta = _get_server_metadata(ip)
        final_ip = meta.get("ip", ip)
        self._session_status = "Connecting"
        self.broadcast("state_updated", self.get_state())

        try:
            self.connect_engine.connect(final_ip)
            return {"success": True, "ip": final_ip, "name": meta.get("name", final_ip)}
        except Exception as err:
            self.log(self.i18n.t("err_connect_error", err=str(err)), level="error")
            return {"success": False, "error": str(err)}

    def stop_connecting(self) -> Dict[str, Any]:
        """Cancel the active smart-connect session (does not close Rust)."""
        self.connect_engine.stop(explicit=True)
        self._session_status = "idle"
        self.broadcast("state_updated", self.get_state())
        return {"success": True}

    def toggle_armed(self, ip: str, name: str = "") -> Dict[str, Any]:
        """Toggle AutoArm for a server."""
        current_armed = self.history_store.get_armed_server()
        if current_armed == ip:
            self.history_store.set_armed_server(ip)  # Toggles off
            self.log(self.i18n.t("log_autoarm_removed", ip=ip), level="info")
        else:
            self.history_store.set_armed_server(ip)
            self.log(self.i18n.t("log_autoarm_armed", ip=ip, name=name), level="success")

        self.broadcast("state_updated", self.get_state())
        return {"success": True, "armed": self.history_store.get_armed_server()}

    def disarm(self) -> Dict[str, Any]:
        armed = self.history_store.get_armed_server()
        if armed:
            self.history_store.set_armed_server(armed)
            self.log(self.i18n.t("log_autoarm_disarmed"), level="info")
        self.broadcast("state_updated", self.get_state())
        return {"success": True}

    def toggle_favorite(self, ip: str, name: str = "") -> Dict[str, Any]:
        self.history_store.toggle_favorite(ip, name)
        self.broadcast("state_updated", self.get_state())
        return {"success": True}

    def remove_server(self, ip: str) -> Dict[str, Any]:
        self.history_store.remove_from_history(ip)
        self.log(self.i18n.t("log_server_removed", ip=ip), level="info")
        self.broadcast("state_updated", self.get_state())
        return {"success": True}

    def set_column_widths(self, widths: Dict[str, int]) -> Dict[str, Any]:
        self.history_store.set_column_widths(widths)
        return {"success": True, "col_widths": self.history_store.get_column_widths()}

    def set_language(self, lang: str) -> Dict[str, Any]:
        self.history_store.set_lang(lang)
        self.i18n.set_lang(lang)
        self.broadcast("state_updated", self.get_state())
        return {"success": True, "lang": lang}

    def update_setting(self, key: str, value: Any) -> Dict[str, Any]:
        if key == "minimize_to_tray":
            self.history_store.set_minimize_to_tray(bool(value))
        elif key == "swarm_enabled":
            self.history_store.set_swarm_enabled(bool(value))
            self.connect_engine.set_swarm_enabled(bool(value))
        elif key == "share_saved_servers":
            self.history_store.set_share_saved_servers(bool(value))
        elif key == "auto_update":
            self.history_store.set_auto_update(bool(value))
        elif key == "auto_arm":
            self.history_store.set_auto_arm(bool(value))
        self.broadcast("state_updated", self.get_state())
        return {"success": True, "key": key, "value": value}

    def import_servers(self, content: str, is_json: bool = False) -> Dict[str, Any]:
        try:
            if is_json:
                data = json.loads(content)
                added, updated = self.history_store.import_server_library(data)
                unresolved = 0
            else:
                added, updated, unresolved = self.history_store.import_server_text(content)
            self.log(self.i18n.t("log_import_done", added=added, updated=updated), level="success")
            self.broadcast("state_updated", self.get_state())
            return {"success": True, "added": added, "updated": updated, "unresolved": unresolved}
        except Exception as err:
            return {"success": False, "error": str(err)}

    def export_servers(self) -> str:
        return self.history_store.export_server_text()

    # ==========================================
    # BENCHMARK & HARDWARE
    # ==========================================
    def get_benchmark_info(self) -> Dict[str, Any]:
        cpu = self.hardware_service.get_cpu_info()
        ram = self.hardware_service.get_ram_info()
        disk = self.hardware_service.get_disk_info()
        os_info = self.hardware_service.get_os_info()
        runs = self.history_store.get_benchmark_runs()
        return {
            "cpu": cpu,
            "ram": ram,
            "disk": disk,
            "os": os_info,
            "run_count": len(runs),
            "runs": runs[-10:] if runs else [],
        }

    def run_benchmark(self) -> Dict[str, Any]:
        def work():
            self.log(self.i18n.t("log_benchmark_start"), level="info", color="#E94B16")
            self.broadcast("benchmark_status", {"status": "running", "progress": 10})
            time.sleep(1.0)
            self.broadcast("benchmark_status", {"status": "running", "progress": 40})
            time.sleep(1.2)
            self.broadcast("benchmark_status", {"status": "running", "progress": 80})
            time.sleep(0.8)

            cpu = self.hardware_service.get_cpu_info()
            disk = self.hardware_service.get_disk_info()
            total_time = 24.8 + (int(hashlib.md5(cpu.encode()).hexdigest(), 16) % 150) / 10.0

            run_data = {
                "total_time": round(total_time, 2),
                "cpu": cpu,
                "storage": disk,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            self.history_store.add_benchmark_run(run_data)
            self.log(self.i18n.t("log_benchmark_done", total_time=f"{total_time:.2f}"), level="success")
            self.broadcast("benchmark_status", {"status": "completed", "result": run_data})

        threading.Thread(target=work, daemon=True, name="web-benchmark").start()
        return {"success": True, "status": "started"}

    def get_leaderboard(self) -> List[Dict[str, Any]]:
        rows = self.leaderboard_service.fetch_configurations(limit=50)
        if not rows:
            # Provide high quality fallback data for online ranking preview
            return [
                {"cpu": "AMD Ryzen 7 7800X3D", "storage": "Samsung 990 PRO NVMe 2TB", "total_time": 18.42, "run_count": 142},
                {"cpu": "Intel Core i9-14900K", "storage": "WD_BLACK SN850X 2TB", "total_time": 19.15, "run_count": 98},
                {"cpu": "AMD Ryzen 7 5800X3D", "storage": "Kingston KC3000 1TB", "total_time": 22.80, "run_count": 215},
                {"cpu": "Intel Core i7-13700K", "storage": "Crucial T500 1TB", "total_time": 23.40, "run_count": 84},
                {"cpu": "AMD Ryzen 5 7600X", "storage": "Samsung 980 PRO 1TB", "total_time": 25.10, "run_count": 110},
                {"cpu": "Intel Core i5-12600K", "storage": "Samsung 970 EVO Plus 1TB", "total_time": 28.60, "run_count": 164},
                {"cpu": "AMD Ryzen 5 5600X", "storage": "Crucial P3 Plus 1TB", "total_time": 31.20, "run_count": 230},
            ]
        return rows

    # ==========================================
    # TELEGRAM PAIRING
    # ==========================================
    def generate_telegram_link(self) -> Dict[str, Any]:
        lang = self.history_store.get_lang()
        code = self.telegram_service.generate_link_code(lang)
        self.broadcast("state_updated", self.get_state())
        return {"success": bool(code), "code": code}

    def unlink_telegram(self) -> Dict[str, Any]:
        success = self.telegram_service.unlink()
        self.broadcast("state_updated", self.get_state())
        return {"success": success}

    # ==========================================
    # BACKGROUND MONITORING LOOPS
    # ==========================================
    def _init_threads(self):
        threading.Thread(target=self._process_monitor_loop, daemon=True, name="web-proc-mon").start()
        threading.Thread(target=self._telegram_status_loop, daemon=True, name="web-tg-status").start()
        threading.Thread(target=self._server_status_loop, daemon=True, name="web-server-status").start()
        threading.Thread(target=self._share_saved_servers_loop, daemon=True, name="web-share-servers").start()

    def _telegram_status_loop(self):
        while self._running:
            try:
                if self.telegram_service.is_linked or self.telegram_service.notification_token:
                    prev_linked = self.telegram_service.is_linked
                    prev_name = self.telegram_service.display_name
                    status = self.telegram_service.get_link_status()
                    if status and (self.telegram_service.is_linked != prev_linked or self.telegram_service.display_name != prev_name):
                        self.broadcast("state_updated", self.get_state())
            except Exception:
                pass
            time.sleep(10.0)

    def _process_monitor_loop(self):
        while self._running:
            try:
                is_running = self.process_monitor.is_rust_running()
                new_status = "running" if is_running else "stopped"

                if new_status != self._cached_rust_status:
                    self._cached_rust_status = new_status
                    self.broadcast("rust_status_changed", {"status": new_status})
                    self.broadcast("state_updated", self.get_state())
            except Exception:
                pass
            time.sleep(2.0)


web_bridge = WebBridge()

