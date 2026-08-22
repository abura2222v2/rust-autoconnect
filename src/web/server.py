# -*- coding: utf-8 -*-
"""Aiohttp Web Server for Rust AutoConnect Web Desktop Application."""
import asyncio
import json
import logging
import os
import secrets
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, Tuple

import aiohttp
from aiohttp import web

from .bridge import web_bridge

STATIC_DIR = Path(__file__).parent / "static"

TOKEN_HEADER = "X-AutoConnect-Token"


@web.middleware
async def session_token_middleware(request: web.Request, handler):
    """Reject any /api/* request that doesn't carry this server instance's session token.

    Prevents a malicious page open in another browser tab from silently calling
    the local API (CSRF) — the token is only ever delivered inside index.html,
    which a cross-origin page cannot read due to the browser's same-origin policy.
    """
    if request.path.startswith("/api/"):
        token = request.headers.get(TOKEN_HEADER, "")
        if not token or not secrets.compare_digest(token, request.app["session_token"]):
            return web.json_response({"error": "forbidden"}, status=403)
    return await handler(request)


async def handle_index(request: web.Request) -> web.Response:
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return web.Response(text="index.html not found", status=404)
    html = index_file.read_text(encoding="utf-8")
    html = html.replace("__AC_TOKEN_VALUE__", request.app["session_token"])
    return web.Response(text=html, content_type="text/html")


async def handle_get_state(request: web.Request) -> web.Response:
    state = web_bridge.get_state()
    return web.json_response(state)


async def handle_connect(request: web.Request) -> web.Response:
    data = await request.json()
    ip = data.get("ip", "")
    res = web_bridge.connect_to_server(ip)
    return web.json_response(res)


async def handle_toggle_armed(request: web.Request) -> web.Response:
    data = await request.json()
    ip = data.get("ip", "")
    name = data.get("name", "")
    res = web_bridge.toggle_armed(ip, name)
    return web.json_response(res)


async def handle_disarm(request: web.Request) -> web.Response:
    res = web_bridge.disarm()
    return web.json_response(res)


async def handle_stop_connecting(request: web.Request) -> web.Response:
    res = web_bridge.stop_connecting()
    return web.json_response(res)


async def handle_toggle_favorite(request: web.Request) -> web.Response:
    data = await request.json()
    ip = data.get("ip", "")
    name = data.get("name", "")
    res = web_bridge.toggle_favorite(ip, name)
    return web.json_response(res)


async def handle_remove_server(request: web.Request) -> web.Response:
    data = await request.json()
    ip = data.get("ip", "")
    res = web_bridge.remove_server(ip)
    return web.json_response(res)


async def handle_set_column_widths(request: web.Request) -> web.Response:
    data = await request.json()
    widths = data.get("widths", {})
    res = web_bridge.set_column_widths(widths)
    return web.json_response(res)


async def handle_set_language(request: web.Request) -> web.Response:
    data = await request.json()
    lang = data.get("lang", "RU")
    res = web_bridge.set_language(lang)
    return web.json_response(res)


async def handle_update_setting(request: web.Request) -> web.Response:
    data = await request.json()
    key = data.get("key", "")
    val = data.get("value")
    res = web_bridge.update_setting(key, val)
    return web.json_response(res)


async def handle_import_servers(request: web.Request) -> web.Response:
    data = await request.json()
    content = data.get("content", "")
    is_json = bool(data.get("is_json", False))
    res = web_bridge.import_servers(content, is_json)
    return web.json_response(res)


async def handle_export_servers(request: web.Request) -> web.Response:
    text = web_bridge.export_servers()
    return web.Response(text=text, content_type="text/plain", headers={"Content-Disposition": 'attachment; filename="rust_servers.txt"'})


async def handle_benchmark_info(request: web.Request) -> web.Response:
    info = web_bridge.get_benchmark_info()
    return web.json_response(info)


async def handle_run_benchmark(request: web.Request) -> web.Response:
    res = web_bridge.run_benchmark()
    return web.json_response(res)


async def handle_leaderboard(request: web.Request) -> web.Response:
    board = web_bridge.get_leaderboard()
    return web.json_response(board)


async def handle_telegram_link(request: web.Request) -> web.Response:
    res = web_bridge.generate_telegram_link()
    return web.json_response(res)


async def handle_telegram_unlink(request: web.Request) -> web.Response:
    res = web_bridge.unlink_telegram()
    return web.json_response(res)


async def handle_get_logs(request: web.Request) -> web.Response:
    logs = web_bridge.get_logs()
    return web.json_response(logs)


async def handle_clear_logs(request: web.Request) -> web.Response:
    web_bridge.clear_logs()
    return web.json_response({"success": True})


def _is_allowed_origin(request: web.Request) -> bool:
    """A browser always sends a truthful Origin header; a non-browser client (or same-page
    same-origin requests in older browsers) may omit it, so absence is allowed too."""
    origin = request.headers.get("Origin")
    if not origin:
        return True
    port = request.url.port
    return origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")


