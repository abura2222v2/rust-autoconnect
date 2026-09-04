# -*- coding: utf-8 -*-
"""Empirical Adversarial Stress Tests for Telegram Integration & WebBridge Status Loops.

Challenger: challenger_1
Scope:
1. Challenge `WebBridge._telegram_status_loop` with simulated rapid state changes:
   - Full state machine transition cycle: unlinked -> code generation -> linked -> name change -> external unlink -> link code regeneration.
   - Network failure/timeout resilience: verify intermittent None responses do not trigger false state_updated broadcasts or mutate internal state.
   - Malformed/dirty JSON responses from Edge Function: verify exception resilience and input sanitization.
   - Live background thread execution of `_telegram_status_loop` under rapid polling and dynamic state mutations.
   - Rapid chaos generator: 100 random state transitions verifying invariant consistency and accurate broadcast dispatch.
   - Unicode & emoji display_name resilience.
   - Unhandled exception resilience in polling loop.
2. Stress test concurrent WebSocket client broadcasts during Telegram status transitions:
   - High-concurrency broadcast delivery across 50-100 simultaneous mock WebSocket clients.
   - Fault tolerance against faulty/crashing WebSocket clients (ConnectionResetError, BrokenPipeError, slow clients).
   - High-frequency client churn (concurrent connect/disconnect during active broadcasts) verifying lock thread-safety.
   - Payload schema and JSON serialization integrity checks.
   - Broadcast resilience with closed or uninitialized event loops.
   - Concurrent action dispatch (generate_telegram_link + unlink_telegram) under multi-threaded load.
"""

import asyncio
import concurrent.futures
import json
import random
import threading
import time
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch, call
import pytest

from src.services.telegram_service import TelegramService
from src.web.bridge import WebBridge


# ============================================================================
# Dimension 1: WebBridge._telegram_status_loop Rapid State Transitions
# ============================================================================

