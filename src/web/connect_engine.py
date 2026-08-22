# -*- coding: utf-8 -*-
"""Web-native smart connect engine.

The web UI's Connect button previously just fired a one-shot steam:// URL.
This gives it the same "smart" behavior the legacy Tkinter GUI already has:
wipe-aware turbo polling, waiting out a pre-wipe restart, real confirmation
via Rust's own log file, Swarm hints, and AutoArm reconnect on disconnect.

It reuses the same UI-agnostic building blocks as src/app.py's AppController
(ConnectionSession, LogWatcher, a2s_client, steam_service, swarm_service,
server_intelligence_service) instead of re-deriving the logic, and drives the
aiohttp WebBridge (bridge.log / bridge.broadcast) instead of Tkinter widgets.
"""
import os
import re
import socket
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from ..core.a2s_client import a2s_client
from ..core.config import config
from ..core.history_store import history_store
from ..core.i18n import i18n
from ..core.network_clock import NetworkClock
from ..core.smart_monitor import ConnectionPhase, ConnectionSession
from ..services import steam_service
from ..services.log_watcher import LogWatcher
from ..services.server_intelligence_service import server_intelligence_service
from ..services.swarm_service import swarm_service
from ..services.telegram_service import telegram_service


def _resolve_hostname_bounded(host: str, timeout: float = 2.0) -> tuple[str, str]:
    """Resolve a hostname with a hard timeout (shutdown(wait=False) so a slow
    DNS server can't block this call past `timeout`)."""
    import concurrent.futures
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(socket.gethostbyname, host)
        try:
            return future.result(timeout=timeout), ""
        except concurrent.futures.TimeoutError:
            return host, f"DNS resolution timed out for {host}"
        except socket.gaierror as e:
            return host, str(e)
        except Exception as e:
            return host, str(e)
    finally:
        pool.shutdown(wait=False)


def _log_reports_attempt(event: str, target: str, session: Optional[ConnectionSession]) -> bool:
    targets = {target.lower()}
    if ":" in target:
        targets.add(target.split(":", 1)[0].lower())
    if session and session.canonical_endpoint:
        targets.add(session.canonical_endpoint.lower())
        if ":" in session.canonical_endpoint:
            targets.add(session.canonical_endpoint.split(":", 1)[0].lower())
    match = re.search(r"Connecting:\s*([A-Za-z0-9.-]+(?::\d{1,5})?)", event, re.IGNORECASE)
    if match:
        observed = match.group(1).lower()
        return observed in targets or (":" in observed and observed.split(":", 1)[0] in targets)
    return False


def _log_confirms_connection(event: str, target: str, session: Optional[ConnectionSession]) -> bool:
    expected = {target.lower()}
    if ":" in target:
        expected.add(target.split(":", 1)[0].lower())
    if session and session.canonical_endpoint:
        expected.add(session.canonical_endpoint.lower())
        if ":" in session.canonical_endpoint:
            expected.add(session.canonical_endpoint.split(":", 1)[0].lower())

    match = re.search(r"Client connected to\s+([A-Za-z0-9.-]+:\d{1,5})", event, re.IGNORECASE)
    if match:
        return match.group(1).lower() in expected
    if "Client connected" in event:
        return bool(session and session.target_connection_attempt_seen)
    return bool(
        session
        and session.target_connection_attempt_seen
        and re.search(r"\bClient\s*:\s*OnClientConnected\b", event, re.IGNORECASE)
    )