async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    if not _is_allowed_origin(request):
        return web.Response(status=403, text="forbidden")

    ws = web.WebSocketResponse(heartbeat=25.0)
    await ws.prepare(request)

    web_bridge.register_ws(ws)
    # Send immediate state on connection
    try:
        await ws.send_str(json.dumps({"type": "init_state", "data": web_bridge.get_state()}))
    except Exception:
        pass

    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                    action = payload.get("action")
                    if action == "ping":
                        await ws.send_str(json.dumps({"type": "pong"}))
                except Exception:
                    pass
            elif msg.type == aiohttp.WSMsgType.ERROR:
                break
    finally:
        web_bridge.unregister_ws(ws)

    return ws


def find_free_port(preferred_port: int = 49200) -> int:
    for port in range(preferred_port, preferred_port + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return 0


def create_app() -> web.Application:
    app = web.Application(middlewares=[session_token_middleware])
    app["session_token"] = secrets.token_urlsafe(32)

    # REST APIs
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/state", handle_get_state)
    app.router.add_post("/api/connect", handle_connect)
    app.router.add_post("/api/toggle_armed", handle_toggle_armed)
    app.router.add_post("/api/disarm", handle_disarm)
    app.router.add_post("/api/stop_connecting", handle_stop_connecting)
    app.router.add_post("/api/toggle_favorite", handle_toggle_favorite)
    app.router.add_post("/api/remove_server", handle_remove_server)
    app.router.add_post("/api/col_widths", handle_set_column_widths)
    app.router.add_post("/api/language", handle_set_language)
    app.router.add_post("/api/setting", handle_update_setting)
    app.router.add_post("/api/import_servers", handle_import_servers)
    app.router.add_get("/api/export_servers", handle_export_servers)
    app.router.add_get("/api/benchmark_info", handle_benchmark_info)
    app.router.add_post("/api/run_benchmark", handle_run_benchmark)
    app.router.add_get("/api/leaderboard", handle_leaderboard)
    app.router.add_post("/api/telegram_link", handle_telegram_link)
    app.router.add_post("/api/telegram_unlink", handle_telegram_unlink)
    app.router.add_get("/api/logs", handle_get_logs)
    app.router.add_post("/api/clear_logs", handle_clear_logs)

    # WebSocket Real-Time Stream
    app.router.add_get("/ws", handle_ws)

    # Static assets
    if STATIC_DIR.exists():
        app.router.add_static("/static/", STATIC_DIR, show_index=False)

    return app


def launch_edge_app_mode(url: str, width: int = 1120, height: int = 760):
    """Launch Microsoft Edge in dedicated standalone desktop application mode."""
    edge_paths = [
        shutil.which("msedge"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
    ]

    edge_exe = next((p for p in edge_paths if p and os.path.exists(p)), None)
    if edge_exe:
        cmd = [
            edge_exe,
            f"--app={url}",
            f"--window-size={width},{height}",
            "--disable-extensions",
            "--disable-plugins",
            "--disable-features=Translate,TranslateUI",
            "--disable-translate",
            "--lang=ru",
            f"--user-data-dir={os.path.expandvars('%LOCALAPPDATA%\\RustAutoConnect\\edge_profile')}",
        ]
        try:
            return subprocess.Popen(cmd)
        except Exception:
            pass

    import webbrowser
    webbrowser.open(url)
    return None



def _create_tray_image():
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (64, 64), color=(233, 75, 22))
    draw = ImageDraw.Draw(image)
    draw.text((24, 22), "R", fill=(255, 255, 255))
    return image


def start_tray_icon(url: str):
    """Persistent system-tray icon so the app is reachable even if the Edge
    window was closed. Python cannot detect Edge's own minimize button (it's
    a separate process), so this is always-on rather than minimize-triggered."""
    try:
        import pystray
    except ImportError:
        return None

    def on_show(icon, item):
        launch_edge_app_mode(url)

    def on_quit(icon, item):
        icon.stop()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("Показать окно", on_show, default=True),
        pystray.MenuItem("Выйти", on_quit),
    )
    icon = pystray.Icon("RustAutoConnect", _create_tray_image(), "Rust AutoConnect", menu)
    icon.run_detached()
    return icon


def run_web_app(port: int = 0, open_window: bool = True):
    """Start local web server and launch native window."""
    if port == 0:
        port = find_free_port(49250)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    web_bridge.set_event_loop(loop)

    app = create_app()
    runner = web.AppRunner(app)
    loop.run_until_complete(runner.setup())
    site = web.TCPSite(runner, "127.0.0.1", port)
    loop.run_until_complete(site.start())

    url = f"http://127.0.0.1:{port}"
    web_bridge.log(f"Rust AutoConnect Web UI запущен на {url}", level="success")

    if open_window:
        threading.Thread(
            target=lambda: (time.sleep(0.5), launch_edge_app_mode(url)),
            daemon=True,
            name="launch-app-window",
        ).start()
        start_tray_icon(url)

    try:
        loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        loop.run_until_complete(runner.cleanup())
        loop.close()


def start_web_server(port: int = 0):
    """Run web server in background thread."""
    if port == 0:
        port = find_free_port(49250)

    t = threading.Thread(target=lambda: run_web_app(port=port, open_window=False), daemon=True, name="web-server-bg")
    t.start()
    return port
