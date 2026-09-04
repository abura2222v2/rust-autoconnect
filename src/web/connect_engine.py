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
import re
import socket
import threading
import traceback
import time
from datetime import datetime, timezone
from typing import Optional

from ..core.a2s_client import a2s_client
from ..core.config import config
from ..core.history_store import history_store
from ..core.i18n import i18n
from ..core.logger import app_logger
from ..core.network_clock import NetworkClock
from ..core.smart_monitor import ConnectionPhase, ConnectionSession, PollingPolicy
from ..services import steam_service
from ..services.log_watcher import LogWatcher
from ..services.process_monitor import process_monitor
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


_WORLD_LOADING_RE = re.compile(r"\[[\d.]+s\]\s*(?:Spawning World|Processing World)", re.IGNORECASE)

# Automatic retry limits. A refusal that repeats is a real refusal (outdated
# client, ban, password) - retrying it forever only spams Steam and hides the
# reason from the player, so we stop and say so.
_MAX_RECONNECT_ATTEMPTS = 5
# The first retry is deliberately quick - the player wants their slot back,
# and during a wipe rush every second costs queue position. It is not zero
# because the client is still walking back to the main menu at that moment.
_RECONNECT_BACKOFF_SECONDS = (1.5, 5.0, 10.0, 20.0, 30.0)

# How long a launched-but-unconfirmed session stays under observation. Rust
# can legitimately take 90+ seconds to load, so this is generous - but not
# infinite, or a session whose confirmation never arrives would keep probing
# and keep claiming "Launching" for the rest of the day.
_OBSERVATION_LIMIT_SECONDS = 600.0
# Rust's own queue can legitimately take a very long time.
_QUEUE_OBSERVATION_LIMIT_SECONDS = 3600.0