class WebConnectController:
    """Drives one smart-connect session at a time for the web UI."""

    def __init__(self, bridge):
        self.bridge = bridge
        self.network_clock = NetworkClock()
        self._active_session: Optional[ConnectionSession] = None
        self._operation_id = 0
        self._poll_stop_event = threading.Event()
        self._poll_wake_event = threading.Event()
        self.log_watcher: Optional[LogWatcher] = None
        self.is_polling = False
        self.is_connected = False
        self._poll_thread: Optional[threading.Thread] = None

        swarm_service.is_enabled = history_store.get_swarm_enabled()
        swarm_service.on_swarm_event = self._on_swarm_event
        swarm_service.on_status = self._on_swarm_status
        if swarm_service.is_enabled:
            swarm_service.start()

    def set_swarm_enabled(self, enabled: bool) -> None:
        swarm_service.is_enabled = enabled
        if enabled:
            swarm_service.start()
        else:
            swarm_service.stop()

    def _is_current(self, operation_id: int, session: ConnectionSession) -> bool:
        return (
            operation_id == self._operation_id
            and session is self._active_session
            and not self._poll_stop_event.is_set()
        )

    def stop(self, *, explicit: bool = True) -> None:
        self.is_polling = False
        self._operation_id += 1
        self._poll_stop_event.set()
        self._poll_wake_event.set()
        if explicit and self._active_session:
            self._active_session.cancel()
            self._active_session = None
        if self.log_watcher:
            self.log_watcher.stop()
            self.log_watcher = None
        swarm_service.leave_room()

    def connect(self, target: str, *, queue_on_full: bool = False) -> None:
        """Start (or restart) a smart connect session toward `target` (ip:port)."""
        self.stop(explicit=True)
        self._poll_stop_event = threading.Event()
        self._poll_wake_event = threading.Event()
        self._operation_id += 1
        operation_id = self._operation_id
        self.is_polling = True
        self.is_connected = False

        session = ConnectionSession(requested_endpoint=target)
        session.queue_on_full = queue_on_full
        self._active_session = session

        self._poll_thread = threading.Thread(
            target=self._run_logic, args=(target, operation_id, session),
            daemon=True, name="web-connect-poll",
        )
        self._poll_thread.start()

    def wait_idle(self, timeout: float = 2.0) -> None:
        """Block until the current polling thread has actually exited.

        stop() only signals cancellation - it doesn't wait. Tests (and any
        caller that needs a deterministic "fully stopped" state) should use
        this instead of assuming stop() returning means the thread is gone.
        """
        thread = self._poll_thread
        if thread is not None:
            thread.join(timeout=timeout)

    def _run_logic(self, target: str, operation_id: int, session: ConnectionSession) -> None:
        try:
            try:
                host, port_str = target.split(":", 1)
                port = int(port_str)
            except ValueError:
                self.bridge.log(i18n.t("err_invalid_address"), level="error")
                self.stop(explicit=False)
                self.bridge._session_status = "idle"
                self.bridge.broadcast("state_updated", self.bridge.get_state())
                return

            self.bridge.log(i18n.t("log_resolving_ip", host=host), level="info")
            real_ip, dns_error = _resolve_hostname_bounded(host)
            if dns_error:
                self.bridge.log(i18n.t("log_dns_failed", host=host), level="warning")
            elif real_ip != host:
                self.bridge.log(i18n.t("log_dns_resolved", real_ip=real_ip), level="success")

            if not self._is_current(operation_id, session):
                return

            canonical_target = f"{real_ip}:{port}"
            session.canonical_endpoint = canonical_target
            session.force_wipe_at = steam_service.relevant_force_wipe_at(self.network_clock.now())

            self._refresh_provider_hint(operation_id, session, canonical_target)

            if session.begin_wipe_restart_hold(self.network_clock.now()):
                self.bridge.log(i18n.t("log_wipe_restart_wait"), level="warning")

            swarm_service.join_room(canonical_target)
            history_store.add_to_history(target, host, canonical_target)
            self.bridge.broadcast("state_updated", self.bridge.get_state())
            self.bridge.log(i18n.t("log_smart_monitor_start", canonical_target=canonical_target), level="info")

            while self._is_current(operation_id, session):
                now = self.network_clock.now()
                provider_requested = session.provider_last_requested_at
                if provider_requested is None or (now - provider_requested).total_seconds() >= 55:
                    self._refresh_provider_hint(operation_id, session, canonical_target)

                if session.begin_wipe_restart_hold(now):
                    self.bridge.log(i18n.t("log_wipe_restart_wait_loop"), level="warning")

                status = a2s_client.check_server_status(real_ip, port, session.stop_event)
                if not self._is_current(operation_id, session):
                    return

                if session.observe_query_result(status.alive, self.network_clock.now()):
                    self.bridge.log(i18n.t("log_server_stopped_responding"), level="warning")

                if status.alive:
                    has_capacity = status.max_players <= 0 or status.player_count < status.max_players
                    if has_capacity or session.queue_on_full:
                        self._dispatch_launch(operation_id, session, canonical_target, queue_mode=not has_capacity)
                        return
                    self.bridge.log(
                        i18n.t("log_server_full", player_count=status.player_count, max_players=status.max_players),
                        level="warning",
                    )
                    wait = session.full_server_retry_seconds(self.network_clock.now())
                else:
                    wait = session.query_retry_seconds(self.network_clock.now())

                self._poll_wake_event.wait(wait)
                self._poll_wake_event.clear()
        finally:
            if self._active_session is session:
                self.is_polling = False

    def _refresh_provider_hint(self, operation_id: int, session: ConnectionSession, endpoint: str) -> None:
        if session.provider_refresh_in_flight:
            return
        session.provider_refresh_in_flight = True
        session.provider_last_requested_at = self.network_clock.now()

        def work() -> None:
            try:
                snapshot = server_intelligence_service.observe_endpoint(endpoint, active=True)
                if not self._is_current(operation_id, session):
                    return
                wipe_at = (
                    datetime.fromtimestamp(snapshot.wipe_at, timezone.utc)
                    if snapshot.wipe_at else None
                )
                online = snapshot.online if snapshot.fresh else None
                changed = session.apply_provider_hint(
                    online=online, wipe_at=wipe_at, source=snapshot.source,
                    confidence=snapshot.confidence, checked_at=snapshot.checked_at,
                    now=self.network_clock.now(),
                )
                if online is False and changed:
                    if session.confirm_wipe_restart():
                        self.bridge.log(i18n.t("log_wipe_restart_detected_cache"), level="warning")
                    self._poll_wake_event.set()
                # A changed map seed near force-wipe time is direct proof the map
                # regenerated - the same signal community wipe trackers rely on.
                if snapshot.fresh and snapshot.map_seed is not None:
                    fingerprint = (snapshot.map_seed, snapshot.map_size)
                    if session.observe_provider_wipe_fingerprint(fingerprint, now=self.network_clock.now()):
                        if session.confirm_wipe_restart():
                            self.bridge.log(i18n.t("log_map_change_detected"), level="warning")
                        session.request_turbo(self.network_clock.now())
                        self._poll_wake_event.set()
            finally:
                session.provider_refresh_in_flight = False

        threading.Thread(target=work, daemon=True, name="web-provider-refresh").start()

    def _dispatch_launch(self, operation_id: int, session: ConnectionSession, target: str, *, queue_mode: bool) -> None:
        try:
            session.launched_by_app = True
            session.steam_url_dispatched = True
            session.steam_request_started_at = time.monotonic()
            self._start_log_monitor(target, session, operation_id)
            url = steam_service.build_connect_url(target, config.STEAM_APP_ID)
            if os.name == "nt":
                os.startfile(url)
            else:
                import webbrowser
                webbrowser.open(url)
            queue_suffix = i18n.t("log_launch_sent_queue_suffix") if queue_mode else ""
            self.bridge.log(i18n.t("log_launch_sent") + queue_suffix, level="success")
            self.bridge._session_status = "Queueing" if queue_mode else "Launching"
            self.bridge._last_connected_ip = target
            self.bridge.broadcast("state_updated", self.bridge.get_state())
            self._start_confirmation_watchdog(session, target, queue_mode=queue_mode)
        except Exception as err:
            self.bridge.log(i18n.t("log_launch_error", err=str(err)), level="error")
            self.stop(explicit=False)

    def _start_confirmation_watchdog(self, session: ConnectionSession, target: str, *, queue_mode: bool) -> None:
        timeout = 900.0 if queue_mode else 120.0

        def watch() -> None:
            if self._poll_stop_event.wait(timeout):
                return
            if self._active_session is session and not self.is_connected:
                self.bridge.log(
                    i18n.t("log_confirm_watchdog_timeout", target=target, timeout=int(timeout)),
                    level="warning",
                )

        threading.Thread(target=watch, daemon=True, name="web-confirm-watchdog").start()

    def _start_log_monitor(self, target: str, session: ConnectionSession, operation_id: int) -> None:
        if self.log_watcher:
            self.log_watcher.stop()
            self.log_watcher = None
        self.is_connected = False
        watcher: Optional[LogWatcher] = None

        def handle_event(event: str) -> None:
            if watcher is not self.log_watcher or self._active_session is not session:
                return
            if not self.is_connected and _log_confirms_connection(event, target, session):
                self.is_connected = True
                session.phase = ConnectionPhase.CONNECTED
                self.bridge.log(i18n.t("log_connection_confirmed", target=target), level="success")
                self.bridge._session_status = "Connected"
                self.bridge.broadcast("state_updated", self.bridge.get_state())
                threading.Thread(target=telegram_service.notify, args=("connected", target), daemon=True, name="telegram-connected").start()
                threading.Thread(target=swarm_service.broadcast_success, args=(target,), daemon=True).start()
                threading.Thread(target=swarm_service.broadcast_stop_spam, args=(target,), daemon=True).start()
                self.is_polling = False
                self._poll_stop_event.set()
                self._poll_wake_event.set()
            elif not session.target_connection_attempt_seen and _log_reports_attempt(event, target, session):
                session.target_connection_attempt_seen = True

        def handle_disconnect(reason: str) -> None:
            self.bridge.log(i18n.t("log_disconnected", reason=reason), level="warning")
            was_connected = self.is_connected
            self.is_connected = False
            armed = history_store.get_armed_server()
            should_reconnect = (
                was_connected
                and history_store.get_auto_arm()
                and armed
                and armed in (target, session.canonical_endpoint)
            )
            self.stop(explicit=True)
            self.bridge._session_status = "idle"
            self.bridge.broadcast("state_updated", self.bridge.get_state())
            if should_reconnect:
                self.bridge.log(i18n.t("log_autoreconnect"), level="info")
                self.connect(target)

        watcher = LogWatcher(
            on_disconnect=handle_disconnect,
            on_error=lambda err: self.bridge.log(i18n.t("log_read_log_error", err=str(err)), level="error"),
            on_event=handle_event,
        )
        self.log_watcher = watcher
        # Ignore any stale lines already in the log (e.g. a previous session's
        # "Client connected") so they can't be misread as confirming this one.
        watcher.capture_start_position()
        watcher.start(loop=self.bridge._event_loop)

    def _on_swarm_status(self, status: str) -> None:
        levels = {
            "disabled": "info", "not_configured": "warning", "invalid_key": "error",
            "connecting": "info", "connected": "success", "disconnected": "warning", "error": "error",
        }
        key = f"swarm_{status}"
        message = i18n.t(key) if key in levels else f"Swarm: {status}"
        self.bridge.log(message, level=levels.get(status, "info"))

    def _on_swarm_event(self, event_name: str, ip_port: str) -> None:
        if not self.is_polling:
            return
        session = self._active_session
        if not session or session.canonical_endpoint != ip_port:
            return
        if event_name == "server_connected":
            self._poll_wake_event.set()
        elif event_name == "swarm_stop_spam" and not session.launched_by_app:
            self.bridge.log(i18n.t("log_swarm_paused"), level="info")
            self.stop(explicit=True)
            self.bridge._session_status = "idle"
            self.bridge.broadcast("state_updated", self.bridge.get_state())