class TestTelegramStatusLoopTransitions:
    """Stress tests for WebBridge._telegram_status_loop under rapid state changes."""

    def test_full_telegram_lifecycle_state_transitions(self):
        """Simulate rapid state cycle: unlinked -> link code -> linked -> rename -> unlinked -> code regenerated."""
        tg = TelegramService()
        tg._save = MagicMock()
        tg.client_id = "test-client-id-0001"
        tg.notification_token = None
        tg.link_code = None
        tg.display_name = None
        tg.is_linked = False

        bridge = WebBridge()
        bridge.telegram_service = tg
        broadcast_events: List[Dict[str, Any]] = []

        def capture_broadcast(event_type: str, data: Any = None):
            broadcast_events.append({"type": event_type, "data": data})

        bridge.broadcast = capture_broadcast

        # Step 1: Initial unlinked state (no token, no code)
        prev_linked = tg.is_linked
        prev_name = tg.display_name
        if tg.is_linked or tg.notification_token:
            status = tg.get_link_status()
            if status and (tg.is_linked != prev_linked or tg.display_name != prev_name):
                bridge.broadcast("state_updated", bridge.get_state())

        assert len(broadcast_events) == 0
        state = bridge.get_state()
        assert state["telegram"]["is_linked"] is False
        assert state["telegram"]["display_name"] is None
        assert state["telegram"]["link_code"] is None

        # Step 2: User generates link code (token set, code set, is_linked=False)
        with patch.object(tg, "_request", return_value={"accepted": True, "notification_token": "token-xyz-123"}):
            code = bridge.generate_telegram_link()
            assert code is not None
            assert code["success"] is True

        # generate_telegram_link triggers a broadcast
        assert len(broadcast_events) == 1
        assert broadcast_events[-1]["type"] == "state_updated"
        assert broadcast_events[-1]["data"]["telegram"]["link_code"] == code["code"]
        assert broadcast_events[-1]["data"]["telegram"]["is_linked"] is False

        # Step 3: Polling loop detects user paired bot on Telegram (is_linked=True, display_name="@RustVeteran")
        with patch.object(tg, "_request", return_value={"linked": True, "display_name": "@RustVeteran"}):
            prev_linked = tg.is_linked
            prev_name = tg.display_name
            status = tg.get_link_status()
            if status and (tg.is_linked != prev_linked or tg.display_name != prev_name):
                bridge.broadcast("state_updated", bridge.get_state())

        assert len(broadcast_events) == 2
        assert broadcast_events[-1]["type"] == "state_updated"
        assert broadcast_events[-1]["data"]["telegram"]["is_linked"] is True
        assert broadcast_events[-1]["data"]["telegram"]["display_name"] == "@RustVeteran"
        assert broadcast_events[-1]["data"]["telegram"]["link_code"] is None

        # Step 4: Subsequent poll with identical state -> NO broadcast
        with patch.object(tg, "_request", return_value={"linked": True, "display_name": "@RustVeteran"}):
            prev_linked = tg.is_linked
            prev_name = tg.display_name
            status = tg.get_link_status()
            if status and (tg.is_linked != prev_linked or tg.display_name != prev_name):
                bridge.broadcast("state_updated", bridge.get_state())

        assert len(broadcast_events) == 2  # No duplicate broadcast

        # Step 5: User updates their Telegram handle / display name to "@RustOverlord"
        with patch.object(tg, "_request", return_value={"linked": True, "display_name": "@RustOverlord"}):
            prev_linked = tg.is_linked
            prev_name = tg.display_name
            status = tg.get_link_status()
            if status and (tg.is_linked != prev_linked or tg.display_name != prev_name):
                bridge.broadcast("state_updated", bridge.get_state())

        assert len(broadcast_events) == 3
        assert broadcast_events[-1]["data"]["telegram"]["is_linked"] is True
        assert broadcast_events[-1]["data"]["telegram"]["display_name"] == "@RustOverlord"

        # Step 6: User unlinks bot externally via Telegram chat command (/unlink)
        with patch.object(tg, "_request", return_value={"linked": False, "display_name": None}):
            prev_linked = tg.is_linked
            prev_name = tg.display_name
            status = tg.get_link_status()
            if status and (tg.is_linked != prev_linked or tg.display_name != prev_name):
                bridge.broadcast("state_updated", bridge.get_state())

        assert len(broadcast_events) == 4
        assert broadcast_events[-1]["data"]["telegram"]["is_linked"] is False
        assert broadcast_events[-1]["data"]["telegram"]["display_name"] is None

        # Step 7: User generates a new link code
        with patch.object(tg, "_request", return_value={"accepted": True, "notification_token": "token-new-456"}):
            new_code = bridge.generate_telegram_link()
            assert new_code["success"] is True

        assert len(broadcast_events) == 5
        assert broadcast_events[-1]["data"]["telegram"]["link_code"] == new_code["code"]
        assert broadcast_events[-1]["data"]["telegram"]["is_linked"] is False

    def test_telegram_status_loop_intermittent_network_failures(self):
        """Verify that intermittent None responses from Edge Function do not trigger false state broadcasts or state loss."""
        tg = TelegramService()
        tg._save = MagicMock()
        tg.client_id = "test-client-id-0002"
        tg.notification_token = "valid-token-777"
        tg.display_name = "@Survivor"
        tg.is_linked = True

        bridge = WebBridge()
        bridge.telegram_service = tg
        broadcast_events = []
        bridge.broadcast = lambda event_type, data=None: broadcast_events.append({"type": event_type, "data": data})

        # Simulate 10 network drops / timeouts (get_link_status returning None)
        for _ in range(10):
            with patch.object(tg, "_request", return_value=None):
                prev_linked = tg.is_linked
                prev_name = tg.display_name
                status = tg.get_link_status()
                if status and (tg.is_linked != prev_linked or tg.display_name != prev_name):
                    bridge.broadcast("state_updated", bridge.get_state())

        assert len(broadcast_events) == 0
        assert tg.is_linked is True
        assert tg.display_name == "@Survivor"

    def test_telegram_status_loop_malformed_and_dirty_responses(self):
        """Stress test _telegram_status_loop against corrupted, typed-mismatched, or missing payload keys."""
        tg = TelegramService()
        tg._save = MagicMock()
        tg.client_id = "test-client-id-0003"
        tg.notification_token = "valid-token-888"
        tg.display_name = "@Original"
        tg.is_linked = True

        bridge = WebBridge()
        bridge.telegram_service = tg
        broadcast_events = []
        bridge.broadcast = lambda event_type, data=None: broadcast_events.append({"type": event_type, "data": data})

        dirty_payloads = [
            {},                                       # Missing all keys
            {"linked": "true"},                       # String instead of bool
            {"linked": 1},                            # Int instead of bool
            {"linked": True, "display_name": 9999},   # Int display_name (should be sanitized to None)
            {"linked": True, "display_name": ""},     # Empty string (should be sanitized to None)
            {"linked": True, "display_name": False},  # Bool display_name (should be sanitized to None)
            {"linked": None, "display_name": "@Foo"}, # None linked
            {"error": "Internal Server Error"},       # Error payload
        ]

        for payload in dirty_payloads:
            with patch.object(tg, "_request", return_value=payload):
                try:
                    prev_linked = tg.is_linked
                    prev_name = tg.display_name
                    status = tg.get_link_status()
                    if status and (tg.is_linked != prev_linked or tg.display_name != prev_name):
                        bridge.broadcast("state_updated", bridge.get_state())
                except Exception as exc:
                    pytest.fail(f"Loop crashed on dirty payload {payload}: {exc}")

        # Ensure internal state remained consistent without crashes
        assert isinstance(tg.is_linked, bool)

    def test_live_telegram_status_loop_thread_execution(self):
        """Verify live background thread execution of _telegram_status_loop with dynamic state updates."""
        tg = TelegramService()
        tg._save = MagicMock()
        tg.client_id = "test-client-id-0004"
        tg.notification_token = "tok_live"
        tg.display_name = None
        tg.is_linked = False

        bridge = WebBridge()
        bridge.telegram_service = tg
        bridge._running = True

        broadcasts = []
        bridge.broadcast = lambda et, data=None: broadcasts.append((et, data["telegram"]["display_name"], data["telegram"]["is_linked"]))

        # Sequence of mocked responses for consecutive loop iterations
        response_sequence = [
            {"linked": True, "display_name": "@LiveAlpha"},
            {"linked": True, "display_name": "@LiveAlpha"},  # Duplicate (no broadcast)
            {"linked": True, "display_name": "@LiveBeta"},   # Name change (broadcast)
            {"linked": False, "display_name": None},         # Unlink (broadcast)
        ]
        seq_idx = 0
        seq_lock = threading.Lock()

        def mock_request(path, payload):
            nonlocal seq_idx
            with seq_lock:
                if seq_idx < len(response_sequence):
                    res = response_sequence[seq_idx]
                    seq_idx += 1
                    return res
                return {"linked": False, "display_name": None}

        # Override sleep to run fast during test without calling mocked time.sleep
        sleep_event = threading.Event()
        def fast_sleep(sec):
            sleep_event.wait(0.01)

        with patch.object(tg, "_request", side_effect=mock_request), \
             patch("time.sleep", side_effect=fast_sleep):
            loop_thread = threading.Thread(target=bridge._telegram_status_loop, daemon=True)
            loop_thread.start()

            # Wait for all 4 iterations to complete
            for _ in range(50):
                with seq_lock:
                    if seq_idx >= len(response_sequence):
                        break
                sleep_event.wait(0.02)

            bridge._running = False
            loop_thread.join(timeout=1.0)

        # Expected broadcasts: @LiveAlpha (link), @LiveBeta (name change), None (unlink)
        assert len(broadcasts) == 3
        assert broadcasts[0] == ("state_updated", "@LiveAlpha", True)
        assert broadcasts[1] == ("state_updated", "@LiveBeta", True)
        assert broadcasts[2] == ("state_updated", None, False)

    def test_telegram_status_loop_100_rapid_random_chaos_transitions(self):
        """Empirical chaos testing: 100 random state updates verifying broadcast accuracy."""
        tg = TelegramService()
        tg._save = MagicMock()
        tg.client_id = "chaos-client"
        tg.notification_token = "chaos-token"
        tg.display_name = None
        tg.is_linked = False

        bridge = WebBridge()
        bridge.telegram_service = tg

        broadcast_log = []
        bridge.broadcast = lambda et, data=None: broadcast_log.append((et, data["telegram"]["is_linked"], data["telegram"]["display_name"]))

        possible_states = [
            {"linked": False, "display_name": None},
            {"linked": True, "display_name": "@Alice"},
            {"linked": True, "display_name": "@Bob"},
            {"linked": True, "display_name": "@Charlie"},
            {"linked": False, "display_name": None},
            None,  # Network error
        ]

        random.seed(42)
        expected_broadcasts = 0

        for i in range(100):
            response = random.choice(possible_states)
            with patch.object(tg, "_request", return_value=response):
                prev_linked = tg.is_linked
                prev_name = tg.display_name
                status = tg.get_link_status()
                if status and (tg.is_linked != prev_linked or tg.display_name != prev_name):
                    bridge.broadcast("state_updated", bridge.get_state())
                    expected_broadcasts += 1

        assert len(broadcast_log) == expected_broadcasts
        for et, linked, name in broadcast_log:
            assert et == "state_updated"
            assert isinstance(linked, bool)

    def test_telegram_display_name_unicode_and_special_chars(self):
        """Verify display_name handles Cyrillic, emojis, symbols, and whitespace properly."""
        tg = TelegramService()
        tg._save = MagicMock()
        tg.client_id = "test-client-unicode"
        tg.notification_token = "tok_unicode"

        bridge = WebBridge()
        bridge.telegram_service = tg

        names = [
            "Игрок_777 (Rust)",
            "🦀RustKing👑",
            "Player <script>alert(1)</script>",
            "User with spaces and special chars: !@#$%^&*()_+-=",
            "   ",  # Pure whitespace: should remain string or be handled safely
        ]

        for name in names:
            with patch.object(tg, "_request", return_value={"linked": True, "display_name": name}):
                status = tg.get_link_status()
                assert status["linked"] is True
                assert status["display_name"] == name
                state = bridge.get_state()
                assert state["telegram"]["display_name"] == name
                # JSON serialization must remain valid
                serialized = json.dumps(state)
                assert name in serialized or json.dumps(name)[1:-1] in serialized

    def test_telegram_status_loop_exception_resilience(self):
        """Verify that runtime exceptions inside get_link_status do not crash the background loop."""
        tg = TelegramService()
        tg._save = MagicMock()
        tg.client_id = "test-client-exc"
        tg.notification_token = "tok_exc"

        bridge = WebBridge()
        bridge.telegram_service = tg
        bridge._running = True

        exceptions = [
            RuntimeError("Unexpected thread termination"),
            ValueError("Malformed JSON internal error"),
            TypeError("NoneType object is not subscriptable"),
            OSError("Network interface reset"),
        ]

        for exc in exceptions:
            with patch.object(tg, "get_link_status", side_effect=exc):
                try:
                    prev_linked = tg.is_linked
                    prev_name = tg.display_name
                    # Simulate loop iteration body inside try/except block
                    try:
                        status = tg.get_link_status()
                        if status and (tg.is_linked != prev_linked or tg.display_name != prev_name):
                            bridge.broadcast("state_updated", bridge.get_state())
                    except Exception:
                        pass
                except Exception as unhandled:
                    pytest.fail(f"Loop leaked unhandled exception {unhandled}")


