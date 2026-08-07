"""Adversarial stress and verification test suite for A2SQueryEngine in src/query.py.

This module empirically stress-tests rate-limiting enforcement, thread lifecycle/concurrency,
and callback exception resilience.
"""

import socket
import threading
import time
from typing import Any, Dict, List, Tuple

import pytest

from src.query import A2SQueryEngine
from tests.mock_a2s_server import MockA2SServer


# ============================================================================
# 1. Rate-Limiting Enforcement Tests
# ============================================================================

def test_rate_limiting_consecutive_timestamps():
    """Verify that timestamps of consecutive UDP queries respect minimum poll_interval."""
    with MockA2SServer(host="127.0.0.1", port=0, challenge_enabled=False) as server:
        query_timestamps: List[float] = []

        def callback(status_type: str, message: str, count: int, info: Dict[str, Any]):
            if status_type.upper() in ("SUCCESS", "READY"):
                query_timestamps.append(time.monotonic())

        poll_interval = 0.2
        engine = A2SQueryEngine(
            ip="127.0.0.1",
            port=server.port,
            poll_interval=poll_interval,
            required_successes=10,
            callback=callback,
        )

        engine.start_polling()
        time.sleep(1.05)
        engine.stop_polling()

        assert len(query_timestamps) >= 4, f"Expected >=4 queries, got {len(query_timestamps)}"

        intervals = [
            query_timestamps[i] - query_timestamps[i - 1]
            for i in range(1, len(query_timestamps))
        ]

        for i, interval in enumerate(intervals):
            assert interval >= (poll_interval * 0.85), (
                f"Interval {i} was {interval:.4f}s, expected >= {poll_interval * 0.85:.4f}s"
            )


def test_rate_limiting_with_server_delay():
    """Verify rate-limiting logic when server has processing delay (e.g. 0.08s delay)."""
    with MockA2SServer(host="127.0.0.1", port=0, challenge_enabled=False, delay=0.08) as server:
        query_timestamps: List[float] = []

        def callback(status_type: str, message: str, count: int, info: Dict[str, Any]):
            if status_type.upper() in ("SUCCESS", "READY"):
                query_timestamps.append(time.monotonic())

        poll_interval = 0.25
        engine = A2SQueryEngine(
            ip="127.0.0.1",
            port=server.port,
            poll_interval=poll_interval,
            required_successes=10,
            callback=callback,
        )

        engine.start_polling()
        time.sleep(1.1)
        engine.stop_polling()

        assert len(query_timestamps) >= 3, f"Expected >=3 queries, got {len(query_timestamps)}"

        intervals = [
            query_timestamps[i] - query_timestamps[i - 1]
            for i in range(1, len(query_timestamps))
        ]

        for i, interval in enumerate(intervals):
            # Total loop time should be approximately max(poll_interval, query_duration)
            assert interval >= (poll_interval * 0.85), (
                f"Interval {i} with delay was {interval:.4f}s, expected >= {poll_interval * 0.85:.4f}s"
            )


# ============================================================================
# 2. Thread Lifecycle & Concurrency Stress Tests
# ============================================================================

def test_concurrent_start_stop_hammering():
    """Stress test calling start_polling(), stop_polling(), and is_polling() concurrently from 20 threads."""
    with MockA2SServer(host="127.0.0.1", port=0, challenge_enabled=False) as server:
        engine = A2SQueryEngine(
            ip="127.0.0.1",
            port=server.port,
            poll_interval=0.05,
            required_successes=3,
        )

        exceptions: List[Exception] = []

        def worker(worker_id: int):
            try:
                for i in range(25):
                    if worker_id % 3 == 0:
                        engine.start_polling()
                    elif worker_id % 3 == 1:
                        engine.stop_polling()
                    else:
                        _ = engine.is_polling()
                        _ = engine.get_success_count()
                    time.sleep(0.001)
            except Exception as e:
                exceptions.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Clean up
        engine.stop_polling()

        assert len(exceptions) == 0, f"Thread stress test raised exceptions: {exceptions}"
        assert not engine.is_polling()


