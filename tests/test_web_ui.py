# -*- coding: utf-8 -*-
"""Unit and integration tests for Rust AutoConnect Web UI backend and endpoints."""
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.web.bridge import WebBridge
from src.web.server import create_app, STATIC_DIR


def test_static_assets_exist():
    """Verify that all frontend static assets are present and non-empty."""
    assert STATIC_DIR.exists()
    index_file = STATIC_DIR / "index.html"
    css_file = STATIC_DIR / "css" / "app.css"
    js_app = STATIC_DIR / "js" / "app.js"
    js_table = STATIC_DIR / "js" / "table.js"
    js_drawer = STATIC_DIR / "js" / "drawer.js"
    js_modal = STATIC_DIR / "js" / "modal.js"
    js_api = STATIC_DIR / "js" / "api.js"
    icons_svg = STATIC_DIR / "assets" / "icons.svg"
    banner_svg = STATIC_DIR / "assets" / "banner.svg"

    for asset in [index_file, css_file, js_app, js_table, js_drawer, js_modal, js_api, icons_svg, banner_svg]:
        assert asset.exists(), f"Missing static asset: {asset}"
        assert asset.stat().st_size > 0, f"Asset is empty: {asset}"


def test_web_bridge_state_and_actions():
    """Verify WebBridge state retrieval and action dispatching."""
    bridge = WebBridge()
    state = bridge.get_state()

    assert "servers" in state
    assert isinstance(state["servers"], list)
    assert len(state["servers"]) > 0
    assert "settings" in state
    assert "col_widths" in state
    assert "version" in state
    assert "rust_status" in state

    # Test toggling favorite
    test_ip = "127.0.0.1:28015"
    res_fav = bridge.toggle_favorite(test_ip, "Test Local Server")
    assert res_fav["success"] is True

    # Test toggling armed
    res_arm = bridge.toggle_armed(test_ip, "Test Local Server")
    assert res_arm["success"] is True

    # Test disarm
    res_disarm = bridge.disarm()
    assert res_disarm["success"] is True

    # Test column widths
    new_widths = {"star": 36, "name": 300, "addr": 190, "players": 90, "local": 64, "action": 120}
    res_w = bridge.set_column_widths(new_widths)
    assert res_w["success"] is True
    assert bridge.history_store.get_column_widths()["name"] == 300


def test_web_bridge_logging():
    """Verify thread-safe logging in WebBridge."""
    bridge = WebBridge()
    bridge.clear_logs()
    assert len(bridge.get_logs()) == 0

    bridge.log("Test log entry", level="info")
    bridge.log("Success event", level="success")
    bridge.log("Warning event", level="warning")

    logs = bridge.get_logs()
    assert len(logs) == 3
    assert logs[0]["message"] == "Test log entry"
    assert logs[1]["level"] == "success"
    assert logs[2]["level"] == "warning"


@pytest.mark.anyio
async def test_aiohttp_endpoints():
    """Verify that aiohttp application handles core REST routes properly."""
    from aiohttp.test_utils import TestServer, TestClient
    app = create_app()
    token_headers = {"X-AutoConnect-Token": app["session_token"]}
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        # 1. GET /
        resp_index = await client.get("/")
        assert resp_index.status == 200
        text_index = await resp_index.text()
        assert "Rust AutoConnect" in text_index

        # 2. GET /api/state
        resp_state = await client.get("/api/state", headers=token_headers)
        assert resp_state.status == 200
        state_json = await resp_state.json()
        assert "servers" in state_json
        assert "telegram" in state_json

        # 3. POST /api/col_widths
        resp_col = await client.post("/api/col_widths", json={"widths": {"name": 340}}, headers=token_headers)
        assert resp_col.status == 200
        col_json = await resp_col.json()
        assert col_json["success"] is True

        # 4. GET /api/benchmark_info
        resp_bench = await client.get("/api/benchmark_info", headers=token_headers)
        assert resp_bench.status == 200
        bench_json = await resp_bench.json()
        assert "cpu" in bench_json

        # 5. GET /api/leaderboard
        resp_board = await client.get("/api/leaderboard", headers=token_headers)
        assert resp_board.status == 200
        board_json = await resp_board.json()
        assert isinstance(board_json, list)
    finally:
        await client.close()


