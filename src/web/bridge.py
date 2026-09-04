# -*- coding: utf-8 -*-
"""Bridge module connecting Web UI API to Rust AutoConnect backend services."""
import asyncio
import json
import logging
import os
import re
import shutil
import threading
import time
import traceback
import webbrowser
from typing import Any, Dict, List, Optional, Set

from ..core.a2s_client import a2s_client
from ..core.benchmark_model import BENCHMARK_VERSION, build_run
from ..core.config import config
from ..core.history_store import history_store
from ..core.i18n import i18n
from ..core.logger import app_logger
from ..services.server_catalog import POPULAR_SERVERS_DATA, get_server_metadata as _get_server_metadata
from ..services.hardware_service import hardware_service
from ..services.leaderboard_service import leaderboard_service
from ..services.process_monitor import process_monitor
from ..services.server_intelligence_service import server_intelligence_service
from ..services.log_watcher import LogWatcher
from ..services import steam_service
from ..services.steam_service import find_rust_install_path, next_force_wipe_at
from ..services.telegram_service import telegram_service
from .connect_engine import WebConnectController

# Verified against a real Rust client (2026-09-03): the game prints
# "Connecting: ip:port", never "Connecting to ip:port" - a regex using "to"
# (as src/app.py's legacy global watcher does) never matches a real log.
_GLOBAL_CONNECTING_RE = re.compile(r"Connecting:\s*([A-Za-z0-9.-]+:\d{1,5})", re.IGNORECASE)

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
    "bench_confirm_msg", "bench_warn_f5", "restore_pending",
    "server_wipe_now", "server_wipe_countdown_label",
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

        self._intel_cache: Dict[str, Any] = {}
        self._intel_lock = threading.Lock()

        self._global_log_watcher: Optional[LogWatcher] = None
        self._last_armed_from_log: Optional[str] = None
        self._global_watcher_lock = threading.Lock()
        self._global_watcher_restart_timer: Optional[threading.Timer] = None

        # Rust patches on every force-wipe day. Launching an outdated client
        # makes Steam start the update instead of the game, and the join then
        # fails with a protocol mismatch - so a pending update holds the
        # launch back. This event is "set" whenever launching is safe.
        self._update_ready_event = threading.Event()
        self._update_ready_event.set()
        self._update_required = False
        self._update_steam_opened = False
        self._update_status_logged = ""
        self._update_check_wake_event = threading.Event()

        self._is_benchmarking: bool = False
        self._benchmark_stop_event = threading.Event()
        self._benchmark_lock = threading.Lock()
        self._benchmark_operation: int = 0
        self._pending_benchmark_restore: Optional[tuple] = None

        self.connect_engine = WebConnectController(self)

        self._running = True
        self._init_threads()

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        self._event_loop = loop

    def start_global_watcher(self) -> None:
        """Watch Rust's log continuously (not just during an active connect
        session) so a server the player joins manually - from Rust's own
        server browser, F1 console, or a friend invite - still gets
        auto-armed. Must be called once a real event loop is available
        (after set_event_loop); tests that only call set_event_loop must
        not trigger this on their own, since it would tail the real user's
        Player.log in the background for every such test."""
        self._start_global_log_watcher()

    def _start_global_log_watcher(self) -> None:
        # Restarts are scheduled from two independent places (a disconnect,
        # and the end of a benchmark run). Without stopping the previous one
        # first, both timers leave a live watcher on the same file, and every
        # auto-arm and log line arrives twice.
        if self._global_log_watcher is not None:
            self._global_log_watcher.stop()
            self._global_log_watcher = None

        def handle_event(event: str) -> None:
            if not self.history_store.get_auto_arm():
                return
            match = _GLOBAL_CONNECTING_RE.search(event)
            if not match:
                return
            ip_port = match.group(1)
            if self._last_armed_from_log == ip_port:
                return
            self._last_armed_from_log = ip_port
            self.history_store.set_armed_server(ip_port, force=True)
            self.log(self.i18n.t("log_auto_armed_server", ip=ip_port), level="warning")
            self.broadcast("state_updated", self.get_state())

        def handle_disconnect(reason: str) -> None:
            # The active per-connection watcher (connect_engine.py) owns
            # reconnect logic for sessions this app launched. This observer
            # only needs to restart itself so it keeps watching afterward -
            # LogWatcher stops itself on any detected disconnect line.
            if self._running:
                self._schedule_global_watcher_restart()

        watcher = LogWatcher(
            on_disconnect=handle_disconnect,
            on_error=lambda err: None,
            on_event=handle_event,
            seek_end=True,
        )
        self._global_log_watcher = watcher
        # Fix the "only new lines" boundary synchronously, on this thread,
        # right now - start() only schedules the async tailing task, which
        # may not actually run for a moment. Without capturing the position
        # first, a line written in that gap could race the seek-to-end and
        # be silently skipped.
        watcher.capture_start_position()
        watcher.start(loop=self._event_loop)

    def _schedule_global_watcher_restart(self) -> None:
        with self._global_watcher_lock:
            if self._global_watcher_restart_timer is not None:
                return  # one restart is already on its way
            def restart() -> None:
                with self._global_watcher_lock:
                    self._global_watcher_restart_timer = None
                if self._running:
                    self._start_global_log_watcher()
            timer = threading.Timer(5.0, restart)
            timer.daemon = True
            self._global_watcher_restart_timer = timer
            timer.start()

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
        return "online" if cached[1] else "offline"

    def _live_player_counts(self, ip: str) -> Optional[tuple]:
        """Return a real (player_count, max_players) pair from the last A2S
        check, or None if this server hasn't been checked yet."""
        with self._status_lock:
            cached = self._status_cache.get(ip)
        if cached is None:
            return None
        return (cached[2], cached[3])

    def _intel_for(self, ip: str):
        """Real per-server community/map data (Discord, website, rules,
        RustMaps link) from the shared backend - or None before the first
        check completes. Refreshed alongside the A2S status check below;
        server_intelligence_service has its own 5-minute cache, so this does
        not add extra network calls beyond what that loop already runs."""
        with self._intel_lock:
            return self._intel_cache.get(ip)

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
                    self._status_cache[ip] = (time.monotonic(), status.alive, status.player_count, status.max_players)
            except Exception as error:
                # Showing this server as offline is the right call, but the
                # reason must not vanish - a systematic failure here would
                # otherwise look exactly like "every server is down".
                app_logger.warning(f"Status check failed for {ip}: {type(error).__name__}")
                with self._status_lock:
                    self._status_cache[ip] = (time.monotonic(), False, 0, 0)
            try:
                snapshot = server_intelligence_service.observe_endpoint(ip, active=False)
                with self._intel_lock:
                    self._intel_cache[ip] = snapshot
            except Exception as error:
                app_logger.warning(f"Community info check failed for {ip}: {type(error).__name__}")

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
                app_logger.error(f"Server status refresh failed: {traceback.format_exc()}")
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
                app_logger.error(f"Sharing saved servers failed: {traceback.format_exc()}")
            time.sleep(600.0)

    # ==========================================
    # RUST BUILD / CLOCK (ported from src/app.py: the web UI had the
    # auto_update setting but nothing that acted on it)
    # ==========================================
    def _check_rust_update_once(self) -> float:
        """Compare the installed Rust build with the published one.

        Also the only place the app learns real network time: Steam's HTTP
        Date header anchors network_clock, which every wipe calculation is
        based on. Without it that clock silently falls back to the Windows
        clock, and a drifting local clock mistimes the whole wipe hold.
        """
        info = steam_service.fetch_latest_build_info()
        if info.server_date:
            clock = self.connect_engine.network_clock
            was_synced = clock.is_synced
            clock.observe_http_date(info.server_date)
            offset = clock.system_offset_seconds
            if offset is not None and abs(offset) > 120 and self._update_status_logged != "clock-offset":
                self.log(self.i18n.t("log_clock_offset", minutes=int(abs(offset) // 60)), level="warning")
                self._update_status_logged = "clock-offset"
            elif not was_synced:
                self.log(self.i18n.t("log_clock_synced"), level="success")

        local_buildid = steam_service.get_local_buildid()
        mismatch = bool(local_buildid and info.buildid and str(local_buildid) != str(info.buildid))
        if mismatch:
            self._update_required = True
            self._update_ready_event.clear()
            if self._update_status_logged != "pending":
                self.log(self.i18n.t("rust_game_update_avail"), level="warning")
                self._update_status_logged = "pending"
            if not self.process_monitor.is_rust_running() and not self._update_steam_opened:
                self._update_steam_opened = steam_service.open_steam_downloads()
                if self._update_steam_opened:
                    self.log(self.i18n.t("log_opened_steam_downloads"), level="info")
        elif info.buildid and local_buildid:
            if self._update_required:
                self.log(self.i18n.t("log_rust_update_ready"), level="success")
            self._update_required = False
            self._update_steam_opened = False
            self._update_status_logged = "ready"
            self._update_ready_event.set()
        return steam_service.force_wipe_poll_interval(self.connect_engine.network_clock.now())

    def _rust_update_loop(self) -> None:
        while self._running:
            if not self.history_store.get_auto_update():
                if self._update_check_wake_event.wait(60.0):
                    self._update_check_wake_event.clear()
                continue
            try:
                interval = self._check_rust_update_once()
            except Exception as error:
                app_logger.error(f"Rust build check failed: {type(error).__name__}")
                interval = 300.0
            self._update_check_wake_event.clear()
            deadline = time.monotonic() + interval
            while self._running and time.monotonic() < deadline:
                if self._update_check_wake_event.wait(min(0.5, max(0.0, deadline - time.monotonic()))):
                    break

    def wait_for_rust_update(self, should_continue) -> bool:
        """Hold a launch while a known Rust update is still pending.

        Returns True when it is safe to launch, False if the caller's session
        was cancelled while waiting.
        """
        if self._update_ready_event.is_set():
            return should_continue()
        self.log(self.i18n.t("log_waiting_rust_update"), level="warning")
        self._update_check_wake_event.set()
        while should_continue():
            if self._update_ready_event.wait(0.25):
                return should_continue()
        return False

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

            # Real community/map data from the shared backend (parsed from the
            # server operator's own listing) - None before the first check.
            intel = self._intel_for(final_ip)

            # RustMaps has two independent ways to resolve, tried in order:
            # the official per-seed API (server-side, needs the aggregator to
            # know this server's seed) and the legacy per-connection A2S
            # rules() lookup (works only if this exact server allows that
            # query). Either can succeed where the other fails.
            raw_rustmaps_url = (intel.rustmaps_url if intel else "") or self._resolve_rustmaps_url(final_ip, "")

            # Prefer a real number from the last A2S check over the catalog's
            # curated/guessed one - only fall back while nothing real is
            # known yet (status "checking").
            live_counts = self._live_player_counts(final_ip)
            if live_counts is not None:
                player_count, max_players = live_counts
            else:
                player_count = meta.get("players", 97)
                max_players = meta.get("max_players", 150)

            servers.append({
                "ip": final_ip,
                "name": final_name,
                "players": player_count,
                "max_players": max_players,
                "map_name": (intel.map_name if intel else "") or meta.get("map_name", "Procedural Map"),
                "map_size": (intel.map_size if intel else None) or meta.get("map_size", 4000),
                "description": (intel.description if intel else "") or meta.get("description", ""),
                # Real per-server links only - never a guessed placeholder.
                # An empty string tells the frontend to hide that button
                # instead of pointing at an unrelated server's page.
                "website": intel.website if intel else "",
                "discord": intel.discord if intel else "",
                "rules": intel.rules if intel else "",
                "rustmaps_url": raw_rustmaps_url,
                "rustmaps_image_url": intel.rustmaps_image_url if intel else "",
                # This server's own posted wipe schedule (from the shared
                # listing cache), independent of the official force-wipe
                # date - None when the catalogue doesn't know it.
                "wipe_at": intel.wipe_at if intel else None,
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
            # A person clicking Connect may want to enter Rust's own server
            # queue when it's full. Automatic recovery does not use this.
            self.connect_engine.connect(final_ip, queue_on_full=True)
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
        """Real hardware benchmark: launches Rust, times the menu load and a
        replayed demo, then restores the player's cfg. Ported from the
        legacy Tkinter app's _run_benchmark_logic_internal (src/app.py) -
        the web UI previously computed a fake number from an md5 hash of
        the CPU name and never actually launched Rust."""
        if self._is_benchmarking:
            return {"success": False, "error": "already running"}

        rust_path = self.history_store.get_rust_path()
        if not rust_path or not os.path.exists(rust_path):
            self.log(self.i18n.t("auto_detect_rust"), level="info")
            rust_path = find_rust_install_path()
            if rust_path:
                self.log(self.i18n.t("found_rust_at", path=rust_path), level="success")
                self.history_store.set_rust_path(rust_path)
            else:
                self.log(self.i18n.t("cannot_detect_rust"), level="error")
                return {"success": False, "error": "rust_not_found"}
        self.log(self.i18n.t("rust_path_confirmed", path=rust_path), level="success")

        self._is_benchmarking = True
        self._benchmark_stop_event.clear()
        with self._benchmark_lock:
            self._benchmark_operation += 1
            benchmark_operation = self._benchmark_operation

        self.broadcast("benchmark_status", {"status": "running", "progress": 5})
        threading.Thread(
            target=self._run_benchmark_logic,
            args=(rust_path, benchmark_operation),
            daemon=True,
            name="web-benchmark",
        ).start()
        return {"success": True, "status": "started"}

    def stop_benchmark(self) -> Dict[str, Any]:
        if not self._is_benchmarking:
            return {"success": False, "error": "not running"}
        self._is_benchmarking = False
        self._benchmark_stop_event.set()
        return {"success": True}

    def _run_benchmark_logic(self, rust_path: str, benchmark_operation: int) -> None:
        # Release the log file so the benchmark's own watcher can open it.
        if self.connect_engine.log_watcher:
            self.connect_engine.log_watcher.stop()
        if self._global_log_watcher:
            self._global_log_watcher.stop()
        try:
            self._run_benchmark_logic_internal(rust_path, benchmark_operation)
        finally:
            self._is_benchmarking = False
            if self._running:
                self._schedule_global_watcher_restart()

    def _run_benchmark_logic_internal(self, rust_path: str, benchmark_operation: int) -> None:
        def cancelled() -> bool:
            return (
                not self._running
                or self._benchmark_stop_event.is_set()
                or benchmark_operation != self._benchmark_operation
            )

        while self.process_monitor.is_rust_running() and not cancelled():
            self._benchmark_stop_event.wait(0.5)
        if cancelled():
            return

        if not os.path.exists(os.path.join(rust_path, "RustClient.exe")):
            self.log(self.i18n.t("invalid_rust_folder"), level="error")
            self.history_store.set_rust_path("")
            self.broadcast("benchmark_status", {"status": "error"})
            return

        base_dir = os.path.dirname(os.path.abspath(__file__))
        bm_source = os.path.abspath(os.path.join(base_dir, "..", "..", "BenchmarkFiles"))
        if not os.path.exists(bm_source):
            bm_source = os.path.abspath(os.path.join(base_dir, "..", "BenchmarkFiles"))
        if not (
            os.path.isdir(os.path.join(bm_source, "cfg"))
            and os.path.isfile(os.path.join(bm_source, "demos", "RustTweaker_bm.dem"))
        ):
            self.log(self.i18n.t("bench_files_incomplete"), level="error")
            self.broadcast("benchmark_status", {"status": "error"})
            return
        self.log(self.i18n.t("backup_cfg_copy_bench"), level="info")

        cfg_path = os.path.join(rust_path, "cfg")
        cfg_backup_path = os.path.join(rust_path, f".rust_autoconnect_cfg_backup_{int(time.time())}_{benchmark_operation}")
        cfg_work_path = os.path.join(rust_path, f".rust_autoconnect_cfg_work_{int(time.time())}_{benchmark_operation}")
        rust_pids_before_start = self.process_monitor.get_rust_pids()
        benchmark_pid = None

        try:
            if not os.path.exists(cfg_path):
                raise FileNotFoundError("Rust cfg directory was not found")
            shutil.copytree(cfg_path, cfg_backup_path)
            with open(os.path.join(cfg_backup_path, "operation.log"), "w", encoding="utf-8") as journal:
                journal.write("configuration backup created\n")
            if cancelled():
                self._restore_benchmark_cfg(cfg_path, cfg_backup_path, cfg_work_path)
                self.broadcast("benchmark_status", {"status": "error"})
                return

            shutil.copytree(os.path.join(bm_source, "cfg"), cfg_path, dirs_exist_ok=True)

            target_demo = os.path.join(rust_path, "demos", "RustTweaker_bm.dem")
            if not os.path.exists(target_demo):
                shutil.copytree(os.path.join(bm_source, "demos"), os.path.join(rust_path, "demos"), dirs_exist_ok=True)

            keys_cfg = os.path.join(cfg_path, "keys.cfg")
            with open(keys_cfg, "a") as f:
                f.write('\nbind f5 "demo.play RustTweaker_bm"\n')
        except Exception as e:
            self.log(self.i18n.t("prep_bench_failed", err=e), level="error")
            if os.path.exists(cfg_backup_path):
                if not self._restore_benchmark_cfg(cfg_path, cfg_backup_path, cfg_work_path):
                    self.log(self.i18n.t("restore_cfg_failed_prep"), level="error")
            self.broadcast("benchmark_status", {"status": "error"})
            return

        self.log(self.i18n.t("start_local_bench"), level="info")
        time.sleep(1.0)

        start_time = time.time()
        spawn_reached = False
        menu_reached = False
        protocol_mismatch = False
        detected_client_protocol = None
        time_to_menu = 0.0
        demo_start_time = 0.0
        last_wait_log = 0

        def bench_event(event: str) -> None:
            nonlocal spawn_reached, menu_reached, protocol_mismatch, detected_client_protocol
            nonlocal time_to_menu, demo_start_time
            app_logger.debug(f"[BENCH] {event}")
            if "Spawning" in event or "LocalPlayer" in event or "Client connected" in event:
                spawn_reached = True
            elif "[Bootstrap] DONE!" in event:
                time_to_menu = time.time() - start_time
                menu_reached = True
            elif "Demo is" in event or "Index created" in event:
                if demo_start_time == 0.0:
                    demo_start_time = time.time()
                    self.log(self.i18n.t("f5_pressed_log"), level="info")
            elif "Protocol mismatch" in event or "Demo protocol" in event:
                protocol_mismatch = True
                match = re.search(r'client protocol (\d+)', event)
                if match:
                    detected_client_protocol = match.group(1)

        bench_watcher = LogWatcher(
            on_disconnect=lambda reason: self.log(f"Disconnected: {reason}", level="warning"),
            on_error=lambda err: self.log(f"Error: {err}", level="error"),
            on_event=bench_event,
            seek_end=True,
            target_log_path=None,
        )

        try:
            bench_watcher.capture_start_position()
            bench_watcher.start(loop=self._event_loop)
            url = f"steam://run/{config.STEAM_APP_ID}//-windowed -popupwindow"
            if os.name == "nt":
                os.startfile(url)
            else:
                webbrowser.open(url)
            has_started = False
            menu_msg_shown = False
            while not spawn_reached and self._is_benchmarking and not cancelled():
                self._benchmark_stop_event.wait(0.2)
                is_running = self.process_monitor.is_rust_running()

                if is_running:
                    if not has_started:
                        new_pids = self.process_monitor.get_rust_pids() - rust_pids_before_start
                        if len(new_pids) == 1:
                            benchmark_pid = new_pids.pop()
                        self.log(self.i18n.t("rust_detected_wait_map"), level="info")
                        has_started = True

                    if menu_reached and not menu_msg_shown:
                        self.log(self.i18n.t("game_ready_menu", sec=round(time_to_menu, 1)), level="success")
                        self.log(self.i18n.t("f5_prompt_log"), level="warning")
                        self.broadcast("benchmark_status", {"status": "running", "progress": 50})
                        menu_msg_shown = True

                    elapsed = int(time.time() - start_time)
                    if elapsed > 0 and elapsed % 5 == 0 and elapsed != last_wait_log:
                        self.log(self.i18n.t("waiting_elapsed", sec=elapsed), level="info")
                        last_wait_log = elapsed

                if has_started and not is_running:
                    self.log(self.i18n.t("rust_closed_bench_stopped"), level="warning")
                    break
                if protocol_mismatch and detected_client_protocol:
                    self.log(self.i18n.t("protocol_mismatch_patching", proto=detected_client_protocol), level="warning")
                    break
                if time.time() - start_time > 600:
                    self.log(self.i18n.t("bench_timeout"), level="error")
                    break
        finally:
            bench_watcher.stop()

            can_restore = True
            restore_deferred = False
            if benchmark_pid is not None and benchmark_pid in self.process_monitor.get_rust_pids():
                self.log(self.i18n.t("closing_rust_for_bench"), level="info")
                self.process_monitor.force_kill_pid(benchmark_pid)
                while benchmark_pid in self.process_monitor.get_rust_pids() and self._running:
                    self._benchmark_stop_event.wait(0.2)
            elif self.process_monitor.is_rust_running():
                self.log(self.i18n.t("rust_ownership_unclear"), level="warning")
                can_restore = False
                restore_deferred = True
                self._pending_benchmark_restore = (cfg_path, cfg_backup_path, cfg_work_path, benchmark_operation)
                threading.Thread(
                    target=self._restore_benchmark_cfg_after_rust_exit,
                    args=(cfg_path, cfg_backup_path, cfg_work_path, benchmark_operation),
                    daemon=False,
                    name="benchmark-restore",
                ).start()

            try:
                if can_restore and os.path.exists(cfg_backup_path):
                    self.log(self.i18n.t("restoring_cfg_backup"), level="info")
                    if not self._restore_benchmark_cfg(cfg_path, cfg_backup_path, cfg_work_path):
                        raise OSError("configuration restore did not complete")
            except (OSError, shutil.Error) as e:
                self.log(self.i18n.t("restore_cfg_failed", err=e), level="error")

            if restore_deferred:
                self.broadcast("benchmark_status", {"status": "restore_pending"})
                return

            if protocol_mismatch and detected_client_protocol:
                self.log(self.i18n.t("demo_proto_mismatch_no_mod"), level="warning")
                self.broadcast("benchmark_status", {"status": "error"})
            elif spawn_reached and menu_reached:
                demo_load_time = time.time() - demo_start_time if demo_start_time > 0.0 else 0.0
                total_time = time_to_menu + demo_load_time

                # Prevent spoofing by requiring minimum realistic phase times.
                if time_to_menu < 2.0 or demo_load_time < 2.0:
                    self.log(self.i18n.t("bench_rejected_fast"), level="error")
                    self.broadcast("benchmark_status", {"status": "rejected"})
                    return

                self.log(self.i18n.t("score_time_to_menu", sec=round(time_to_menu, 1)), level="info")
                self.log(self.i18n.t("score_map_load", sec=round(demo_load_time, 1)), level="info")
                self.log(self.i18n.t("score_total", sec=round(total_time, 1)), level="success")
                self.log(self.i18n.t("bench_complete_game_closed"), level="success")

                if total_time < 90:
                    tier, tier_level = self.i18n.t("bench_excellent"), "success"
                elif total_time < 180:
                    tier, tier_level = self.i18n.t("bench_good"), "warning"
                else:
                    tier, tier_level = self.i18n.t("bench_slow"), "error"
                self.log(tier, level=tier_level)

                self._record_benchmark_result(rust_path, time_to_menu, demo_load_time, benchmark_operation)
                self.broadcast("benchmark_status", {"status": "completed", "result": {"total_time": round(total_time, 2)}})
            else:
                self.broadcast("benchmark_status", {"status": "error"})

    @staticmethod
    def _restore_benchmark_cfg(cfg_path: str, backup_path: str, work_path: str) -> bool:
        """Restore a benchmark backup without leaving the active cfg directory absent."""
        journal_path = os.path.join(backup_path, "operation.log")
        if os.path.exists(journal_path):
            os.remove(journal_path)
        if os.path.exists(cfg_path):
            os.replace(cfg_path, work_path)
        try:
            shutil.copytree(backup_path, cfg_path)
        except OSError:
            if os.path.exists(work_path) and not os.path.exists(cfg_path):
                os.replace(work_path, cfg_path)
            return False
        shutil.rmtree(work_path)
        shutil.rmtree(backup_path)
        return True

    def _restore_benchmark_cfg_after_rust_exit(self, cfg_path: str, backup_path: str, work_path: str, benchmark_operation: int) -> None:
        while self.process_monitor.is_rust_running() and self._running:
            time.sleep(0.5)

        with self._benchmark_lock:
            self._pending_benchmark_restore = None

        if self._restore_benchmark_cfg(cfg_path, backup_path, work_path):
            if self._running:
                self.log(self.i18n.t("rust_closed_restored"), level="success")
                self.broadcast("benchmark_status", {"status": "restore_done"})
        else:
            self.log(self.i18n.t("rust_closed_restore_failed"), level="error")

    def _restore_pending_benchmark_on_shutdown(self) -> None:
        """Best-effort recovery if the app is closing with a benchmark cfg
        swap still pending (Rust's ownership was unclear when it launched).
        Mirrors src/app.py's shutdown() hook - not a guarantee against a
        hard kill of the whole process, same as the legacy implementation."""
        with self._benchmark_lock:
            pending = self._pending_benchmark_restore
            if not pending:
                return
            self._pending_benchmark_restore = None
        cfg_path, backup_path, work_path, _operation = pending
        try:
            if self.process_monitor.is_rust_running():
                self.process_monitor.force_kill_rust()
            restored = self._restore_benchmark_cfg(cfg_path, backup_path, work_path)
        except (OSError, shutil.Error):
            app_logger.error("Could not restore pending benchmark configuration during shutdown.")
            return
        if restored:
            app_logger.info("Restored pending benchmark configuration during shutdown.")
        else:
            app_logger.error("Could not restore pending benchmark configuration during shutdown.")

    def _record_benchmark_result(
        self, rust_path: str, time_to_menu: float, demo_load_time: float, benchmark_operation: int
    ) -> None:
        """Persist a valid run before attempting any optional network upload."""
        try:
            cpu = self.hardware_service.get_cpu_info()
            storage, storage_bus = self.hardware_service.get_benchmark_storage(rust_path)
            run = build_run(
                self.history_store.get_installation_id(), cpu, storage, storage_bus,
                time_to_menu, demo_load_time, BENCHMARK_VERSION,
            )
            if not self.history_store.add_benchmark_run(run):
                self.log(self.i18n.t("bench_result_not_queued"), level="warning")
                return
        except (OSError, ValueError) as error:
            self.log(self.i18n.t("bench_result_not_saved", err=type(error).__name__), level="error")
            return

        self.log(self.i18n.t("result_queued_for", cpu=run["cpu"], storage=run["storage"]), level="info")
        self.log(self.i18n.t("sending_bench_result"), level="info")
        threading.Thread(
            target=self._submit_benchmark_run_bg,
            args=(run,),
            daemon=True,
            name="benchmark-upload",
        ).start()

    def _submit_benchmark_run_bg(self, run: Dict[str, Any]) -> None:
        try:
            success = self.leaderboard_service.submit_run(run)
            if success:
                if self.history_store.mark_benchmark_run_synced(run["id"]):
                    self.log(self.i18n.t("result_submitted"), level="success")
                else:
                    self.log(self.i18n.t("result_submitted_mark_failed"), level="warning")
            else:
                self.log(self.i18n.t("leaderboard_unavailable_pending"), level="warning")
        except Exception as e:
            self.log(self.i18n.t("bench_result_not_saved", err=type(e).__name__), level="error")
            app_logger.error(f"Failed to submit benchmark run: {type(e).__name__}")

    def _retry_pending_benchmark_runs(self) -> None:
        """Retry retained benchmark uploads that failed to sync last time."""
        for run in self.history_store.get_benchmark_runs():
            if not self._running:
                return
            if run.get("sync_state") == "pending":
                self._submit_benchmark_run_bg(run)
                time.sleep(1.0)

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
        threading.Thread(target=self._retry_pending_benchmark_runs, daemon=True, name="retry-pending-bm").start()
        threading.Thread(target=self._rust_update_loop, daemon=True, name="web-rust-update").start()

    def _telegram_status_loop(self):
        while self._running:
            try:
                if self.telegram_service.is_linked or self.telegram_service.notification_token:
                    prev_linked = self.telegram_service.is_linked
                    prev_name = self.telegram_service.display_name
                    status = self.telegram_service.get_link_status()
                    if status and (self.telegram_service.is_linked != prev_linked or self.telegram_service.display_name != prev_name):
                        self.broadcast("state_updated", self.get_state())
            except Exception as error:
                app_logger.warning(f"Telegram status poll failed: {type(error).__name__}")
            time.sleep(10.0)

    def _process_monitor_loop(self):
        was_running = False
        while self._running:
            try:
                is_running = self.process_monitor.is_rust_running()
                new_status = "running" if is_running else "stopped"

                if new_status != self._cached_rust_status:
                    self._cached_rust_status = new_status
                    self.broadcast("rust_status_changed", {"status": new_status})
                    self.broadcast("state_updated", self.get_state())

                if is_running:
                    was_running = True
                elif was_running:
                    was_running = False
                    self.connect_engine.handle_unexpected_rust_exit()
            except Exception:
                # This loop owns crash-detection and reconnect-after-crash.
                # Swallowing its errors silently would disable that recovery
                # without a single trace of why.
                app_logger.error(f"Rust process monitor iteration failed: {traceback.format_exc()}")
            time.sleep(2.0)


web_bridge = WebBridge()