def test_rapid_start_stop_cycles():
    """Verify rapid sequential start_polling() and stop_polling() cycles."""
    with MockA2SServer(host="127.0.0.1", port=0, challenge_enabled=False) as server:
        engine = A2SQueryEngine(
            ip="127.0.0.1",
            port=server.port,
            poll_interval=0.1,
            required_successes=2,
        )

        for _ in range(30):
            engine.start_polling()
            assert engine.is_polling()
            engine.stop_polling()
            assert not engine.is_polling()


def test_stop_polling_from_inside_callback():
    """Verify stopping the query engine from within its own callback does not cause a deadlock."""
    with MockA2SServer(host="127.0.0.1", port=0, challenge_enabled=False) as server:
        engine = None

        def self_stopping_callback(status_type, message, count, info):
            nonlocal engine
            if status_type.upper() == "SUCCESS" and count >= 1 and engine is not None:
                # Stop engine directly from inside thread invoking callback
                engine.stop_polling()

        engine = A2SQueryEngine(
            ip="127.0.0.1",
            port=server.port,
            poll_interval=0.05,
            required_successes=3,
            callback=self_stopping_callback,
        )

        engine.start_polling()

        # Wait up to 1 second for callback to stop the engine
        start = time.monotonic()
        stopped = False
        while time.monotonic() - start < 1.0:
            if not engine.is_polling():
                stopped = True
                break
            time.sleep(0.05)

        assert stopped, "Engine failed to stop cleanly when stop_polling() called from callback"
        assert not engine.is_polling()


def test_start_polling_idempotency():
    """Verify repeated start_polling() calls when already active are safe no-ops."""
    with MockA2SServer(host="127.0.0.1", port=0, challenge_enabled=False) as server:
        engine = A2SQueryEngine(
            ip="127.0.0.1",
            port=server.port,
            poll_interval=0.1,
            required_successes=2,
        )

        engine.start_polling()
        t1 = engine._thread
        engine.start_polling()
        t2 = engine._thread
        assert t1 is t2, "start_polling() spawned new thread while already polling"

        engine.stop_polling()


# ============================================================================
# 3. Callback Resilience Tests
# ============================================================================

class CustomException(Exception):
    """Custom exception subclassing Exception."""
    pass


class CustomBaseException(BaseException):
    """Custom exception subclassing BaseException directly."""
    pass


def test_callback_custom_exception_subclass():
    """Verify loop survives callback throwing a custom Exception subclass."""
    with MockA2SServer(host="127.0.0.1", port=0, challenge_enabled=False) as server:
        call_count = 0

        def buggy_callback(status_type, message, count, info):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise CustomException("Custom error in callback")

        engine = A2SQueryEngine(
            ip="127.0.0.1",
            port=server.port,
            poll_interval=0.05,
            required_successes=5,
            callback=buggy_callback,
        )

        engine.start_polling()
        time.sleep(0.3)
        engine.stop_polling()

        assert call_count >= 3, f"Expected polling loop to continue after CustomException, got {call_count} calls"


def test_callback_standard_exceptions():
    """Verify loop survives standard built-in exceptions (ValueError, TypeError, ZeroDivisionError)."""
    with MockA2SServer(host="127.0.0.1", port=0, challenge_enabled=False) as server:
        call_count = 0

        def chaos_callback(status_type, message, count, info):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("Bad value")
            elif call_count == 2:
                raise TypeError("Bad type")
            elif call_count == 3:
                _ = 1 / 0

        engine = A2SQueryEngine(
            ip="127.0.0.1",
            port=server.port,
            poll_interval=0.05,
            required_successes=5,
            callback=chaos_callback,
        )

        engine.start_polling()
        time.sleep(0.3)
        engine.stop_polling()

        assert call_count >= 4, f"Expected loop to survive multiple built-in exceptions, got {call_count} calls"


def test_callback_base_exception_behavior():
    """Test behavior when callback raises a BaseException subclass."""
    with MockA2SServer(host="127.0.0.1", port=0, challenge_enabled=False) as server:
        call_count = 0

        def base_error_callback(status_type, message, count, info):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise CustomBaseException("Fatal base error")

        engine = A2SQueryEngine(
            ip="127.0.0.1",
            port=server.port,
            poll_interval=0.05,
            required_successes=5,
            callback=base_error_callback,
        )

        engine.start_polling()
        time.sleep(0.25)
        engine.stop_polling()

        # Document whether BaseException breaks the thread or is uncaught
        # (Self-verifying empirical measurement)
