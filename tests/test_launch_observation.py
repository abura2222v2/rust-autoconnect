"""Regression tests for observing a server while Rust is loading.

No Steam, Rust process, network service, or real Player.log is used here.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock
import queue
import threading

import pytest

from src.app import AppController
from src.core.a2s_client import ServerStatus
from src.core.smart_monitor import ConnectionPhase, ConnectionSession


class _OneWaitEvent:
    """Acts as a cancellation event after one post-launch observation."""

    def __init__(self):
        self.cancelled = False

    def is_set(self):
        return self.cancelled

    def set(self):
        self.cancelled = True

    def wait(self, _timeout=None):
        self.cancelled = True
        return True


class _FixedClock:
    def now(self):
        return datetime(2026, 8, 12, tzinfo=timezone.utc)


def _loading_controller(status: ServerStatus):
    controller = object.__new__(AppController)
    controller._state_lock = threading.Lock()
    controller._operation_lock = threading.Lock()
    controller._poll_operation = 7
    controller._benchmark_operation = 0
    controller._is_polling = True
    controller._is_reconnecting = False
    controller._shutdown_event = threading.Event()
    controller._poll_stop_event = threading.Event()
    controller._poll_wake_event = threading.Event()
    controller._ui_queue = queue.Queue()
    controller.network_clock = _FixedClock()
    controller.history_store = MagicMock()
    controller.history_store.get_server_wipe_schedule.return_value = {"wipe_at": None, "wipe_source": ""}
    controller.swarm_service = MagicMock()
    controller.a2s_client = MagicMock()
    controller.a2s_client.check_server_status.return_value = status
    controller._refresh_provider_hint = MagicMock()
    controller.log_safe = MagicMock()
    controller.set_connection_phase = MagicMock()
    controller.set_connection_state = MagicMock()
    controller.refresh_history_ui = MagicMock()
    controller.launch_game = MagicMock()
    controller.t = lambda key, **_kwargs: key
    controller.dispatch_ui = lambda callback, *args, **kwargs: callback(*args)
    controller._last_smart_phase = None
    controller._last_probe_outcome = ""

    session = ConnectionSession(
        "127.0.0.1:28015",
        canonical_endpoint="127.0.0.1:28015",
        phase=ConnectionPhase.AWAITING_LOG_CONFIRMATION,
        launched_by_app=True,
        stop_event=_OneWaitEvent(),
    )
    controller._active_session = session
    return controller, session


@pytest.mark.parametrize(
    ("status", "expected_state", "expected_log"),
    [
        (ServerStatus(True, player_count=0, max_players=100), "launching", "launch_server_online"),
        (ServerStatus(False), "offline", "launch_server_offline"),
    ],
)
def test_loading_rust_keeps_observing_server_without_second_steam_launch(status, expected_state, expected_log):
    controller, _session = _loading_controller(status)

    AppController.run_logic(controller, "127.0.0.1:28015", operation_id=7)

    controller.a2s_client.check_server_status.assert_called_once()
    controller.launch_game.assert_not_called()
    profile_call = controller.history_store.update_server_profile.call_args
    assert profile_call.args == ("127.0.0.1:28015",)
    assert profile_call.kwargs["state"] == expected_state
    assert isinstance(profile_call.kwargs["checked_at"], int)
    assert any(call.args[0] == expected_log for call in controller.log_safe.call_args_list)
