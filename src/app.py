import socket
import threading
import time
import webbrowser
import os
import re
import shutil
import queue
from datetime import datetime, timezone
import customtkinter as ctk
from typing import Callable, Optional

from .core.config import config
from .core.i18n import i18n
from .core.history_store import history_store
from .core.a2s_client import a2s_client
from .core.benchmark_model import BENCHMARK_VERSION, build_run
from .core.smart_monitor import ConnectionPhase, ConnectionSession, PollingPolicy
from .core.network_clock import NetworkClock
from .services.log_watcher import LogWatcher
from .services.process_monitor import process_monitor
from .services.server_intelligence_service import server_intelligence_service
from .services import steam_service
from .services.telegram_service import telegram_service
from .gui.main_window import COLORS, MainWindow
from .core.logger import app_logger


def _is_valid_endpoint(value: str) -> bool:
    """Accept a bounded hostname-or-IP endpoint without interpreting it as a URL."""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9.-]{1,253}:\d{1,5}", value):
        return False
    try:
        return 1 <= int(value.rsplit(":", 1)[1]) <= 65535
    except ValueError:
        return False


class AppController(MainWindow):
    """
    Main Application Controller acting as state machine and orchestrator
    connecting GUI, history_store, a2s_client, log_watcher, and process_monitor.
    """
    def __init__(self):
        super().__init__(history_mgr=history_store, i18n_mgr=i18n)

        self._state_lock = threading.Lock()
        self._operation_lock = threading.Lock()
        self._poll_stop_event = threading.Event()
        self._poll_wake_event = threading.Event()
        self._update_ready_event = threading.Event()
        self._update_ready_event.set()
        self._update_check_wake_event = threading.Event()
        self._update_required = False
        self._update_steam_opened = False
        self._update_status_logged = ""
        self.network_clock = NetworkClock()
        self._shutdown_event = threading.Event()
        self._benchmark_stop_event = threading.Event()
        self._ui_queue: queue.Queue[tuple[Optional[tuple[str, int]], Callable, tuple, dict]] = queue.Queue()
        self._poll_operation = 0
        self._benchmark_operation = 0
        self._pending_benchmark_restore = None
        self._global_watcher_after_id = None
        self._is_polling = False
        self._is_reconnecting = False
        self.poll_thread = None
        self._active_session: Optional[ConnectionSession] = None
        self._last_smart_phase: Optional[ConnectionPhase] = None
        self.log_watcher: Optional[LogWatcher] = None
        self.a2s_client = a2s_client
        self.process_monitor = process_monitor
        self.server_intelligence = server_intelligence_service
        self._ui_queue_after_id = self.after(50, self._drain_ui_queue)

        from .services.hardware_service import hardware_service
        self.hardware_service = hardware_service
        
        self.log_safe(self.t("ready"))
        threading.Thread(target=self._report_telegram_status, daemon=True, name="telegram-status-log").start()
        # Asyncio integration is owned by LogWatcher.  Polling itself runs in
        # a dedicated thread, so it must never be submitted as a coroutine.
        import asyncio
        self.async_loop = asyncio.new_event_loop()
        from .services.swarm_service import swarm_service
        self.swarm_service = swarm_service
        self.swarm_service.is_enabled = self.history_store.get_swarm_enabled()
        self.swarm_service.on_swarm_event = self._on_swarm_event
        self.swarm_service.on_presence_update = self._on_swarm_presence
        self.swarm_service.on_status = self._on_swarm_status
        if self.swarm_service.is_enabled:
            self.swarm_service.start()
        else:
            self._on_swarm_status("disabled")

        self.async_thread = threading.Thread(target=self._run_async_loop, daemon=True, name="async-loop")
        self.async_thread.start()
        self._start_global_log_watcher()

        # Start background status and update monitoring loops
        threading.Thread(target=self.check_rust_status_loop, daemon=True, name="rust-status-check").start()
        threading.Thread(target=self.check_rust_update_loop, daemon=True, name="rust-update-check").start()
        threading.Thread(target=self.check_application_version, daemon=True, name="app-version-check").start()
        threading.Thread(target=self._retry_pending_benchmark_runs, daemon=True, name="retry-pending-bm").start()
        threading.Thread(target=self._share_saved_servers_loop, daemon=True, name="shared-server-interest").start()
        
        # Keep load_hardware synchronous as it calls blocking wmi/psutil
        threading.Thread(target=self._load_hardware, daemon=True).start()
        
    def _run_async_loop(self):
        import asyncio
        asyncio.set_event_loop(self.async_loop)
        self.async_loop.run_forever()

    def _report_telegram_status(self) -> None:
        """Log one human-readable Telegram state per application start."""
        status = telegram_service.get_link_status()
        if status is None:
            self.log_safe(self.t("tg_status_unavailable"), "#98A2B3")
        elif status.get("linked"):
            name = status.get("display_name") or self.t("tg_status_user")
            self.log_safe(self.t("tg_log_connected", name=name), COLORS["success"])
        else:
            self.log_safe(self.t("tg_log_unlinked"), "#98A2B3")
        self.dispatch_ui(self._apply_telegram_status, status or {})

    def _drain_ui_queue(self):
        """Run worker-thread UI requests only while this controller is active."""
        while not self._shutdown_event.is_set():
            try:
                operation, callback, args, kwargs = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            if operation is not None and not self._is_current_operation(operation):
                continue
            try:
                callback(*args, **kwargs)
            except Exception as error:
                app_logger.warning(f"UI callback failed: {type(error).__name__}")
        if not self._shutdown_event.is_set():
            self._ui_queue_after_id = self.after(50, self._drain_ui_queue)

    def dispatch_ui(self, callback: Callable, *args, operation: Optional[tuple[str, int]] = None, **kwargs) -> None:
        if not self._shutdown_event.is_set():
            self._ui_queue.put((operation, callback, args, kwargs))

    def _is_current_operation(self, operation: tuple[str, int]) -> bool:
        kind, operation_id = operation
        with self._operation_lock:
            if kind == "poll":
                return operation_id == self._poll_operation
            if kind == "benchmark":
                return operation_id == self._benchmark_operation
        return False

    def _next_poll_operation(self) -> int:
        with self._operation_lock:
            self._poll_operation += 1
            return self._poll_operation

    def _is_current_poll_operation(self, operation_id: int) -> bool:
        with self._operation_lock:
            is_current = self._poll_operation == operation_id
        return not self._shutdown_event.is_set() and is_current and self.is_polling

    def _is_current_session(self, operation_id: int, session: ConnectionSession) -> bool:
        return (
            self._is_current_poll_operation(operation_id)
            and self._active_session is session
            and not session.stop_event.is_set()
        )

    def _wait_for_rust_update(self, operation_id: int, session: ConnectionSession) -> bool:
        """Delay only the current launch while a known Rust update is pending."""
        if self._update_ready_event.is_set():
            return self._is_current_session(operation_id, session)
        session.phase = ConnectionPhase.WATCH
        self.dispatch_ui(self.set_connection_phase, "waiting_update", operation=("poll", operation_id))
        self.log_safe("Rust update is pending; waiting before launch.", "#F97316")
        self._update_check_wake_event.set()
        while self._is_current_session(operation_id, session):
            if self._update_ready_event.wait(0.25):
                return self._is_current_session(operation_id, session)
        return False

    def _update_server_profile(self, endpoint: str, **values) -> None:
        """Best-effort local profile update; controller stubs have no store."""
        store = self.__dict__.get("history_store")
        if store is not None:
            store.update_server_profile(endpoint, **values)

    def _share_saved_servers_loop(self) -> None:
        """Opt-in background heartbeat for the shared provider catalogue."""
        while not self._shutdown_event.is_set():
            if self.history_store.get_share_saved_servers():
                endpoints = []
                for item in self.history_store.get_history():
                    endpoint = item.get("canonical_endpoint") or item.get("ip")
                    if isinstance(endpoint, str) and _is_valid_endpoint(endpoint):
                        endpoints.append(endpoint)
                self.server_intelligence.share_saved_endpoints(endpoints)
            self._shutdown_event.wait(600)

    def _refresh_provider_hint(self, operation_id: int, session: ConnectionSession, endpoint: str) -> None:
        """Fetch provider cache off the polling path; A2S never waits for it."""
        if session.provider_refresh_in_flight:
            return
        session.provider_refresh_in_flight = True
        session.provider_last_requested_at = self.network_clock.now()

        def work() -> None:
            try:
                snapshot = self.server_intelligence.observe_endpoint(endpoint, active=True)
                if not self._is_current_session(operation_id, session):
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
                if snapshot.fresh and (changed or wipe_at is not None):
                    self.log_safe(self.t("provider_cache_updated"), "#98A2B3")
                if online is False and changed:
                    if session.confirm_wipe_restart():
                        self.log_safe(self.t("wipe_restart_detected"), "#F97316")
                    self.log_safe(self.t("provider_offline_turbo"), "#F97316")
                    self._poll_wake_event.set()
            finally:
                session.provider_refresh_in_flight = False

        threading.Thread(target=work, daemon=True, name="provider-cache-refresh").start()

    @property
    def is_polling(self) -> bool:
        with self._state_lock:
            return self._is_polling

    @is_polling.setter
    def is_polling(self, val: bool):
        with self._state_lock:
            self._is_polling = val

    @property
    def is_reconnecting(self) -> bool:
        with self._state_lock:
            return self._is_reconnecting

    @is_reconnecting.setter
    def is_reconnecting(self, val: bool):
        with self._state_lock:
            self._is_reconnecting = val

    def _start_global_log_watcher(self):
        def handle_disconnect(reason):
            # The per-connection watcher owns a launch initiated by this app.
            # Avoid racing it with the always-on observer.
            if getattr(self, "log_watcher", None) and self.log_watcher.is_monitoring:
                return
            if getattr(self, 'is_polling', False) and getattr(self, 'log_watcher', None) is not None:
                # Local log watcher handles disconnects during active polling
                pass
            else:
                armed = self.history_store.get_armed_server()
                session = self._active_session
                if (
                    armed
                    and session
                    and session.launched_by_app
                    and armed in {session.requested_endpoint, session.canonical_endpoint}
                    and not self.is_reconnecting
                ):
                    self.log_safe(self.t("auto_reconnect_monitoring", target=armed), "#F97316")
                    self.start_process_force(armed)
            # A generic disconnect from a manual Rust session is not ours to
            # recover.  Restart the watcher but do not touch the game.
            if not getattr(self, '_is_shutting_down', False):
                self.dispatch_ui(self._schedule_global_watcher_restart)

        def handle_event(event):
            import re
            match = re.search(r"(?:Connecting to|Client connected to)\s+([a-zA-Z0-9.-]+:\d{1,5})", event, re.IGNORECASE)
            if match and self.history_store.get_auto_arm():
                ip_port = match.group(1)
                if getattr(self, '_last_armed_from_log', None) != ip_port:
                    self._last_armed_from_log = ip_port
                    self.history_store.set_armed_server(ip_port)
                    self.dispatch_ui(self.refresh_history_ui)
                    self.dispatch_ui(self._refresh_session_state_once)
                    self.log_safe(self.t("auto_armed_server", default=f"Auto-Armed server: {ip_port}"), "#F97316")

            session = self._active_session
            # A generic loading line is not proof of a manual connection and
            # must never cancel an active safe-connect session.
            if self.is_polling and (not session or not session.launched_by_app) and match:
                self.log_safe(self.t("manual_conn_detected"), "#98A2B3")
                self.stop_polling_safe(explicit=False)

        self.global_log_watcher = LogWatcher(
            on_disconnect=handle_disconnect,
            on_error=lambda e: None,
            on_event=handle_event,
            seek_end=True
        )
        self.global_log_watcher.start(loop=self.async_loop)

    def _schedule_global_watcher_restart(self):
        if self._global_watcher_after_id is not None:
            self.after_cancel(self._global_watcher_after_id)
        self._global_watcher_after_id = self.after(5000, self._start_global_log_watcher)

    def _on_connect_btn_click(self):
        self.start_process(self.get_target_ip())

    def start_process(self, target_str: str):
        if self.is_polling:
            self.stop_polling()
            return
            
        target_str = target_str.strip()
        if target_str and ":" not in target_str:
            target_str = f"{target_str}:28015"
            if hasattr(self, 'ip_var'):
                self.ip_var.set(target_str)

        if not _is_valid_endpoint(target_str):
            self.log_safe(self.t("security_err_invalid_addr"))
            return

        self.ip_entry.configure(state="disabled")
        self.connect_btn.configure(text=self.t("stop"), fg_color="#C74E4E", hover_color="#9E3E3E", text_color="#F2F4F7")
        self.set_connection_state("Monitoring", target_str)
        self._poll_stop_event.clear()
        self._poll_wake_event.clear()
        self.is_polling = True
        self.is_reconnecting = False
        operation_id = self._next_poll_operation()
        # A person who explicitly pressed Connect may want Rust to enter a
        # server queue. Forced/armed reconnects deliberately do not do this.
        self._active_session = ConnectionSession(requested_endpoint=target_str, queue_on_full=True)
        self._last_smart_phase = None
        
        # Reset UI log spam flags
        self._ui_logged_ans = False
        self._ui_logged_wait = False
        self._ui_logged_err = False
        self._last_probe_outcome = ""
        
        self.poll_task = threading.Thread(
            target=self.run_logic,
            args=(target_str, operation_id),
            daemon=True,
            name="server-poll",
        )
        self.poll_task.start()

    def stop_polling(self, explicit: bool = True):
        self.is_polling = False
        self.is_reconnecting = False
        self._next_poll_operation()
        self._poll_stop_event.set()
        self._poll_wake_event.set()
        if explicit and self.__dict__.get('_active_session'):
            self._active_session.cancel()
            self._active_session = None
        log_watcher = self.__dict__.get('log_watcher')
        if log_watcher:
            log_watcher.stop()
            self.log_watcher = None
            
        self.swarm_service.leave_room()

        def _update_ui():
            self.connect_btn.configure(
                text="CONNECT", fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"], text_color=COLORS["canvas"]
            )
            self.ip_entry.configure(state="normal")
            self.set_connection_state("Idle")
            self.log(self.t("poll_stop"))
            
        self.dispatch_ui(_update_ui)

    def stop_polling_safe(self, explicit: bool = True):
        self.stop_polling(explicit)

    def run_logic(self, target: str, operation_id: Optional[int] = None):
        """
        BUG-01 Fix: Wrap reconnect polling logic in try...finally block
        to guarantee self.is_reconnecting = False is ALWAYS executed.
        """
        if operation_id is None:
            operation_id = self._poll_operation
        session = self._active_session
        if session is None or session.requested_endpoint != target:
            session = ConnectionSession(requested_endpoint=target)
            self._active_session = session
        try:
            try:
                host, port_str = target.split(":", 1)
                port = int(port_str)
            except ValueError:
                self.log_safe(self.t("err_port"))
                self.stop_polling_safe()
                return

            # 1. Resolve DNS
            real_ip = host
            try:
                self.log_safe(self.t("dns_resolve", host=host))
                real_ip = socket.gethostbyname(host)
                if real_ip != host:
                    self.log_safe(self.t("dns_ok", ip=real_ip))
            except socket.gaierror:
                self.log_safe(self.t("dns_err", host=host))

            if not self._is_current_session(operation_id, session):
                return

            self.log_safe(self.t("ping_test", ip=real_ip, port=port))

            canonical_target = f"{real_ip}:{port}"
            session.canonical_endpoint = canonical_target
            session.force_wipe_at = steam_service.relevant_force_wipe_at(self.network_clock.now())
            local_force_wipe = session.force_wipe_at.astimezone()
            self.log_safe(
                f"Force Wipe: {local_force_wipe.strftime('%Y-%m-%d %H:%M %Z')} "
                "(19:00 London).",
                "#98A2B3",
            )
            # Provider cache is optional intelligence, not part of the direct
            # connection path. Start it in parallel with the first A2S probe.
            self._refresh_provider_hint(operation_id, session, canonical_target)
            schedule = {"wipe_at": None, "wipe_source": ""}
            if not schedule["wipe_at"]:
                schedule = self.history_store.get_server_wipe_schedule(target)
            if not schedule["wipe_at"] and canonical_target != target:
                schedule = self.history_store.get_server_wipe_schedule(canonical_target)
            if schedule["wipe_at"]:
                session.wipe_at = datetime.fromtimestamp(schedule["wipe_at"], timezone.utc)
                session.wipe_source = schedule["wipe_source"]
                self.log_safe(f"Wipe schedule: {schedule['wipe_source'] or 'shared cache'}.", "#98A2B3")
            if session.begin_wipe_restart_hold(self.network_clock.now()):
                self.log_safe(self.t("waiting_wipe_restart"), "#F97316")
                self.dispatch_ui(
                    self.set_connection_phase,
                    ConnectionPhase.WAITING_FOR_WIPE_RESTART.value,
                    operation=("poll", operation_id),
                )
            
            self.swarm_service.join_room(canonical_target)
            
            self.dispatch_ui(
                self.history_store.add_to_history, target, host, canonical_target,
                operation=("poll", operation_id),
            )
            self.dispatch_ui(self.refresh_history_ui, operation=("poll", operation_id))

            self.log_safe(self.t("start_poll", ip=real_ip, port=port))

            if not self._is_current_session(operation_id, session):
                return

            server_name = host
            while self._is_current_session(operation_id, session):
                provider_requested = session.provider_last_requested_at
                now = self.network_clock.now()
                if (
                    provider_requested is None
                    or (now - provider_requested).total_seconds() >= 55
                ):
                    self._refresh_provider_hint(operation_id, session, canonical_target)

                if session.begin_wipe_restart_hold(now):
                    self.log_safe(self.t("waiting_wipe_restart"), "#F97316")
                    self.dispatch_ui(
                        self.set_connection_phase,
                        ConnectionPhase.WAITING_FOR_WIPE_RESTART.value,
                        operation=("poll", operation_id),
                    )

                # Steam is opened only once below. Rust may take tens of
                # seconds to load, while a healthy server can still restart
                # or disappear. Keep observing A2S until this session's own
                # Player.log watcher confirms the connection; this branch
                # deliberately never launches Steam a second time.
                if session.launched_by_app:
                    status = self.a2s_client.check_server_status(real_ip, port, session.stop_event)
                    if not self._is_current_session(operation_id, session):
                        return
                    outcome = "launch_online" if status.alive else "launch_offline"
                    if outcome != getattr(self, "_last_probe_outcome", ""):
                        self.log_safe(
                            self.t("launch_server_online" if status.alive else "launch_server_offline"),
                            "#48D16D" if status.alive else "#F97316",
                        )
                        self._last_probe_outcome = outcome
                    self._update_server_profile(
                        target,
                        state="queue" if session.queue_requested else ("launching" if status.alive else "offline"),
                        checked_at=int(time.time()),
                    )
                    if session.stop_event.wait(PollingPolicy().launch_confirmation_probe_seconds):
                        break
                    continue

                phase = session.select_phase(self.network_clock.now())
                if (
                    session.force_wipe_at
                    and not session.force_wipe_notified
                    and self.network_clock.now() >= session.force_wipe_at
                ):
                    session.force_wipe_notified = True
                    self.log_safe("Force Wipe window started.", "#F97316")
                    threading.Thread(
                        target=telegram_service.notify,
                        args=("wipe", target),
                        daemon=True,
                        name="telegram-force-wipe",
                    ).start()
                if phase != self._last_smart_phase:
                    labels = {
                        ConnectionPhase.SCHEDULED: self.t("smart_phase_scheduled"),
                        ConnectionPhase.WATCH: self.t("smart_phase_watch"),
                        ConnectionPhase.TURBO: self.t("smart_phase_turbo"),
                    }
                    if phase in labels:
                        self.log_safe(labels[phase], "#F97316" if phase != ConnectionPhase.SCHEDULED else "#98A2B3")
                    self.dispatch_ui(self.set_connection_phase, phase.value, operation=("poll", operation_id))
                    self._last_smart_phase = phase

                status = self.a2s_client.check_server_status(real_ip, port, session.stop_event)
                if not self._is_current_session(operation_id, session):
                    return
                if status.server_name:
                    server_name = status.server_name

                # Near a scheduled wipe a live response can still be the old
                # map. Do not launch Rust until a restart was observed. A
                # fresh provider offline result may release this hold in the
                # parallel hint worker; otherwise require the normal two A2S
                # misses after a known live server, or wait until the planned
                # wipe time has passed while the server is unavailable.
                if session.waiting_for_wipe_restart:
                    restart_detected = False
                    if status.alive:
                        session.observe_query_result(True, now)
                        if not session.wipe_wait_announced_online:
                            self.log_safe(self.t("wipe_old_server_online"), "#98A2B3")
                            session.wipe_wait_announced_online = True
                    else:
                        restart_detected = session.observe_query_result(False, now)
                        restart_detected = restart_detected or session.wipe_time_has_arrived(now)
                    if restart_detected and session.confirm_wipe_restart():
                        self.log_safe(self.t("wipe_restart_detected"), "#F97316")
                    else:
                        self._update_server_profile(target, state="waiting_wipe", checked_at=int(time.time()))
                        current_interval = session.interval_seconds(now)
                        deadline = time.monotonic() + current_interval
                        while self._is_current_session(operation_id, session) and time.monotonic() < deadline:
                            if session.stop_event.wait(0.1):
                                break
                            if self._poll_wake_event.is_set():
                                self._poll_wake_event.clear()
                                break
                        continue

                ready = status.alive and status.has_join_capacity
                if ready:
                    if session.stop_event.wait(PollingPolicy().confirmation_gap_seconds):
                        break
                        
                    confirmed = self.a2s_client.check_server_status(real_ip, port, session.stop_event)
                    if not self._is_current_session(operation_id, session):
                        return
                    if confirmed.alive and confirmed.has_join_capacity:
                        session.consume_hint()
                        session.phase = ConnectionPhase.LAUNCH_REQUESTED
                        self.dispatch_ui(self.set_connection_phase, session.phase.value, operation=("poll", operation_id))
                        self.log_safe(self.t("stable"))
                        self.dispatch_ui(
                            self.history_store.add_to_history, target, server_name, canonical_target,
                            operation=("poll", operation_id),
                        )
                        self.dispatch_ui(self.refresh_history_ui, operation=("poll", operation_id))
                        if self._wait_for_rust_update(operation_id, session):
                            self.launch_game(target, session=session, operation_id=operation_id)
                        break
                    status = confirmed

                # A manual Connect may use Rust's queue, but only after two
                # fresh A2S replies agree that this is a real, full server.
                # A missing/zero capacity is not a queue and never launches
                # Steam, because it can be a starting or unavailable server.
                if (
                    status.alive
                    and status.max_players > 0
                    and not status.has_join_capacity
                    and session.queue_on_full
                ):
                    if session.stop_event.wait(PollingPolicy().confirmation_gap_seconds):
                        break
                    confirmed = self.a2s_client.check_server_status(real_ip, port, session.stop_event)
                    if not self._is_current_session(operation_id, session):
                        return
                    if (
                        confirmed.alive
                        and confirmed.max_players > 0
                        and not confirmed.has_join_capacity
                    ):
                        session.consume_hint()
                        session.phase = ConnectionPhase.QUEUED
                        session.queue_requested = True
                        self.dispatch_ui(self.set_connection_phase, session.phase.value, operation=("poll", operation_id))
                        self.log_safe(self.t("server_full_join_queue"), "#F97316")
                        self.dispatch_ui(
                            self.history_store.add_to_history, target, server_name, canonical_target,
                            operation=("poll", operation_id),
                        )
                        self.dispatch_ui(self.refresh_history_ui, operation=("poll", operation_id))
                        self._update_server_profile(target, state="queue", checked_at=int(time.time()))
                        if self._wait_for_rust_update(operation_id, session):
                            self.launch_game(target, session=session, operation_id=operation_id, queue_mode=True)
                        break
                    # State changed between confirmations; evaluate it again
                    # in the next bounded poll instead of launching on stale data.
                    status = confirmed
                    if status.alive and status.has_join_capacity:
                        continue

                if not (status.alive and status.has_join_capacity):
                    now = self.network_clock.now()
                    restarted = session.observe_query_result(status.alive, now)
                    if not status.alive:
                        profile_state = "offline"
                        current_interval = session.query_retry_seconds(now)
                        outcome = "restart" if restarted else "query_unavailable"
                        if outcome != getattr(self, "_last_probe_outcome", ""):
                            message = (
                                self.t("server_restart_turbo") if restarted
                                else self.t("query_unavailable_retry", sec=round(current_interval, 1))
                            )
                            self.log_safe(message, "#F97316")
                            self._last_probe_outcome = outcome
                    else:
                        profile_state = "full"
                        current_interval = session.full_server_retry_seconds(now)
                        if "full" != getattr(self, "_last_probe_outcome", ""):
                            self.log_safe(self.t("server_full_retry", sec=round(current_interval, 1)), "#F97316")
                            self._last_probe_outcome = "full"
                    self._update_server_profile(target, state=profile_state, checked_at=int(time.time()))
                else:
                    current_interval = session.interval_seconds(self.network_clock.now())

                deadline = time.monotonic() + current_interval
                while self._is_current_session(operation_id, session) and time.monotonic() < deadline:
                    if session.stop_event.wait(0.1):
                        break
                    if self._poll_wake_event.is_set():
                        self._poll_wake_event.clear()
                        break
        finally:
            if self._is_current_poll_operation(operation_id):
                self.is_reconnecting = False
                if getattr(self, '_active_session', None) and self._active_session.phase not in (
                    ConnectionPhase.LAUNCH_REQUESTED, 
                    ConnectionPhase.WAITING_FOR_WIPE_RESTART,
                    ConnectionPhase.QUEUED,
                    ConnectionPhase.AWAITING_LOG_CONFIRMATION, 
                    ConnectionPhase.CONNECTED
                ):
                    self.stop_polling_safe()

    def _on_run_test_click(self):
        if getattr(self, 'is_benchmarking', False):
            self.is_benchmarking = False
            self._benchmark_stop_event.set()
            self.bench_btn.configure(state="disabled", text="Stopping...")
            return
        self.run_benchmark()

    def log_safe(self, msg: str, color: Optional[str] = None):
        self.dispatch_ui(self.log, msg, color=color)

    def _on_swarm_event(self, event_name: str, ip_port: str):
        if not getattr(self, 'is_polling', False):
            return
            
        self.dispatch_ui(self._handle_swarm_event_ui, event_name, ip_port)

    def _on_swarm_status(self, status: str) -> None:
        messages = {
            "disabled": (self.t("swarm_disabled"), "#DE5148"),
            "not_configured": (self.t("swarm_not_configured"), "#DE5148"),
            "invalid_key": (self.t("swarm_invalid_key"), "#DE5148"),
            "connecting": (self.t("swarm_connecting"), "#DE5148"),
            "connected": (self.t("swarm_connected"), "#55C95D"),
            "disconnected": (self.t("swarm_disconnected"), "#DE5148"),
            "error": (self.t("swarm_error"), "#DE5148"),
        }
        message, color = messages.get(status, (self.t("swarm_unavailable"), "#DE5148"))
        self.log_safe(message, color)

    def _handle_swarm_event_ui(self, event_name: str, ip_port: str):
        if not self.is_polling:
            return
        target = self.swarm_service.current_ip_port
        if target == ip_port:
            if event_name == "server_connected":
                session = self._active_session
                if session:
                    session.request_turbo()
                    self._poll_wake_event.set()
                self.log_safe(self.t("swarm_hint_received"), "#F97316")
            elif event_name == "swarm_stop_spam":
                session = self._active_session
                if not session or not session.launched_by_app:
                    self.log_safe(self.t("swarm_member_connected"), "#98A2B3")
                    self.stop_polling_safe()
            elif event_name == "swarm_connection_failed":
                self.log_safe(self.t("swarm_member_failed"), "#98A2B3")
            
    def _on_swarm_presence(self, count: int):
        now = time.monotonic()
        previous_count = getattr(self, "_last_swarm_presence_count", None)
        last_log_at = getattr(self, "_last_swarm_presence_log_at", 0.0)
        if count > 0 and (count != previous_count or now - last_log_at >= 60.0):
            self.dispatch_ui(self.log, self.t("swarm_presence_msg", count=count), "#2ECC71")
            self._last_swarm_presence_log_at = now
        self._last_swarm_presence_count = count
        
    def _load_hardware(self):
        try:
            hw_cpu = self.hardware_service.get_cpu_info()
            hw_ram = self.hardware_service.get_ram_info()
            hw_disk = self.hardware_service.get_disk_info()
            self.dispatch_ui(self.hardware_label.configure, text=f"CPU: {hw_cpu}\nRAM: {hw_ram}\nDisk: {hw_disk}")
        except Exception as e:
            from .core.logger import app_logger
            app_logger.warning(f"Failed to load hardware info: {type(e).__name__}")

    def run_benchmark(self):
        if not hasattr(self, 'bench_btn'):
            return
            
        import tkinter.messagebox as messagebox
        if self.process_monitor.is_rust_running():
            msg = self.t("bench_warn_running")
            if messagebox.askyesno(self.t("close_rust_title"), msg):
                self.process_monitor.force_kill_rust()
                self.log_safe(self.t("closed_rust"))
            else:
                self.log_safe(self.t("bench_aborted"))
                self.bench_btn.configure(state="normal")
                return
        else:
            pass # No early return, proceed to combined instruction
            
        combined_msg = f"{self.t('bench_confirm_msg')}\n\n{self.t('bench_warn_f5')}"
        if not messagebox.askokcancel(self.t("bench_instr_title"), combined_msg):
            self.log_safe(self.t("bench_aborted"))
            self.bench_btn.configure(state="normal")
            return
                
        if getattr(self, 'is_benchmarking', False):
            return
            
        from .core.history_store import history_store
        import tkinter.filedialog as filedialog
        
        # Determine rust path inside run_benchmark (main thread) so filedialog is safe
        rust_path = history_store.get_rust_path()
        if not rust_path or not os.path.exists(rust_path):
            self.log_safe(self.t("auto_detect_rust"))
            from .services import steam_service
            rust_path = steam_service.find_rust_install_path()
            if rust_path:
                self.log_safe(self.t("found_rust_at", path=rust_path))
                history_store.set_rust_path(rust_path)
            else:
                self.log_safe(self.t("cannot_detect_rust"))
                rust_path = filedialog.askdirectory(title=self.t("select_rust_folder_title"))
                if not rust_path:
                    self.log_safe(self.t("bench_aborted_no_path"))
                    self.bench_btn.configure(state="normal", text=self.t("run_test"), fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"], text_color=COLORS["canvas"])
                    return
                history_store.set_rust_path(rust_path)
        self.log_safe(self.t("rust_path_confirmed", path=rust_path), "#55C95D")

        self.is_benchmarking = True
        self._benchmark_stop_event.clear()
        with self._operation_lock:
            self._benchmark_operation += 1
            benchmark_operation = self._benchmark_operation
        self.bench_btn.configure(text=self.t("stop_bench"), fg_color="#E74C3C")
        self.bench_log.configure(state="normal")
        self.bench_log.delete("0.0", "end")
        self.bench_log.configure(state="disabled")
        
        threading.Thread(target=self.run_benchmark_logic, args=(rust_path, benchmark_operation), daemon=True, name="benchmark").start()

    def save_user_config(self):
        from .core.history_store import history_store
        rust_path = history_store.get_rust_path()
        if not rust_path or not os.path.exists(rust_path):
            import tkinter.messagebox as messagebox
            messagebox.showerror(self.t("error_title"), self.t("rust_path_not_found_err"))
            return
            
        import shutil
        import time
        import tkinter.messagebox as messagebox
        
        cfg_path = os.path.join(rust_path, "cfg")
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        user_cfg_path = os.path.join(rust_path, f"cfg_user_backup_{timestamp}")
        
        if not os.path.exists(cfg_path):
            messagebox.showerror(self.t("error_title"), self.t("no_cfg_folder_err"))
            return
            
        try:
            shutil.copytree(cfg_path, user_cfg_path)
            messagebox.showinfo(self.t("success_title"), self.t("user_config_saved", path=user_cfg_path))
        except Exception as e:
            messagebox.showerror(self.t("error_title"), self.t("user_config_save_failed", err=e))

    def run_benchmark_logic(self, rust_path, benchmark_operation):
        # Stop existing watchers to release log file locks
        if getattr(self, 'log_watcher', None):
            self.log_watcher.stop()
        if getattr(self, 'global_log_watcher', None):
            self.global_log_watcher.stop()
            
        try:
            self._run_benchmark_logic_internal(rust_path, benchmark_operation)
        finally:
            if not getattr(self, '_is_shutting_down', False):
                self.dispatch_ui(self._schedule_global_watcher_restart)

    def _run_benchmark_logic_internal(self, rust_path, benchmark_operation):
        from .core.history_store import history_store
        from .core.config import config

        def cancelled() -> bool:
            return (
                self._shutdown_event.is_set()
                or self._benchmark_stop_event.is_set()
                or benchmark_operation != self._benchmark_operation
            )
        
        # Wait until Rust is fully closed
        while self.process_monitor.is_rust_running() and not cancelled():
            self._benchmark_stop_event.wait(0.5)
        if cancelled():
            return
            
        if not os.path.exists(os.path.join(rust_path, "RustClient.exe")):
            self.log_bench(self.t("invalid_rust_folder"))
            history_store.set_rust_path("") # reset
            self.is_benchmarking = False
            self.dispatch_ui(self.bench_btn.configure, state="normal", text=self.t("run_test"), fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"], text_color=COLORS["canvas"], operation=("benchmark", benchmark_operation))
            return
            
        # Assets must exist before touching the game installation.
        base_dir = os.path.dirname(os.path.abspath(__file__))
        bm_source = os.path.abspath(os.path.join(base_dir, "..", "..", "BenchmarkFiles"))
        if not os.path.exists(bm_source):
            bm_source = os.path.abspath(os.path.join(base_dir, "..", "BenchmarkFiles"))
        if not (
            os.path.isdir(os.path.join(bm_source, "cfg"))
            and os.path.isfile(os.path.join(bm_source, "demos", "RustTweaker_bm.dem"))
        ):
            self.log_bench(self.t("bench_files_incomplete"))
            self.is_benchmarking = False
            self.dispatch_ui(self.bench_btn.configure, state="normal", text=self.t("run_test"), fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"], text_color=COLORS["canvas"], operation=("benchmark", benchmark_operation))
            return
        self.log_bench(self.t("backup_cfg_copy_bench"))
        
        cfg_path = os.path.join(rust_path, "cfg")
        cfg_backup_path = os.path.join(rust_path, f".rust_autoconnect_cfg_backup_{int(time.time())}_{benchmark_operation}")
        cfg_work_path = os.path.join(rust_path, f".rust_autoconnect_cfg_work_{int(time.time())}_{benchmark_operation}")
        rust_pids_before_start = self.process_monitor.get_rust_pids()
        benchmark_pid = None
        
        try:
            # Backup CFG
            if not os.path.exists(cfg_path):
                raise FileNotFoundError("Rust cfg directory was not found")
            shutil.copytree(cfg_path, cfg_backup_path)
            with open(os.path.join(cfg_backup_path, "operation.log"), "w", encoding="utf-8") as journal:
                journal.write("configuration backup created\n")
            if cancelled():
                self._restore_benchmark_cfg(cfg_path, cfg_backup_path, cfg_work_path)
                self.is_benchmarking = False
                self.dispatch_ui(self.bench_btn.configure, state="normal", text=self.t("run_test"), fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"], text_color=COLORS["canvas"], operation=("benchmark", benchmark_operation))
                return
                
            shutil.copytree(os.path.join(bm_source, "cfg"), cfg_path, dirs_exist_ok=True)
            
            target_demo = os.path.join(rust_path, "demos", "RustTweaker_bm.dem")
            if not os.path.exists(target_demo):
                shutil.copytree(os.path.join(bm_source, "demos"), os.path.join(rust_path, "demos"), dirs_exist_ok=True)
                
            # Append F5 bind to keys.cfg for manual start
            keys_cfg = os.path.join(cfg_path, "keys.cfg")
            with open(keys_cfg, "a") as f:
                f.write('\nbind f5 "demo.play RustTweaker_bm"\n')
        except Exception as e:
            self.log_bench(self.t("prep_bench_failed", err=e))
            if os.path.exists(cfg_backup_path):
                if not self._restore_benchmark_cfg(cfg_path, cfg_backup_path, cfg_work_path):
                    self.log_bench(self.t("restore_cfg_failed_prep"))
            self.is_benchmarking = False
            self.dispatch_ui(self.bench_btn.configure, state="normal", text=self.t("run_test"), fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"], text_color=COLORS["canvas"], operation=("benchmark", benchmark_operation))
            return
            
        self.log_bench(self.t("start_local_bench"))
        time.sleep(1.0)
        
        start_time = time.time()
        
        # The watcher starts at EOF, so existing diagnostic logs are preserved.
            
        spawn_reached = False
        menu_reached = False
        protocol_mismatch = False
        detected_client_protocol = None
        
        time_to_menu = 0.0
        demo_start_time = 0.0
        
        def bench_event(event):
            nonlocal spawn_reached, menu_reached, protocol_mismatch, detected_client_protocol
            nonlocal time_to_menu, demo_start_time
            # Log the game output to file only, keep UI clean
            from .core.logger import app_logger
            app_logger.debug(f"[GAME] {event}")
            
            if "Spawning" in event or "LocalPlayer" in event or "Client connected" in event:
                spawn_reached = True
            elif "[Bootstrap] DONE!" in event:
                time_to_menu = time.time() - start_time
                menu_reached = True
            elif "Demo is" in event or "Index created" in event:
                if demo_start_time == 0.0:
                    demo_start_time = time.time()
                    self.log_bench(self.t("f5_pressed_log"))
            elif "Protocol mismatch" in event or "Demo protocol" in event:
                protocol_mismatch = True
                # Parse: "Demo protocol 2530 does not match client protocol 2544"
                import re
                match = re.search(r'client protocol (\d+)', event)
                if match:
                    detected_client_protocol = match.group(1)

        from .services.log_watcher import LogWatcher        
        bench_watcher = LogWatcher(
            on_disconnect=lambda reason: self.log_bench(f"Disconnected: {reason}"),
            on_error=lambda err: self.log_bench(f"Error: {err}"),
            on_event=bench_event,
            seek_end=True,
            target_log_path=None
        )
        
        try:
            bench_watcher.start(loop=self.async_loop)
            url = f"steam://run/{config.STEAM_APP_ID}//-windowed -popupwindow"
            if os.name == 'nt':
                os.startfile(url)
            else:
                webbrowser.open(url)
            has_started = False
            menu_msg_shown = False
            while not spawn_reached and self.is_benchmarking and not cancelled():
                self._benchmark_stop_event.wait(0.2)
                is_running = self.process_monitor.is_rust_running()
                
                if is_running:
                    if not has_started:
                        new_pids = self.process_monitor.get_rust_pids() - rust_pids_before_start
                        if len(new_pids) == 1:
                            benchmark_pid = new_pids.pop()
                        self.log_bench(self.t("rust_detected_wait_map"))
                        has_started = True
                        
                    if menu_reached and not menu_msg_shown:
                        self.log_bench(self.t("game_ready_menu", sec=round(time_to_menu, 1)))
                        self.log_bench(self.t("f5_prompt_log"))
                        menu_msg_shown = True
                    
                    elapsed = int(time.time() - start_time)
                    if elapsed > 0 and elapsed % 5 == 0 and elapsed != getattr(self, '_last_wait_log', 0):
                        self.log_bench(self.t("waiting_elapsed", sec=elapsed))
                        self._last_wait_log = elapsed
                        
                if has_started and not is_running:
                    self.log_bench(self.t("rust_closed_bench_stopped"))
                    self.is_benchmarking = False
                    break
                if protocol_mismatch and detected_client_protocol:
                    self.log_bench(self.t("protocol_mismatch_patching", proto=detected_client_protocol))
                    self.is_benchmarking = False
                    break
                if time.time() - start_time > 600:
                    self.log_bench(self.t("bench_timeout"))
                    self.is_benchmarking = False
                    break
        finally:
            bench_watcher.stop()
            
            can_restore = True
            restore_deferred = False
            if benchmark_pid is not None and benchmark_pid in self.process_monitor.get_rust_pids():
                self.log_bench(self.t("closing_rust_for_bench"))
                self.process_monitor.force_kill_pid(benchmark_pid)
                while benchmark_pid in self.process_monitor.get_rust_pids() and not self._shutdown_event.is_set():
                    self._benchmark_stop_event.wait(0.2)
            elif self.process_monitor.is_rust_running():
                self.log_bench(self.t("rust_ownership_unclear"))
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
                    self.log_bench(self.t("restoring_cfg_backup"))
                    if not self._restore_benchmark_cfg(cfg_path, cfg_backup_path, cfg_work_path):
                        raise OSError("configuration restore did not complete")
            except (OSError, shutil.Error) as e:
                self.log_bench(self.t("restore_cfg_failed", err=e))
            
            self.is_benchmarking = False
            if restore_deferred:
                self.dispatch_ui(
                    self.bench_btn.configure,
                    state="disabled",
                    text=self.t("restore_pending"),
                    fg_color="#FADA5E",
                    text_color="black",
                    operation=("benchmark", benchmark_operation),
                )
                return
            
            if protocol_mismatch and detected_client_protocol:
                self.log_bench(self.t("demo_proto_mismatch_no_mod"))
            elif spawn_reached and menu_reached:
                demo_load_time = time.time() - demo_start_time if demo_start_time > 0.0 else 0.0
                total_time = time_to_menu + demo_load_time
                
                # Validation: Prevent spoofing by requiring minimum realistic times
                if time_to_menu < 2.0 or demo_load_time < 2.0:
                    self.log_bench(self.t("bench_rejected_fast"))
                    self.is_benchmarking = False
                    self.dispatch_ui(self.bench_btn.configure, state="normal", fg_color="#E74C3C", text=self.t("rejected"), operation=("benchmark", benchmark_operation))
                    return
                    
                self.log_bench(self.t("score_time_to_menu", sec=round(time_to_menu, 1)))
                self.log_bench(self.t("score_map_load", sec=round(demo_load_time, 1)))
                self.log_bench(self.t("score_total", sec=round(total_time, 1)))
                
                self.log_bench(self.t("bench_complete_game_closed"))
                
                if total_time < 90:
                    self.dispatch_ui(self.bench_btn.configure, state="normal", fg_color="#50C878", text=self.t("bench_excellent"), operation=("benchmark", benchmark_operation))
                elif total_time < 180:
                    self.dispatch_ui(self.bench_btn.configure, state="normal", fg_color="#FADA5E", text=self.t("bench_good"), text_color="black", operation=("benchmark", benchmark_operation))
                else:
                    self.dispatch_ui(self.bench_btn.configure, state="normal", fg_color="#E74C3C", text=self.t("bench_slow"), operation=("benchmark", benchmark_operation))
                
                self._record_benchmark_result(rust_path, time_to_menu, demo_load_time, benchmark_operation)
            else:
                self.dispatch_ui(self.bench_btn.configure, state="normal", fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"], text_color=COLORS["canvas"], text=self.t("run_test"), operation=("benchmark", benchmark_operation))

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
        while self.process_monitor.is_rust_running() and not self._shutdown_event.is_set():
            self._shutdown_event.wait(0.5)
            
        with self._operation_lock:
            pending = self.__dict__.get("_pending_benchmark_restore")
            if pending is not None:
                self._pending_benchmark_restore = None

        # Always restore CFG even if shutting down
        if self._restore_benchmark_cfg(cfg_path, backup_path, work_path):
            if not self._shutdown_event.is_set():
                self.log_bench(self.t("rust_closed_restored"))
                self.dispatch_ui(
                    self.bench_btn.configure,
                    state="normal",
                text=self.t("run_test"),
                fg_color="#E67E22",
                text_color="#101214",
                operation=("benchmark", benchmark_operation),
            )
        else:
            self.log_bench(self.t("rust_closed_restore_failed"))

    def _restore_pending_benchmark_on_shutdown(self) -> None:
        with self._operation_lock:
            pending = self.__dict__.get("_pending_benchmark_restore")
            if not pending:
                return
            self._pending_benchmark_restore = None
        cfg_path, backup_path, work_path, _operation = pending
        try:
            if self.process_monitor.is_rust_running():
                self.process_monitor.force_kill_rust()
            restored = self._restore_benchmark_cfg(cfg_path, backup_path, work_path)
        except (OSError, shutil.Error) as error:
            app_logger.error(f"Could not restore pending benchmark configuration during shutdown: {type(error).__name__}")
            return
        if restored:
            self._pending_benchmark_restore = None
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
                history_store.get_installation_id(), cpu, storage, storage_bus,
                time_to_menu, demo_load_time, BENCHMARK_VERSION,
            )
            if not history_store.add_benchmark_run(run):
                self.log_bench(self.t("bench_result_not_queued"))
                return
        except (OSError, ValueError) as error:
            self.log_bench(self.t("bench_result_not_saved", err=type(error).__name__))
            return

        self.log_bench(self.t("result_queued_for", cpu=run['cpu'], storage=run['storage']))
        self.dispatch_ui(self.update_benchmark_summary, run, operation=("benchmark", benchmark_operation))
        self.log_bench(self.t("sending_bench_result"))
        threading.Thread(
            target=self._submit_benchmark_run_bg,
            args=(run,),
            daemon=True,
            name="benchmark-upload",
        ).start()

    def _auto_patch_demo(self, demo_path: str, new_protocol: int):
        # Rust demo header: 8 bytes id, 4 bytes protocol, 4 bytes save version
        try:
            with open(demo_path, "rb+") as f:
                f.seek(8) # Skip identifier
                f.write(new_protocol.to_bytes(4, byteorder='little'))
        except Exception as e:
            self.log_bench(self.t("patch_demo_failed", err=e))

    def _submit_benchmark_run_bg(self, run: dict) -> None:
        try:
            from .services.leaderboard_service import leaderboard_service
            success = leaderboard_service.submit_run(run)
            if success:
                if history_store.mark_benchmark_run_synced(run["id"]):
                    self.log_bench(self.t("result_submitted"))
                else:
                    self.log_bench(self.t("result_submitted_mark_failed"))
            else:
                self.log_bench(self.t("leaderboard_unavailable_pending"))
        except Exception as e:
            from .core.logger import app_logger
            self.log_bench(self.t("bench_result_not_saved", err=type(e).__name__))
            app_logger.error(f"Failed to submit benchmark run: {type(e).__name__}")

    def _retry_pending_benchmark_runs(self) -> None:
        """Retry retained benchmark uploads without exposing a user-facing history."""
        for run in history_store.get_benchmark_runs():
            if self._shutdown_event.is_set():
                return
            if run.get("sync_state") == "pending":
                self._submit_benchmark_run_bg(run)
                if self._shutdown_event.wait(1.0):
                    break

    def log_bench(self, msg: str):
        self.dispatch_ui(self._log_bench_ui, msg)
        
    def _log_bench_ui(self, msg: str):
        if not hasattr(self, 'bench_log'):
            return
        import time
        from .core.logger import app_logger
        app_logger.info(f"[BENCHMARK] {msg}")
        ts = time.strftime("[%H:%M:%S]")
        self.bench_log.configure(state="normal")
        self.bench_log.insert("end", f"{ts} {msg}\n")
        self.bench_log.see("end")
        self.bench_log.configure(state="disabled")

    def _on_log_error(self, err: str):
        self.log_safe(f"[x] Log Error: {err}")

    @staticmethod
    def _log_confirms_current_connection(event: str, target: str, session: Optional[ConnectionSession]) -> bool:
        """Accept only a post-launch client connection event for this session.

        Rust's generic ``Spawning`` line merely means a local scene is loading.
        If the log provides an endpoint, it must match the requested or
        canonical target; older log formats without an endpoint remain a
        conservative local confirmation, not a proof of remote identity.
        """
        if "Client connected" not in event:
            return False
        match = re.search(r"Client connected to\s+([A-Za-z0-9.-]+:\d{1,5})", event, re.IGNORECASE)
        if not match:
            return True
        observed = match.group(1).lower()
        expected = {target.lower()}
        if session and session.canonical_endpoint:
            expected.add(session.canonical_endpoint.lower())
        return observed in expected

    def start_log_monitor(
        self,
        target_str: str,
        *,
        session: Optional[ConnectionSession] = None,
        operation_id: Optional[int] = None,
    ):
        self.log_safe(self.t("log_mon"))
        if self.log_watcher:
            self.log_watcher.stop()
            self.log_watcher = None

        self.connection_start_time = time.time()
        self.is_connected = False
        
        def handle_event(event):
            from .core.logger import app_logger
            app_logger.info(f"[*] Game log: {event}")
            # Do NOT spam the UI with every game log line
            if watcher is not self.log_watcher or (session is not None and self._active_session is not session):
                return
            # Benchmarking established this as Rust's local menu-ready marker.
            # It is informative only: the selected-server confirmation still
            # requires the later Client connected event below.
            if session is not None and not session.menu_ready and "[Bootstrap] DONE!" in event:
                session.menu_ready = True
                self.log_safe(self.t("rust_menu_ready_waiting"), "#98A2B3")
            if not getattr(self, 'is_connected', False) and self._log_confirms_current_connection(event, target_str, session):
                self.is_connected = True
                if session:
                    session.phase = ConnectionPhase.CONNECTED
                    if operation_id is not None:
                        self.dispatch_ui(self.set_connection_phase, session.phase.value, operation=("poll", operation_id))
                conn_time = round(time.time() - getattr(self, 'connection_start_time', time.time()), 1)
                self.dispatch_ui(self.set_connection_state, "Connected", target_str)
                self.log_safe(self.t("server_conn_time", sec=conn_time))
                self._update_server_profile(target_str, state="connected")
                threading.Thread(
                    target=telegram_service.notify,
                    args=("connected", target_str),
                    daemon=True,
                    name="telegram-connected",
                ).start()
                if getattr(self, 'is_polling', False):
                    canonical = session.canonical_endpoint if session and session.canonical_endpoint else target_str
                    threading.Thread(target=self.swarm_service.broadcast_success, args=(canonical,), daemon=True).start()
                    threading.Thread(target=self.server_intelligence.report_available, args=(canonical,), daemon=True).start()
                    threading.Thread(target=self.swarm_service.broadcast_stop_spam, args=(canonical,), daemon=True).start()
                    # Stop probing but keep this watcher alive: it is the safe
                    # local signal for a later armed auto-reconnect.
                    self.is_polling = False
                    self._poll_stop_event.set()
                    self._poll_wake_event.set()
                    self.dispatch_ui(self.connect_btn.configure, text="CONNECT", fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"], text_color=COLORS["canvas"])
                    self.dispatch_ui(self.ip_entry.configure, state="normal")

        import uuid
        queue_session_id = uuid.uuid4().hex
        queue_levels = (90, 60, 30, 5)
        sent_queue_levels: set[int] = set()

        def handle_queue(position: int):
            eligible = [level for level in queue_levels if position <= level and level not in sent_queue_levels]
            if eligible:
                level = min(eligible)
                sent_queue_levels.add(level)
                threading.Thread(
                    target=telegram_service.notify_queue,
                    args=(position, target_str),
                    kwargs={"level": level, "queue_session_id": queue_session_id},
                    daemon=True,
                    name="telegram-queue",
                ).start()

        watcher = None
        def handle_disconnect(reason):
            self._on_log_disconnect(target_str, watcher, reason, session=session)

        watcher = LogWatcher(
            on_disconnect=handle_disconnect,
            on_error=self._on_log_error,
            on_event=handle_event,
            on_queue_update=handle_queue,
        )
        self.log_watcher = watcher
        watcher.start(loop=self.async_loop)

        def confirmation_watchdog() -> None:
            # Queue admission may legitimately take longer, but neither path
            # is allowed to silently become a confirmed connection.
            timeout = 900 if session and session.queue_requested else 120
            if self._shutdown_event.wait(timeout):
                return
            if (
                watcher is self.log_watcher
                and session is self._active_session
                and not self.__dict__.get("is_connected", False)
                and session is not None
                and session.phase in {ConnectionPhase.QUEUED, ConnectionPhase.AWAITING_LOG_CONFIRMATION}
            ):
                self.log_safe(self.t("connection_log_timeout", sec=timeout), "#F97316")
                self._update_server_profile(target_str, state="unconfirmed", reason="Rust log confirmation timed out")

        threading.Thread(
            target=confirmation_watchdog, daemon=True, name="connection-log-watchdog",
        ).start()

    def _on_log_disconnect(self, target_str: str, source_watcher, reason: str, *, session: Optional[ConnectionSession] = None):
        if self.log_watcher is not source_watcher:
            return

        session = session or self._active_session
        if session is not self._active_session:
            return
        armed = self.history_store.get_armed_server()
        is_armed_target = bool(session and session.launched_by_app and armed in {target_str, session.canonical_endpoint})
        self._update_server_profile(target_str, state="disconnected", reason=reason)
        self.log_safe(self.t("log_err") + f" Reason: {reason}")
        threading.Thread(target=telegram_service.notify, args=("disconnect", target_str, {"reason": reason[:160]}), daemon=True, name="telegram-disconnect").start()

        if not is_armed_target:
            self.log_safe(self.t("auto_reconnect_skipped_disarmed"), "#98A2B3")
            return

        if not self.__dict__.get('is_connected', False):
            canonical = session.canonical_endpoint or target_str
            threading.Thread(target=self.swarm_service.broadcast_connection_failed, args=(canonical,), daemon=True).start()

        def reconnect_after_cooldown():
            if self._shutdown_event.wait(2.0) or self.log_watcher is not source_watcher or self._active_session is not session:
                return
            if self._active_session:
                self._active_session.phase = ConnectionPhase.COOLDOWN
            self.log_safe(self.t("auto_reconnect_monitoring", target=target_str), "#F97316")
            telegram_service.notify("reconnect", target_str)
            self.start_process_force(target_str, recovery_session=session)

        threading.Thread(target=reconnect_after_cooldown, daemon=True, name="auto-reconnect-cooldown").start()

    def start_process_force(self, target: str, *, recovery_session: Optional[ConnectionSession] = None):
        if not _is_valid_endpoint(target):
            self.log_safe(self.t("auto_reconnect_skipped_invalid"), "#DE5148")
            return
        self.stop_polling()
        with self._state_lock:
            if self._is_reconnecting:
                return
            self._is_reconnecting = True
            self._is_polling = True
        self.dispatch_ui(self.ip_entry.configure, state="disabled")
        self.dispatch_ui(
            self.connect_btn.configure,
            text=self.t("stop"),
            fg_color="#C74E4E",
            hover_color="#9E3E3E",
            text_color="#F2F4F7",
        )
        self.dispatch_ui(self.set_connection_state, "Monitoring", target)
        self._update_server_profile(target, state="reconnecting")
        self._poll_stop_event.clear()
        self._poll_wake_event.clear()
        operation_id = self._next_poll_operation()
        self._active_session = ConnectionSession(requested_endpoint=target)
        if recovery_session is not None:
            # Preserve a confirmed restart's bounded Turbo/Watch state across
            # the new polling operation; never carry over a prior launch flag.
            self._active_session.canonical_endpoint = recovery_session.canonical_endpoint
            self._active_session.turbo_until = recovery_session.turbo_until
            self._active_session.watch_until = recovery_session.watch_until
            self._active_session.offline_turbo_used = recovery_session.offline_turbo_used
            self._active_session.down_observed = recovery_session.down_observed
        self._last_smart_phase = None
        self._last_probe_outcome = ""
        threading.Thread(
            target=self.run_logic,
            args=(target, operation_id),
            daemon=True,
            name="forced-server-poll",
        ).start()

    def launch_game(
        self, target: str, *, session: Optional[ConnectionSession] = None,
        operation_id: Optional[int] = None, queue_mode: bool = False,
    ):
        if not _is_valid_endpoint(target):
            self.log_safe(self.t("launch_skipped_invalid"), "#DE5148")
            return
        session = session or self._active_session
        if operation_id is not None and (session is None or not self._is_current_session(operation_id, session)):
            return
        self.log_safe(self.t("launch", url=target))
        try:
            url = steam_service.build_connect_url(target, config.STEAM_APP_ID)
            if os.name == 'nt':
                os.startfile(url)
            else:
                import webbrowser
                webbrowser.open(url)
            self.log_safe(self.t("launch_ok"))
            if session:
                session.launched_by_app = True
                session.queue_requested = queue_mode
                session.phase = ConnectionPhase.QUEUED if queue_mode else ConnectionPhase.AWAITING_LOG_CONFIRMATION
                session.reset_offline_turbo()
                if operation_id is not None:
                    self.dispatch_ui(self.set_connection_phase, session.phase.value, operation=("poll", operation_id))
            self.dispatch_ui(self.set_connection_state, "Queueing" if queue_mode else "Launching", target)
            self._update_server_profile(target, state="queue" if queue_mode else "launching")
            self.start_log_monitor(target, session=session, operation_id=operation_id)
        except Exception as e:
            self.dispatch_ui(self.set_connection_state, "Launch failed")
            self.log_safe(self.t("launch_err", err=str(e)))
            self.stop_polling_safe()

    def save_only(self):
        target = self.get_target_ip()
        if not target or ":" not in target:
            self.log_safe(self.t("err_format"))
            return
        threading.Thread(target=self.run_save_logic, args=(target,), daemon=True).start()

    def run_save_logic(self, target: str):
        try:
            host, port_str = target.split(":", 1)
            port = int(port_str)
        except ValueError:
            self.log_safe(self.t("err_port"))
            return

        real_ip = host
        try:
            real_ip = socket.gethostbyname(host)
            self.dispatch_ui(self.update_entry, f"{real_ip}:{port}")
        except socket.gaierror:
            pass

        try:
            server_name = host
            is_alive, name, max_players, _ = self.a2s_client.check_server_alive(real_ip, port)
            if is_alive and name:
                server_name = name

            target_str = f"{real_ip}:{port}"
            self.dispatch_ui(self.history_store.add_to_history, target_str, server_name)
            self.dispatch_ui(self.refresh_history_ui)
            self.log_safe(self.t("save_ip"))
        except Exception as e:
            from .core.logger import app_logger
            app_logger.warning(f"Failed to save server: {type(e).__name__}")

    def save_favorite_dialog(self):
        target = self.get_target_ip()
        if not target:
            return

        dialog = ctk.CTkInputDialog(text=self.t("save_favorite_prompt"), title=self.t("save_favorite_title"))
        name = dialog.get_input()
        if name:
            self.history_store.toggle_favorite(target, name)
            self.update_favorites_combobox()
            self.set_address(f"{name} ({target})")
            self.log_safe(self.t("saved_to_favorites", name=name))

    def select_history(self, ip_port: str):
        if self.is_polling:
            return
        self.set_address(ip_port)

    def check_rust_status_loop(self):
        self.is_rust_was_running = False
        last_status = None
        while not self._shutdown_event.is_set():
            is_running = self.process_monitor.is_rust_running()
            if is_running:
                self.is_rust_was_running = True
                if last_status is not True:
                    self.dispatch_ui(self.set_rust_status, True)
                    last_status = True
            else:
                if last_status is not False:
                    self.dispatch_ui(self.set_rust_status, False)
                    last_status = False
                if getattr(self, 'is_rust_was_running', False):
                    self.is_rust_was_running = False
                    self.dispatch_ui(self._handle_unexpected_rust_exit)
            
            if self._shutdown_event.wait(2.0):
                break

    def _handle_unexpected_rust_exit(self) -> None:
        session = self._active_session
        armed = self.history_store.get_armed_server()
        if not session or not session.launched_by_app:
            return
        if armed not in {session.requested_endpoint, session.canonical_endpoint}:
            return
        self.log_safe(self.t("rust_closed_unexpectedly"), "#F97316")
        session.offline_turbo_used = False
        session.observe_server_down()
        self.start_process_force(session.requested_endpoint, recovery_session=session)

    def _check_rust_update_once(self) -> float:
        """Check Rust's Steam build once and return the next safe check delay."""
        info = steam_service.fetch_latest_build_info()
        if info.server_date:
            was_synced = self.network_clock.is_synced
            self.network_clock.observe_http_date(info.server_date)
            offset = self.network_clock.system_offset_seconds
            if offset is not None and abs(offset) > 120 and self._update_status_logged != "clock-offset":
                self.log_safe("Windows clock differs from network time by more than two minutes.", "#F97316")
                self._update_status_logged = "clock-offset"
            elif not was_synced:
                self.log_safe("Network time synchronized.", "#55C95D")

        local_buildid = steam_service.get_local_buildid()
        mismatch = bool(local_buildid and info.buildid and str(local_buildid) != str(info.buildid))
        if mismatch:
            self._update_required = True
            self._update_ready_event.clear()
            if self._update_status_logged != "pending":
                self.log_safe(self.t("rust_game_update_avail"), "#F97316")
                self._update_status_logged = "pending"
            if not self.process_monitor.is_rust_running() and not self._update_steam_opened:
                self._update_steam_opened = steam_service.open_steam_downloads()
                if self._update_steam_opened:
                    self.log_safe("Opened Steam Downloads; waiting for Rust to update.", "#98A2B3")
        elif info.buildid and local_buildid:
            if self._update_required:
                self.log_safe("Rust update is ready.", "#55C95D")
            self._update_required = False
            self._update_steam_opened = False
            self._update_status_logged = "ready"
            self._update_ready_event.set()
        return steam_service.force_wipe_poll_interval(self.network_clock.now())

    def check_rust_update_loop(self):
        while not self._shutdown_event.is_set():
            if not self.history_store.get_auto_update():
                if self._shutdown_event.wait(60.0):
                    break
                continue

            interval = self._check_rust_update_once()
            self._update_check_wake_event.clear()
            deadline = time.monotonic() + interval
            while not self._shutdown_event.is_set() and time.monotonic() < deadline:
                if self._update_check_wake_event.wait(min(0.5, max(0.0, deadline - time.monotonic()))):
                    break

    def check_application_version(self):
        from .services.release_service import LOCAL_VERSION, is_newer_version, release_service

        latest_version = release_service.fetch_latest_version()
        if latest_version is None:
            status, color = "Offline", "#98A2B3"
        elif is_newer_version(latest_version, LOCAL_VERSION):
            status, color = f"Update: {latest_version}", "#F97316"
        else:
            status, color = "Latest", "#2ECC71"
        self.dispatch_ui(self.set_version_status, LOCAL_VERSION, status, color)

    def shutdown(self):
        """
        BUG-04 Fix: Graceful shutdown stopping log watcher and polling loops.
        """
        self._restore_pending_benchmark_on_shutdown()
        self.is_polling = False
        self._is_shutting_down = True
        self._shutdown_event.set()
        self._benchmark_stop_event.set()
        self._next_poll_operation()

        if self._global_watcher_after_id is not None:
            self.after_cancel(self._global_watcher_after_id)
            self._global_watcher_after_id = None
        if getattr(self, "_ui_queue_after_id", None) is not None:
            self.after_cancel(self._ui_queue_after_id)
            self._ui_queue_after_id = None
        
        if self.log_watcher:
            self.log_watcher.stop()
            self.log_watcher = None
            
        if hasattr(self, 'global_log_watcher') and self.global_log_watcher:
            self.global_log_watcher.stop()
            self.global_log_watcher = None

        swarm_service = self.__dict__.get("swarm_service")
        if swarm_service is not None:
            swarm_service.on_swarm_event = None
            swarm_service.on_presence_update = None
            swarm_service.on_status = None
            swarm_service.stop()
            
        super().shutdown()