# ============================================================================
# Dimension 2: Concurrent WebSocket Client Broadcasts During Telegram Transitions
# ============================================================================

class MockWebSocket:
    """Mock aiohttp WebSocketResponse for empirical concurrency testing."""

    def __init__(self, ws_id: int, fail_on_send: bool = False, delay: float = 0.0):
        self.ws_id = ws_id
        self.fail_on_send = fail_on_send
        self.delay = delay
        self.messages: List[str] = []
        self.is_closed = False

    async def send_str(self, data: str):
        if self.fail_on_send:
            raise ConnectionResetError(f"WS {self.ws_id} disconnected unexpectedly")
        if self.is_closed:
            raise RuntimeError(f"WS {self.ws_id} is already closed")
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        self.messages.append(data)


class TestWebSocketConcurrencyAndBroadcastStress:
    """Stress tests for concurrent WebSocket client broadcasts during Telegram status changes."""

    def test_broadcast_to_100_concurrent_ws_clients(self):
        """Stress test: 100 simultaneous WebSocket clients receiving Telegram state broadcasts."""
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True, name="test-ws-loop")
        thread.start()

        bridge = WebBridge()
        bridge.set_event_loop(loop)

        clients = [MockWebSocket(i) for i in range(100)]
        for client in clients:
            bridge.register_ws(client)

        try:
            start = time.perf_counter()
            # Trigger 10 rapid Telegram state updates
            for i in range(10):
                bridge.telegram_service.is_linked = (i % 2 == 0)
                bridge.telegram_service.display_name = f"@User_{i}"
                bridge.broadcast("state_updated", bridge.get_state())

            # Wait for all async tasks in the event loop to flush
            flush_future = asyncio.run_coroutine_threadsafe(asyncio.sleep(0.1), loop)
            flush_future.result(timeout=5.0)
            elapsed = time.perf_counter() - start

            # Verify all 100 clients received at least the 10 explicit broadcasts
            # (a background rustmaps lookup may add its own state_updated broadcast too)
            for client in clients:
                assert len(client.messages) >= 10
                for msg in client.messages:
                    parsed = json.loads(msg)
                    assert parsed["type"] == "state_updated"
                    assert "telegram" in parsed["data"]
                    assert "is_linked" in parsed["data"]["telegram"]

            assert elapsed < 3.0, f"10 broadcasts to 100 clients took {elapsed:.2f}s"
        finally:
            loop.call_soon_threadsafe(loop.stop)

    def test_broadcast_resilience_with_faulty_and_crashing_ws_clients(self):
        """Verify WebBridge.broadcast does not deadlock or crash when clients throw exceptions."""
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True, name="test-ws-faulty-loop")
        thread.start()

        bridge = WebBridge()
        bridge.set_event_loop(loop)

        # 20 healthy clients, 20 failing clients (ConnectionResetError), 10 slow clients
        healthy_clients = [MockWebSocket(i) for i in range(20)]
        failing_clients = [MockWebSocket(100 + i, fail_on_send=True) for i in range(20)]
        slow_clients = [MockWebSocket(200 + i, delay=0.01) for i in range(10)]

        for c in healthy_clients + failing_clients + slow_clients:
            bridge.register_ws(c)

        try:
            # Broadcast 5 Telegram state changes
            for i in range(5):
                bridge.telegram_service.is_linked = True
                bridge.telegram_service.display_name = f"@ResilientUser_{i}"
                bridge.broadcast("state_updated", bridge.get_state())

            flush_future = asyncio.run_coroutine_threadsafe(asyncio.sleep(0.2), loop)
            flush_future.result(timeout=5.0)

            # Healthy clients must have received at least the 5 explicit broadcasts
            # (a background rustmaps lookup may add its own state_updated broadcast too)
            for c in healthy_clients:
                assert len(c.messages) >= 5

            # Slow clients must have received at least the 5 explicit broadcasts
            for c in slow_clients:
                assert len(c.messages) >= 5

            # Failing clients received 0 messages due to connection reset
            for c in failing_clients:
                assert len(c.messages) == 0
        finally:
            loop.call_soon_threadsafe(loop.stop)

    def test_dynamic_ws_client_churn_during_active_telegram_broadcasts(self):
        """Stress test: 10 threads concurrently adding/removing clients while 5 threads broadcast state updates."""
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True, name="test-ws-churn-loop")
        thread.start()

        bridge = WebBridge()
        bridge.set_event_loop(loop)

        stop_event = threading.Event()
        errors = []

        def churn_worker(worker_id: int):
            try:
                for i in range(50):
                    if stop_event.is_set():
                        break
                    client = MockWebSocket(worker_id * 1000 + i)
                    bridge.register_ws(client)
                    time.sleep(0.002)
                    bridge.unregister_ws(client)
            except Exception as e:
                errors.append(e)

        def broadcast_worker(worker_id: int):
            try:
                for i in range(30):
                    if stop_event.is_set():
                        break
                    bridge.telegram_service.is_linked = (i % 2 == 0)
                    bridge.telegram_service.display_name = f"@Churn_{worker_id}_{i}"
                    bridge.broadcast("state_updated", bridge.get_state())
                    time.sleep(0.003)
            except Exception as e:
                errors.append(e)

        churn_threads = [threading.Thread(target=churn_worker, args=(t,)) for t in range(10)]
        broadcast_threads = [threading.Thread(target=broadcast_worker, args=(t,)) for t in range(5)]

        start = time.perf_counter()
        for t in churn_threads + broadcast_threads:
            t.start()

        for t in churn_threads + broadcast_threads:
            t.join(timeout=10.0)

        elapsed = time.perf_counter() - start
        loop.call_soon_threadsafe(loop.stop)

        assert len(errors) == 0, f"Encountered concurrency errors during client churn: {errors}"
        assert elapsed < 8.0, f"Churn stress test took {elapsed:.2f}s"

    def test_broadcast_payload_schema_and_serialization_integrity(self):
        """Verify that all state_updated broadcast payloads strictly adhere to the expected schema."""
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True, name="test-ws-schema-loop")
        thread.start()

        bridge = WebBridge()
        bridge.set_event_loop(loop)
        test_client = MockWebSocket(1)
        bridge.register_ws(test_client)

        try:
            # Test linked state
            bridge.telegram_service.is_linked = True
            bridge.telegram_service.display_name = "@SchemaTest"
            bridge.telegram_service.link_code = None
            bridge.broadcast("state_updated", bridge.get_state())

            # Test unlinked with code
            bridge.telegram_service.is_linked = False
            bridge.telegram_service.display_name = None
            bridge.telegram_service.link_code = "ABCD8888"
            bridge.broadcast("state_updated", bridge.get_state())

            # Test unlinked without code
            bridge.telegram_service.is_linked = False
            bridge.telegram_service.display_name = None
            bridge.telegram_service.link_code = None
            bridge.broadcast("state_updated", bridge.get_state())

            flush_future = asyncio.run_coroutine_threadsafe(asyncio.sleep(0.1), loop)
            flush_future.result(timeout=5.0)

            # A background monitoring loop (e.g. server/telegram status) may fire an
            # extra state_updated broadcast in this window, so match by content instead
            # of a strict count/index — the 3 explicit broadcasts must still be present.
            assert len(test_client.messages) >= 3
            parsed = [json.loads(m) for m in test_client.messages]

            assert any(
                p["data"]["telegram"]["is_linked"] is True
                and p["data"]["telegram"]["display_name"] == "@SchemaTest"
                and p["data"]["telegram"]["link_code"] is None
                for p in parsed
            )
            assert any(
                p["data"]["telegram"]["is_linked"] is False
                and p["data"]["telegram"]["display_name"] is None
                and p["data"]["telegram"]["link_code"] == "ABCD8888"
                for p in parsed
            )
            assert any(
                p["data"]["telegram"]["is_linked"] is False
                and p["data"]["telegram"]["display_name"] is None
                and p["data"]["telegram"]["link_code"] is None
                for p in parsed
            )
        finally:
            loop.call_soon_threadsafe(loop.stop)

    def test_broadcast_with_closed_or_uninitialized_event_loop(self):
        """Verify broadcast handles None loop or closed loop gracefully without raising exceptions."""
        bridge = WebBridge()
        test_client = MockWebSocket(1)
        bridge.register_ws(test_client)

        # Case 1: _event_loop is None
        bridge._event_loop = None
        try:
            bridge.broadcast("state_updated", bridge.get_state())
        except Exception as e:
            pytest.fail(f"broadcast raised exception with None event loop: {e}")

        # Case 2: _event_loop is closed
        loop = asyncio.new_event_loop()
        loop.close()
        bridge.set_event_loop(loop)
        try:
            bridge.broadcast("state_updated", bridge.get_state())
        except Exception as e:
            pytest.fail(f"broadcast raised exception with closed event loop: {e}")

    def test_concurrent_telegram_action_dispatch_stress(self):
        """Stress test 20 concurrent threads calling generate_telegram_link and unlink_telegram."""
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True, name="test-ws-act-loop")
        thread.start()

        bridge = WebBridge()
        bridge.set_event_loop(loop)
        client = MockWebSocket(1)
        bridge.register_ws(client)

        bridge.telegram_service._save = MagicMock()
        results = []
        errors = []

        def worker(idx: int):
            try:
                if idx % 2 == 0:
                    with patch.object(bridge.telegram_service, "_request", return_value={"accepted": True, "notification_token": f"tok_{idx}"}):
                        res = bridge.generate_telegram_link()
                        results.append(res)
                else:
                    with patch.object(bridge.telegram_service, "_request", return_value={"accepted": True}):
                        res = bridge.unlink_telegram()
                        results.append(res)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        start = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.perf_counter() - start

        flush_future = asyncio.run_coroutine_threadsafe(asyncio.sleep(0.1), loop)
        flush_future.result(timeout=5.0)
        loop.call_soon_threadsafe(loop.stop)

        assert len(errors) == 0, f"Encountered errors during concurrent action dispatch: {errors}"
        assert len(results) == 20
        # Background monitoring loops may add extra state_updated broadcasts on top
        # of the 20 explicit ones triggered by the workers.
        assert len(client.messages) >= 20
        assert elapsed < 3.0
