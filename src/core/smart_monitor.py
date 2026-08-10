"""State and polling policy for a single safe auto-connect session."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import Event
from typing import Optional


class ConnectionPhase(str, Enum):
    IDLE = "idle"
    SCHEDULED = "scheduled"
    WATCH = "watch"
    TURBO = "turbo"
    LAUNCH_REQUESTED = "launch_requested"
    AWAITING_LOG_CONFIRMATION = "awaiting_log_confirmation"
    CONNECTED = "connected"
    COOLDOWN = "cooldown"


@dataclass(frozen=True)
class PollingPolicy:
    idle_seconds: float = 30.0
    watch_seconds: float = 5.0
    turbo_seconds: float = 1.0
    watch_window: timedelta = timedelta(minutes=30)
    turbo_window: timedelta = timedelta(minutes=5)
    max_turbo_duration: timedelta = timedelta(minutes=5)
    confirmation_gap_seconds: float = 0.3


@dataclass
class ConnectionSession:
    requested_endpoint: str
    canonical_endpoint: str = ""
    wipe_at: Optional[datetime] = None
    wipe_source: str = ""
    phase: ConnectionPhase = ConnectionPhase.IDLE
    launched_by_app: bool = False
    down_observed: bool = False
    turbo_until: Optional[datetime] = None
    swarm_hint_pending: bool = False
    offline_turbo_used: bool = False
    stop_event: Event = field(default_factory=Event)

    def select_phase(self, now: Optional[datetime] = None, swarm_hint: bool = False) -> ConnectionPhase:
        now = now or datetime.now(timezone.utc)
        if self.stop_event.is_set():
            self.phase = ConnectionPhase.IDLE
            return self.phase
        if swarm_hint:
            self.request_turbo(now)
        if self.turbo_until is not None:
            if now < self.turbo_until:
                self.phase = ConnectionPhase.TURBO
                return self.phase
            self.down_observed = False
            self.swarm_hint_pending = False
            self.turbo_until = None
        if self.wipe_at:
            remaining = self.wipe_at - now
            if timedelta(minutes=-30) <= remaining <= PollingPolicy().turbo_window:
                self.phase = ConnectionPhase.TURBO
            elif timedelta(minutes=-60) <= remaining <= PollingPolicy().watch_window:
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

    def observe_server_down(self, now: Optional[datetime] = None) -> None:
        """Use one bounded turbo window after a confirmed offline result."""
        if self.offline_turbo_used:
            return
        self.offline_turbo_used = True
        self.down_observed = True
        self.request_turbo(now)

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