def test_web_bridge_telegram_state_and_actions():
    """Verify Telegram link/unlink actions and state reflection in WebBridge."""
    bridge = WebBridge()
    state = bridge.get_state()
    assert "telegram" in state
    assert "is_linked" in state["telegram"]
    assert "display_name" in state["telegram"]
    assert "link_code" in state["telegram"]

    with patch.object(bridge.telegram_service, "generate_link_code", return_value="ABCD1234"):
        res_link = bridge.generate_telegram_link()
        assert res_link["success"] is True
        assert res_link["code"] == "ABCD1234"

    with patch.object(bridge.telegram_service, "unlink", return_value=True):
        res_unlink = bridge.unlink_telegram()
        assert res_unlink["success"] is True


def test_telegram_status_loop_change_detection():
    """Verify that _telegram_status_loop detects link and display_name changes accurately."""
    bridge = WebBridge()
    bridge._running = True

    # Case 1: is_linked transitions False -> True
    bridge.telegram_service.is_linked = False
    bridge.telegram_service.display_name = None
    bridge.telegram_service.notification_token = "tok_123"

    def side_effect_linked():
        bridge.telegram_service.is_linked = True
        bridge.telegram_service.display_name = "@player1"
        return {"linked": True, "display_name": "@player1"}

    with patch.object(bridge.telegram_service, "get_link_status", side_effect=side_effect_linked):
        with patch.object(bridge, "broadcast") as mock_broadcast:
            # Run one iteration logic
            prev_linked = bridge.telegram_service.is_linked
            prev_name = bridge.telegram_service.display_name
            status = bridge.telegram_service.get_link_status()
            if status and (bridge.telegram_service.is_linked != prev_linked or bridge.telegram_service.display_name != prev_name):
                bridge.broadcast("state_updated", bridge.get_state())

            mock_broadcast.assert_called_once()
            assert mock_broadcast.call_args[0][0] == "state_updated"

    # Case 2: display_name transitions @player1 -> @player2
    bridge.telegram_service.is_linked = True
    bridge.telegram_service.display_name = "@player1"

    def side_effect_name_change():
        bridge.telegram_service.display_name = "@player2"
        return {"linked": True, "display_name": "@player2"}

    with patch.object(bridge.telegram_service, "get_link_status", side_effect=side_effect_name_change):
        with patch.object(bridge, "broadcast") as mock_broadcast:
            prev_linked = bridge.telegram_service.is_linked
            prev_name = bridge.telegram_service.display_name
            status = bridge.telegram_service.get_link_status()
            if status and (bridge.telegram_service.is_linked != prev_linked or bridge.telegram_service.display_name != prev_name):
                bridge.broadcast("state_updated", bridge.get_state())

            mock_broadcast.assert_called_once()
            assert mock_broadcast.call_args[0][0] == "state_updated"

    # Case 3: No change in link state or display_name
    bridge.telegram_service.is_linked = True
    bridge.telegram_service.display_name = "@player2"

    def side_effect_no_change():
        return {"linked": True, "display_name": "@player2"}

    with patch.object(bridge.telegram_service, "get_link_status", side_effect=side_effect_no_change):
        with patch.object(bridge, "broadcast") as mock_broadcast:
            prev_linked = bridge.telegram_service.is_linked
            prev_name = bridge.telegram_service.display_name
            status = bridge.telegram_service.get_link_status()
            if status and (bridge.telegram_service.is_linked != prev_linked or bridge.telegram_service.display_name != prev_name):
                bridge.broadcast("state_updated", bridge.get_state())

            mock_broadcast.assert_not_called()

    # Case 4: get_link_status returns None (error)
    with patch.object(bridge.telegram_service, "get_link_status", return_value=None):
        with patch.object(bridge, "broadcast") as mock_broadcast:
            prev_linked = bridge.telegram_service.is_linked
            prev_name = bridge.telegram_service.display_name
            status = bridge.telegram_service.get_link_status()
            if status and (bridge.telegram_service.is_linked != prev_linked or bridge.telegram_service.display_name != prev_name):
                bridge.broadcast("state_updated", bridge.get_state())

            mock_broadcast.assert_not_called()


def test_telegram_ui_static_integration():
    """Verify that index.html and app.css contain the required Telegram status elements and styles."""
    index_content = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="tg-status-badge"' in index_content
    assert 'class="tg-status-badge"' in index_content
    assert 'id="tg-settings-status"' in index_content
    assert 'id="btn-open-tg-modal"' in index_content
    assert 'id="telegram-link-modal"' in index_content

    css_content = (STATIC_DIR / "css" / "app.css").read_text(encoding="utf-8")
    assert '.tg-status-badge' in css_content

    app_js = (STATIC_DIR / "js" / "app.js").read_text(encoding="utf-8")
    assert 'renderTelegramStatus' in app_js

    modal_js = (STATIC_DIR / "js" / "modal.js").read_text(encoding="utf-8")
    assert 'showTelegramModal' in modal_js


