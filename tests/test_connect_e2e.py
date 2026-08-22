"""Safe localhost integration: no Steam, RustClient, or real Player.log."""

import asyncio
from pathlib import Path

from src.core.a2s_client import A2SClient
from src.services.log_watcher import LogWatcher
from src.services.steam_service import build_connect_url
from tests.mock_a2s_server import MockA2SServer


def test_localhost_offline_online_two_confirmations_and_log_disconnect(tmp_path: Path):
    server = MockA2SServer(players=100, max_players=100)
    port = server.start()
    client = A2SClient(timeout=0.2, offsets=(0,))
    log_file = tmp_path / "Player.log"
    log_file.write_text("", encoding="utf-8")
    events, disconnects = [], []

    async def scenario():
        server.set_offline(True)
        assert not (await client.get_server_status("127.0.0.1", port)).alive
        server.set_offline(False)
        server.set_server_info(players=99, max_players=100)
        first = await client.get_server_status("127.0.0.1", port)
        second = await client.get_server_status("127.0.0.1", port)
        assert first.has_join_capacity and second.has_join_capacity

        watcher = LogWatcher(disconnects.append, lambda error: (_ for _ in ()).throw(AssertionError(error)), events.append, seek_end=False, target_log_path=log_file)
        watcher.start(loop=asyncio.get_running_loop())
        log_file.write_text("Client connected to 127.0.0.1:28015\nDisconnected\n", encoding="utf-8")
        for _ in range(20):
            if disconnects:
                break
            await asyncio.sleep(0.1)
        watcher.stop()

    try:
        asyncio.run(scenario())
    finally:
        server.stop()

    assert build_connect_url("127.0.0.1:28015") == "steam://run/252490//+connect 127.0.0.1:28015"
    assert any("Client connected" in event for event in events)
    assert disconnects == ["Disconnected"]


def test_localhost_full_server_is_not_ready_to_join():
    server = MockA2SServer(players=100, max_players=100)
    port = server.start()
    try:
        status = asyncio.run(A2SClient(timeout=0.2, offsets=(0,)).get_server_status("127.0.0.1", port))
    finally:
        server.stop()
    assert status.alive
    assert not status.has_join_capacity


def test_watcher_start_boundary_ignores_old_lines_and_keeps_immediate_new_lines(tmp_path: Path):
    log_file = tmp_path / "Player.log"
    log_file.write_text("Client connected to old.example:28015\n", encoding="utf-8")
    events = []

    async def scenario():
        watcher = LogWatcher(
            lambda _reason: None, lambda error: (_ for _ in ()).throw(AssertionError(error)),
            events.append, target_log_path=log_file, poll_interval=0.02,
        )
        watcher.capture_start_position()
        watcher.start(loop=asyncio.get_running_loop())
        with log_file.open("a", encoding="utf-8") as handle:
            handle.write("Client connected to 127.0.0.1:28015\n")
        for _ in range(20):
            if events:
                break
            await asyncio.sleep(0.02)
        watcher.stop()

    asyncio.run(scenario())
    assert events == ["Client connected to 127.0.0.1:28015"]
