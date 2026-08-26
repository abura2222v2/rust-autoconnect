"""State and polling policy for a single safe auto-connect session."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import Event, Lock
import time
from typing import Optional


class ConnectionPhase(str, Enum):
    IDLE = "idle"
    SCHEDULED = "scheduled"
    WATCH = "watch"
    TURBO = "turbo"
    WAITING_FOR_WIPE_RESTART = "waiting_for_wipe_restart"
    LAUNCH_REQUESTED = "launch_requested"
    QUEUED = "queued"
    AWAITING_LOG_CONFIRMATION = "awaiting_log_confirmation"
    CONNECTED = "connected"
    COOLDOWN = "cooldown"


@dataclass(frozen=True)
class PollingPolicy:
    # Quiet by default.  Turbo is deliberately short and only enabled by a
    # trusted schedule, a confirmed offline transition, or a Swarm hint.
    # A selected/armed server is intentionally simple: one local check every
    # 30 seconds.  Provider data is fetched independently at most once/minute.
    idle_seconds: float = 30.0
    watch_seconds: float = 30.0
    turbo_seconds: float = 2.0
    watch_window: timedelta = timedelta(minutes=30)
    turbo_window: timedelta = timedelta(minutes=5)
    max_turbo_duration: timedelta = timedelta(minutes=5)
    confirmation_gap_seconds: float = 0.3
    # An A2S timeout can also mean that a server uses another query port or
    # filters queries.  Probe cautiously before falling back to quiet mode.
    first_query_retry_seconds: float = 30.0
    full_server_retry_seconds: float = 30.0
    manual_fast_retry_seconds: float = 5.0
    manual_watch_retry_seconds: float = 15.0
    # Once Steam has been launched, keep a light independent observation
    # running until Rust confirms the selected server in Player.log.  This is
    # not a retry to launch Steam and therefore cannot create duplicate joins.
    launch_confirmation_probe_seconds: float = 5.0


@dataclass
class ConnectionSession:
    requested_endpoint: str
    # Normal mode: constant fast polling from Start, ignoring the wipe
    # schedule entirely. Smart mode (wipe-aware quiet/watch/turbo) is kept
    # intact below but is not currently reachable from the settings UI.
    smart_mode: bool = False
    canonical_endpoint: str = ""
    wipe_at: Optional[datetime] = None
    wipe_source: str = ""
    force_wipe_at: Optional[datetime] = None
    phase: ConnectionPhase = ConnectionPhase.IDLE
    launched_by_app: bool = False
    steam_url_dispatched: bool = False
    steam_request_started_at: Optional[float] = None
    post_dispatch_log_activity_seen: bool = False
    steam_handoff_warning_reported: bool = False
    target_connection_attempt_seen: bool = False
    queue_requested: bool = False
    menu_ready: bool = False
    waiting_for_wipe_restart: bool = False
    wipe_restart_seen: bool = False
    wipe_wait_announced_online: bool = False
    # A manual Connect may intentionally enter Rust's server queue. Automatic
    # recovery must wait for a playable slot instead of launching Rust again.
    queue_on_full: bool = False
    down_observed: bool = False
    turbo_until: Optional[datetime] = None
    swarm_hint_pending: bool = False
    offline_turbo_used: bool = False
    force_wipe_notified: bool = False
    consecutive_query_failures: int = 0
    query_was_confirmed_alive: bool = False
    provider_online: Optional[bool] = None
    provider_checked_at: Optional[datetime] = None
    provider_last_requested_at: Optional[datetime] = None
    provider_refresh_in_flight: bool = False
    provider_query_port: Optional[int] = None
    provider_wipe_baseline: Optional[tuple[object, ...]] = None
    provider_wipe_change_detected: bool = False
    provider_wipe_offline_seen: bool = False
    watch_until: Optional[datetime] = None
    stop_event: Event = field(default_factory=Event)
    diagnostic_started_at: float = field(default_factory=time.monotonic)
    diagnostic_stage: str = ""
    diagnostic_events: list[tuple[str, float]] = field(default_factory=list)
    dns_refresh_attempted: bool = False
    _diagnostic_lock: Lock = field(default_factory=Lock, repr=False, compare=False)

    def record_stage(self, stage: str) -> tuple[float, bool]:
        """Record a user-visible connection stage using a monotonic clock."""
        elapsed = max(0.0, time.monotonic() - self.diagnostic_started_at)
        with self._diagnostic_lock:
            changed = stage != self.diagnostic_stage
            if changed:
                self.diagnostic_stage = stage
                self.diagnostic_events.append((stage, elapsed))
        return elapsed, changed

    def select_phase(self, now: Optional[datetime] = None, swarm_hint: bool = False) -> ConnectionPhase:
        now = now or datetime.now(timezone.utc)
        if self.stop_event.is_set():
            self.phase = ConnectionPhase.IDLE
            return self.phase
        if not self.smart_mode:
            # Normal mode: dumb constant-rate polling, no wipe awareness.
            self.phase = ConnectionPhase.TURBO
            return self.phase
        # Swarm is advisory only.  It may wake the next local probe but must
        # never escalate the connection rate or trigger a Steam launch.
        if self.turbo_until is not None:
            if now < self.turbo_until:
                self.phase = ConnectionPhase.TURBO
                return self.phase
            self.down_observed = False
            self.swarm_hint_pending = False
            self.turbo_until = None
        if self.watch_until is not None and now < self.watch_until:
            self.phase = ConnectionPhase.WATCH
            return self.phase
        if self.force_wipe_at:
            remaining = self.force_wipe_at - now
            # The expected wipe is not proof that a server is ready. Turbo is
            # limited to T-5 through T+5; early restarts use offline/Swarm.
            if timedelta(minutes=-5) <= remaining <= timedelta(minutes=5):
                self.phase = ConnectionPhase.TURBO
                return self.phase
            if timedelta(minutes=-30) <= remaining <= timedelta(minutes=30):
                self.phase = ConnectionPhase.WATCH
                return self.phase
        if self.wipe_at:
            remaining = self.wipe_at - now
            if timedelta(minutes=-5) <= remaining <= PollingPolicy().turbo_window:
                self.phase = ConnectionPhase.TURBO
            elif timedelta(minutes=-30) <= remaining <= PollingPolicy().watch_window:
                self.phase = ConnectionPhase.WATCH
            else:
                self.phase = ConnectionPhase.SCHEDULED
        else:
            self.phase = ConnectionPhase.SCHEDULED
        return self.phase

    def request_turbo(self, now: Optional[datetime] = None) -> None:
        now = now or datetime.now(timezone.utc)
        self.swarm_hint_pending = True
        self.turbo_until = now + PollingPolicy().max_turbo_duration
        # A restart can take longer than the short turbo window.  Continue
        # watching at a moderate rate instead of falling back to ten minutes.
        self.watch_until = now + timedelta(minutes=30)

    def begin_wipe_restart_hold(self, now: Optional[datetime] = None) -> bool:
        """Hold a new launch during the final pre-wipe window.

        A live old map is not evidence that the post-wipe server is ready.
        This affects a not-yet-launched session only; it never ejects a player
        who is already in Rust.
        """
        now = now or datetime.now(timezone.utc)
        if not self.smart_mode:
            return False
        if self.launched_by_app or self.waiting_for_wipe_restart or self.wipe_restart_seen:
            return False
        candidates = (self.wipe_at, self.force_wipe_at)
        if any(
            wipe_at is not None and timedelta(0) < wipe_at - now <= PollingPolicy().turbo_window
            for wipe_at in candidates
        ):
            self.waiting_for_wipe_restart = True
            self.phase = ConnectionPhase.WAITING_FOR_WIPE_RESTART
            return True
        return False

    def wipe_time_has_arrived(self, now: Optional[datetime] = None) -> bool:
        """Return whether one of the held wipe schedules has been reached."""
        now = now or datetime.now(timezone.utc)
        return any(wipe_at is not None and now >= wipe_at for wipe_at in (self.wipe_at, self.force_wipe_at))

    def confirm_wipe_restart(self) -> bool:
        """Release the pre-wipe hold after a trustworthy restart signal."""
        if not self.waiting_for_wipe_restart:
            return False
        self.waiting_for_wipe_restart = False
        self.wipe_restart_seen = True
        return True

    def observe_server_down(self, now: Optional[datetime] = None) -> None:
        """Use one bounded turbo window after a confirmed offline result."""
        now = now or datetime.now(timezone.utc)
        self.watch_until = now + timedelta(minutes=30)
        if self.offline_turbo_used:
            return
        self.offline_turbo_used = True
        self.down_observed = True
        self.request_turbo(now)

    def apply_provider_hint(
        self, *, online: Optional[bool], wipe_at: Optional[datetime], source: str,
        confidence: str, checked_at: Optional[datetime], now: Optional[datetime] = None,
    ) -> bool:
        """Apply provider data as a hint; only explicit offline enables turbo."""
        now = now or datetime.now(timezone.utc)
        changed = online is not None and online != self.provider_online
        self.provider_online = online
        self.provider_checked_at = checked_at
        if wipe_at is not None:
            self.wipe_at = wipe_at
            self.wipe_source = source
        if online is False:
            self.observe_server_down(now)
        return changed

    def observe_provider_wipe_fingerprint(
        self, fingerprint: tuple[object, ...], now: Optional[datetime] = None,
    ) -> bool:
        """Detect a post-force-wipe provider change without trusting a clock alone."""
        now = now or datetime.now(timezone.utc)
        if not fingerprint or not self.force_wipe_at:
            return False
        if not self.force_wipe_at - timedelta(minutes=30) <= now <= self.force_wipe_at + timedelta(minutes=30):
            return False
        if self.provider_wipe_baseline is None:
            self.provider_wipe_baseline = fingerprint
            return False
        if fingerprint != self.provider_wipe_baseline and now >= self.force_wipe_at - timedelta(minutes=5):
            self.provider_wipe_change_detected = True
            return True
        return False

    def observe_provider_wipe_availability(self, online: Optional[bool]) -> bool:
        """Require an observed provider offline-to-online transition for a wipe restart."""
        if online is False:
            self.provider_wipe_offline_seen = True
            return False
        if online is True and self.provider_wipe_offline_seen:
            self.provider_wipe_offline_seen = False
            return True
        return False

    def observe_query_result(self, alive: bool, now: Optional[datetime] = None) -> bool:
        """Record an A2S result and return whether a restart is confirmed.

        A first missing A2S reply is ambiguous: the query port may differ from
        the game port or be filtered.  Only two misses after a successful
        reply are treated as a server restart and allowed to enable turbo.
        """
        if alive:
            self.consecutive_query_failures = 0
            self.query_was_confirmed_alive = True
            return False

        self.consecutive_query_failures += 1
        if self.query_was_confirmed_alive and self.consecutive_query_failures >= 2:
            self.query_was_confirmed_alive = False
            self.observe_server_down(now)
            return True
        return False

    def query_retry_seconds(self, now: Optional[datetime] = None) -> float:
        """Back off unknown A2S failures without delaying initial discovery."""
        policy = PollingPolicy()
        if self.queue_on_full:
            # A person waiting for a just-starting server gets a short fast
            # probe window. Armed recovery retains the quieter backoff below.
            if self.consecutive_query_failures <= 12:
                return policy.manual_fast_retry_seconds
            if self.consecutive_query_failures <= 24:
                return policy.manual_watch_retry_seconds
            # After the four-minute fast window, widen gradually rather than
            # jumping straight to the quiet ten-minute schedule.
            manual_backoff = (30.0, 60.0, 120.0, 240.0, policy.idle_seconds)
            index = min(self.consecutive_query_failures - 25, len(manual_backoff) - 1)
            return manual_backoff[index]
        retries = max(0, self.consecutive_query_failures - 1)
        discovery_delay = min(policy.idle_seconds, policy.first_query_retry_seconds * (2 ** retries))
        return min(self.interval_seconds(now), discovery_delay)

    def full_server_retry_seconds(self, now: Optional[datetime] = None) -> float:
        """Keep checking a healthy full server for an open slot."""
        return min(self.interval_seconds(now), PollingPolicy().full_server_retry_seconds)

    def reset_offline_turbo(self) -> None:
        self.offline_turbo_used = False

    def consume_hint(self) -> None:
        self.swarm_hint_pending = False

    def interval_seconds(self, now: Optional[datetime] = None, swarm_hint: bool = False) -> float:
        phase = self.select_phase(now, swarm_hint)
        policy = PollingPolicy()
        if phase == ConnectionPhase.TURBO:
            return policy.turbo_seconds
        if phase == ConnectionPhase.WATCH:
            return policy.watch_seconds
        return policy.idle_seconds

    def cancel(self) -> None:
        self.stop_event.set()
        self.phase = ConnectionPhase.IDLE