# Redirecting an already-open Rust client is not as reliable as launching a
# closed one (measured live, 2026-09-04): the same steam://+connect command
# sometimes lands instantly and sometimes does nothing at all - no new log
# line, no visible attempt, as if the client silently dropped it (possibly a
# client-side command cooldown). A fresh launch does not have this problem,
# so only the "already running" redirect case gets a bounded number of
# resends; spaced apart, not spammed, in case that guess about a cooldown is
# right and a rapid resend would just be ignored too.
_REDIRECT_RESEND_INTERVAL_SECONDS = 20.0
_MAX_REDIRECT_RESENDS = 2


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
    if not (session and session.target_connection_attempt_seen):
        return False
    if "Client connected" in event:
        return True
    if re.search(r"\bClient\s*:\s*OnClientConnected\b", event, re.IGNORECASE):
        return True
    # Verified against a real Rust client (2026-09-03): "Client connected"
    # and "OnClientConnected" are never actually printed on a real, fully
    # successful join. The real, reproducible signal after a matched
    # "Connecting:" line is the world-loading sequence starting ("Spawning
    # World" then "Processing World") with no disconnect in between.
    return bool(_WORLD_LOADING_RE.search(event))


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
        # A server that keeps refusing us (outdated client, ban, password)
        # would otherwise loop forever: disconnect -> reconnect -> refused.
        # Counted per target and reset by a confirmed join or a manual click.
        self._reconnect_attempts = 0
        self._reconnect_target = ""
        self._reconnect_timer: Optional[threading.Timer] = None

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
        if explicit and self._reconnect_timer is not None:
            # Otherwise a retry scheduled a moment ago still fires after the
            # person pressed Stop, and the game gets yanked to a server they
            # just told us to leave alone.
            self._reconnect_timer.cancel()
            self._reconnect_timer = None
        if explicit and self._active_session:
            self._active_session.cancel()
            self._active_session = None
        if self.log_watcher:
            self.log_watcher.stop()
            self.log_watcher = None
        swarm_service.leave_room()

    def handle_unexpected_rust_exit(self) -> None:
        """Rust's process disappeared without a log-detected disconnect line
        (a hard crash or an OS-level kill). The log watcher will never fire
        on its own here, so this is the only way to notice and recover."""
        session = self._active_session
        if not session or not session.launched_by_app:
            return
        armed = history_store.get_armed_server()
        target = session.canonical_endpoint or session.requested_endpoint
        if not armed or armed not in (session.requested_endpoint, session.canonical_endpoint):
            return
        self.bridge.log(i18n.t("log_rust_closed_unexpectedly"), level="warning")
        session.offline_turbo_used = False
        self.stop(explicit=True)
        self.bridge._session_status = "idle"
        self.bridge.broadcast("state_updated", self.bridge.get_state())
        # Same bounded retry as a log-detected disconnect: a client that
        # crashes every time it touches this server must not relaunch the
        # game forever.
        self._schedule_reconnect(target)

    def connect(self, target: str, *, queue_on_full: bool = False, reset_attempts: bool = True) -> None:
        """Start (or restart) a smart connect session toward `target` (ip:port).

        `reset_attempts` is False only for our own automatic retry, so the
        retry budget keeps counting down; any request that came from the
        person using the app starts that budget over.
        """
        self.stop(explicit=True)
        if reset_attempts or target != self._reconnect_target:
            self._reconnect_attempts = 0
            self._reconnect_target = target
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

            last_probe_outcome = ""
            while self._is_current(operation_id, session):
                now = self.network_clock.now()

                # Steam is opened once for a closed Rust, below. Rust may take
                # tens of seconds to load, while the server can still restart
                # or disappear in the meantime. Keep lightly observing A2S -
                # never re-launching a closed client twice - until this
                # session's own log watcher confirms the connection. The one
                # exception is a bounded resend of the same redirect command
                # when it targeted an already-open client (see
                # _REDIRECT_RESEND_INTERVAL_SECONDS for why that case alone
                # needs it).
                if session.launched_by_app:
                    # Observation is not endless. If confirmation never
                    # arrives (a log format change, a join that quietly
                    # failed), keep saying "Launching" and probing every few
                    # seconds forever would be a lie dressed as work.
                    if self._observation_expired(session):
                        self.bridge.log(
                            i18n.t("log_confirm_timeout_stop", target=canonical_target),
                            level="warning",
                        )
                        self.stop(explicit=False)
                        self.bridge._session_status = "idle"
                        self.bridge.broadcast("state_updated", self.bridge.get_state())
                        return
                    if (
                        session.relaunch_was_already_running
                        and session.redirect_resend_count < _MAX_REDIRECT_RESENDS
                        and session.last_launch_sent_at is not None
                        and (time.monotonic() - session.last_launch_sent_at) >= _REDIRECT_RESEND_INTERVAL_SECONDS
                    ):
                        steam_service.dispatch_launch(canonical_target, config.STEAM_APP_ID)
                        session.last_launch_sent_at = time.monotonic()
                        session.redirect_resend_count += 1
                        self.bridge.log(
                            i18n.t(
                                "log_redirect_resend",
                                attempt=session.redirect_resend_count,
                                attempts=_MAX_REDIRECT_RESENDS,
                            ),
                            level="info",
                        )
                    obs_status = a2s_client.check_server_status(real_ip, port, session.stop_event)
                    if not self._is_current(operation_id, session):
                        return
                    rust_running = process_monitor.is_rust_running()
                    outcome = ("rust_open_" if rust_running else "launch_") + ("online" if obs_status.alive else "offline")
                    if outcome != last_probe_outcome:
                        msg_key = (
                            ("rust_open_server_online" if rust_running else "launch_server_online")
                            if obs_status.alive
                            else ("rust_open_server_offline" if rust_running else "launch_server_offline")
                        )
                        self.bridge.log(i18n.t(msg_key), level="info" if obs_status.alive else "warning")
                        last_probe_outcome = outcome
                    history_store.update_server_profile(
                        target,
                        state="queue" if session.queue_requested else ("launching" if obs_status.alive else "offline"),
                        checked_at=int(time.time()),
                    )
                    if session.stop_event.wait(PollingPolicy().launch_confirmation_probe_seconds):
                        return
                    continue

                provider_requested = session.provider_last_requested_at
                if provider_requested is None or (now - provider_requested).total_seconds() >= 55:
                    self._refresh_provider_hint(operation_id, session, canonical_target)

                if session.begin_wipe_restart_hold(now):
                    self.bridge.log(i18n.t("log_wipe_restart_wait_loop"), level="warning")

                status = a2s_client.check_server_status(real_ip, port, session.stop_event)
                if not self._is_current(operation_id, session):
                    return

                # Near a scheduled wipe a live response can still be the old
                # map. Do not launch Rust until a restart was observed: the
                # normal two A2S misses after a known-live server, or the
                # planned wipe time passing while the server is unavailable.
                if session.waiting_for_wipe_restart:
                    restart_detected = False
                    if status.alive:
                        session.observe_query_result(True, now)
                        if not session.wipe_wait_announced_online:
                            self.bridge.log(i18n.t("wipe_old_server_online"), level="info")
                            session.wipe_wait_announced_online = True
                    else:
                        restart_detected = session.observe_query_result(False, now)
                        restart_detected = restart_detected or session.wipe_time_has_arrived(now)
                    if restart_detected and session.confirm_wipe_restart():
                        self.bridge.log(i18n.t("wipe_restart_detected"), level="warning")
                    else:
                        wait = session.interval_seconds(now)
                        self._poll_wake_event.wait(wait)
                        self._poll_wake_event.clear()
                        continue

                # A single UDP reply can be stale or a fluke. Re-check once
                # before launching so a momentary flicker doesn't trigger it.
                if status.alive and status.has_join_capacity:
                    if session.stop_event.wait(PollingPolicy().confirmation_gap_seconds):
                        return
                    confirmed = a2s_client.check_server_status(real_ip, port, session.stop_event)
                    if not self._is_current(operation_id, session):
                        return
                    if confirmed.alive and confirmed.has_join_capacity:
                        self._dispatch_launch(operation_id, session, canonical_target, queue_mode=False)
                        continue
                    status = confirmed

                # A missing/zero max_players is not proof of a free slot - it
                # can be a still-starting or otherwise unavailable server
                # (e.g. right after a wipe restart). Only queue after two
                # fresh A2S replies agree this is a real, full server.
                if status.alive and status.max_players > 0 and not status.has_join_capacity and session.queue_on_full:
                    if session.stop_event.wait(PollingPolicy().confirmation_gap_seconds):
                        return
                    confirmed = a2s_client.check_server_status(real_ip, port, session.stop_event)
                    if not self._is_current(operation_id, session):
                        return
                    if confirmed.alive and confirmed.max_players > 0 and not confirmed.has_join_capacity:
                        self._dispatch_launch(operation_id, session, canonical_target, queue_mode=True)
                        continue
                    status = confirmed
                    if status.alive and status.has_join_capacity:
                        continue

                if not (status.alive and status.has_join_capacity):
                    if session.observe_query_result(status.alive, now):
                        self.bridge.log(i18n.t("log_server_stopped_responding"), level="warning")
                    if status.alive:
                        self.bridge.log(
                            i18n.t("log_server_full", player_count=status.player_count, max_players=status.max_players),
                            level="warning",
                        )
                        wait = session.full_server_retry_seconds(now)
                    else:
                        wait = session.query_retry_seconds(now)
                else:
                    wait = session.interval_seconds(now)

                self._poll_wake_event.wait(wait)
                self._poll_wake_event.clear()
        except Exception as error:
            # Without this the thread dies silently: `finally` clears
            # is_polling, but the UI keeps showing "Connecting" forever for a
            # session that no longer exists. Fail loudly instead.
            app_logger.error(f"Connect polling thread crashed: {traceback.format_exc()}")
            self.bridge.log(
                i18n.t("log_poll_crashed", err=type(error).__name__), level="error"
            )
            if self._active_session is session:
                self.bridge._session_status = "idle"
                self.bridge.broadcast("state_updated", self.bridge.get_state())
        finally:
            if self._active_session is session:
                self.is_polling = False

    def _schedule_reconnect(self, target: str) -> None:
        """Retry a dropped connection, but a bounded number of times.

        Before the launch-blocking check was removed this loop was capped by
        accident: the second attempt was refused because Rust was already
        open. Now the command always goes through, so a server that keeps
        rejecting us (outdated client, ban, password) would be retried
        forever without this budget.
        """
        if target != self._reconnect_target:
            self._reconnect_target = target
            self._reconnect_attempts = 0
        if self._reconnect_attempts >= _MAX_RECONNECT_ATTEMPTS:
            self.bridge.log(
                i18n.t("log_autoreconnect_gave_up", target=target, attempts=_MAX_RECONNECT_ATTEMPTS),
                level="error",
            )
            return

        delay = _RECONNECT_BACKOFF_SECONDS[min(self._reconnect_attempts, len(_RECONNECT_BACKOFF_SECONDS) - 1)]
        self._reconnect_attempts += 1
        self.bridge.log(
            i18n.t(
                "log_autoreconnect_in",
                seconds=int(delay),
                attempt=self._reconnect_attempts,
                attempts=_MAX_RECONNECT_ATTEMPTS,
            ),
            level="info",
        )

        def fire() -> None:
            self._reconnect_timer = None
            self.connect(target, reset_attempts=False)

        timer = threading.Timer(delay, fire)
        timer.daemon = True
        self._reconnect_timer = timer
        timer.start()

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
            # The same steam://run//+connect URL works in both states -
            # it launches a closed Rust, and it also redirects a client that
            # is already open in the main menu (measured against a real
            # client, 2026-09-04). Only the wording changes, so the user can
            # tell which of the two is happening.
            # Launching an outdated client just makes Steam download the
            # update while we wait for a join that can never happen - Rust
            # patches on every force-wipe day, exactly when this matters.
            if not self.bridge.wait_for_rust_update(lambda: self._is_current(operation_id, session)):
                return
            rust_already_running = process_monitor.is_rust_running()
            # The watcher must be listening before the client can answer.
            self._start_log_monitor(target, session, operation_id)
            steam_service.dispatch_launch(target, config.STEAM_APP_ID)
            session.launched_by_app = True
            session.steam_url_dispatched = True
            session.steam_request_started_at = time.monotonic()
            session.relaunch_was_already_running = rust_already_running
            session.last_launch_sent_at = session.steam_request_started_at
            session.redirect_resend_count = 0
            queue_suffix = i18n.t("log_launch_sent_queue_suffix") if queue_mode else ""
            sent_key = "log_connect_sent_rust_running" if rust_already_running else "log_launch_sent"
            self.bridge.log(i18n.t(sent_key) + queue_suffix, level="success")
            self.bridge._session_status = "Queueing" if queue_mode else "Launching"
            self.bridge._last_connected_ip = target
            self.bridge.broadcast("state_updated", self.bridge.get_state())
            self._start_confirmation_watchdog(session, target, queue_mode=queue_mode)
        except Exception as err:
            self.bridge.log(i18n.t("log_launch_error", err=str(err)), level="error")
            self.stop(explicit=False)

    def _observation_expired(self, session: ConnectionSession) -> bool:
        """True once we have watched a launched session for longer than any
        real join takes. Queueing is given far longer, because waiting in
        Rust's own queue legitimately takes many minutes."""
        started = session.steam_request_started_at
        if not started or self.is_connected:
            return False
        limit = _QUEUE_OBSERVATION_LIMIT_SECONDS if session.queue_requested else _OBSERVATION_LIMIT_SECONDS
        return (time.monotonic() - started) > limit

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
                # A join that actually worked clears the retry budget, so a
                # later, unrelated disconnect gets its full allowance again.
                self._reconnect_attempts = 0
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
            self.is_connected = False
            # Matches app.py: reconnect whenever this session (launched by us)
            # targets the currently armed server - a rejected FIRST attempt
            # (kick, full, "Connection Attempt Failed") must retry too, not
            # only a disconnect after an already-confirmed connection. This
            # is unrelated to the separate auto_arm setting, which only
            # controls auto-arming from a manually-detected in-game connect.
            armed = history_store.get_armed_server()
            should_reconnect = bool(
                session.launched_by_app and armed and armed in (target, session.canonical_endpoint)
            )
            self.stop(explicit=True)
            self.bridge._session_status = "idle"
            self.bridge.broadcast("state_updated", self.bridge.get_state())
            if should_reconnect:
                self._schedule_reconnect(target)

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
