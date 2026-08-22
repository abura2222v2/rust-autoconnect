# -*- coding: utf-8 -*-
import customtkinter as ctk
import tkinter as tk
import queue
import threading
import pystray
import time
import webbrowser
import io
import math
import hashlib
import urllib.request
from urllib.parse import urlparse
from types import SimpleNamespace
from PIL import Image, ImageDraw, ImageFilter
from typing import Optional, Dict, Any, List

from .tooltip import ToolTip
from ..core.i18n import i18n, I18nManager
from ..core.history_store import history_store, HistoryStore
from ..services.telegram_service import telegram_service

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

COLORS = {
    "canvas": "#12151B",
    "sidebar": "#0F1217",
    "surface": "#161921",
    "surface_card": "#1A1E27",
    "surface_alt": "#1E232E",
    "surface_hover": "#232A37",
    "input_bg": "#11141A",
    "border": "#242B39",
    "border_subtle": "#1B212C",
    "text": "#FFFFFF",
    "text_secondary": "#CAD1DB",
    "muted": "#7E8795",
    "accent": "#E94B16",
    "accent_hover": "#FF5722",
    "danger": "#EF4444",
    "success": "#2ECC71",
    "warning": "#F1C40F",
    "divider": "#242B39",
    "divider_subtle": "#1B212C",
    "divider_hover": "#E94B16",
}

DEFAULT_COL_WIDTHS = {
    "star": 32,
    "name": 260,
    "addr": 180,
    "players": 76,
    "local": 56,
    "action": 110,
}

MIN_WIDTHS = {
    "star": 32,
    "name": 140,
    "addr": 130,
    "players": 60,
    "local": 50,
    "action": 90,
}

POPULAR_SERVERS_DATA = {
    "198.244.168.34:28015": {
        "name": "Rustafied.com - EU Small - Friday",
        "ip": "198.244.168.34:28015",
        "players": 97,
        "max_players": 150,
        "map_name": "Procedural Map",
        "map_size": 4000,
        "description": "Классический Rust сервер от Rustafied с привилегиями без оплаты. Еженедельный вайп по пятницам. Активное комьюнити, баланс между выживанием и PvP. Удачи и приятной игры!",
        "website": "https://rustafied.com",
        "discord": "https://discord.gg/rustafied",
        "rules": "https://rustafied.com/rules",
        "rustmaps_url": "https://rustmaps.com",
    },
    "198.244.168.35:28015": {
        "name": "Rustopia.co - EU Main",
        "ip": "198.244.168.35:28015",
        "players": 188,
        "max_players": 300,
        "map_name": "Procedural Map",
        "map_size": 4250,
        "description": "Официальный сервер Rustopia EU Main. Вайп каждый четверг в 21:00 МСК. Высокий FPS, активная администрация, лучшая защита от читеров.",
        "website": "https://rustopia.co",
        "discord": "https://discord.gg/rustopia",
        "rules": "https://rustopia.co/rules",
        "rustmaps_url": "https://rustmaps.com",
    },
    "198.244.168.36:28015": {
        "name": "Intoxicated EU Main",
        "ip": "198.244.168.36:28015",
        "players": 142,
        "max_players": 250,
        "map_name": "Procedural Map",
        "map_size": 4000,
        "description": "Intoxicated Gaming Rust Server. Еженедельный вайп карты, двухнедельный вайп чертежей. Высокая производительность и сбалансированный геймплей.",
        "website": "https://intoxicated.games",
        "discord": "https://discord.gg/intoxicated",
        "rules": "https://intoxicated.games/rules",
        "rustmaps_url": "https://rustmaps.com",
    },
    "198.244.168.37:28015": {
        "name": "Rustafied.com - US Main",
        "ip": "198.244.168.37:28015",
        "players": 201,
        "max_players": 300,
        "map_name": "Procedural Map",
        "map_size": 4500,
        "description": "Rustafied US Main server. Weekly wipes every Thursday at 3 PM EST. Active community and competitive vanilla gameplay.",
        "website": "https://rustafied.com",
        "discord": "https://discord.gg/rustafied",
        "rules": "https://rustafied.com/rules",
        "rustmaps_url": "https://rustmaps.com",
    },
    "198.244.168.38:28015": {
        "name": "Rustopia.co - US Long",
        "ip": "198.244.168.38:28015",
        "players": 87,
        "max_players": 200,
        "map_name": "Procedural Map",
        "map_size": 4000,
        "description": "Rustopia US Long server. Bi-weekly wipes for dedicated survivalists. Stable vanilla settings.",
        "website": "https://rustopia.co",
        "discord": "https://discord.gg/rustopia",
        "rules": "https://rustopia.co/rules",
        "rustmaps_url": "https://rustmaps.com",
    },
    "198.244.168.39:28015": {
        "name": "Rustoria.co - EU Main",
        "ip": "198.244.168.39:28015",
        "players": 156,
        "max_players": 250,
        "map_name": "Procedural Map",
        "map_size": 4250,
        "description": "Rustoria EU Main vanilla server. No lag, high-tickrate hardware, 24/7 moderation.",
        "website": "https://rustoria.co",
        "discord": "https://discord.gg/rustoria",
        "rules": "https://rustoria.co/rules",
        "rustmaps_url": "https://rustmaps.com",
    },
    "198.244.168.40:28015": {
        "name": "Rustified - EU Trio",
        "ip": "198.244.168.40:28015",
        "players": 64,
        "max_players": 150,
        "map_name": "Procedural Map",
        "map_size": 3750,
        "description": "Trio only server (Max 3 players per team/base). Strict team limit enforcement and weekly wipes.",
        "website": "https://rustified.net",
        "discord": "https://discord.gg/rustified",
        "rules": "https://rustified.net/rules",
        "rustmaps_url": "https://rustmaps.com",
    },
    "198.244.168.41:28015": {
        "name": "Facepunch 2",
        "ip": "198.244.168.41:28015",
        "players": 12,
        "max_players": 150,
        "map_name": "Procedural Map",
        "map_size": 4000,
        "description": "Official Facepunch Server. Monthly force wipe with official vanilla rules.",
        "website": "https://facepunch.com",
        "discord": "https://discord.gg/facepunch",
        "rules": "https://facepunch.com/rules",
        "rustmaps_url": "https://rustmaps.com",
    },
    "198.244.168.42:28015": {
        "name": "Rustafied.com - AU Main",
        "ip": "198.244.168.42:28015",
        "players": 93,
        "max_players": 200,
        "map_name": "Procedural Map",
        "map_size": 4000,
        "description": "Official Australian Rustafied server. High performance server located in Sydney.",
        "website": "https://rustafied.com",
        "discord": "https://discord.gg/rustafied",
        "rules": "https://rustafied.com/rules",
        "rustmaps_url": "https://rustmaps.com",
    },
    "198.244.168.43:28015": {
        "name": "Rustopia.co - EU Trio",
        "ip": "198.244.168.43:28015",
        "players": 58,
        "max_players": 150,
        "map_name": "Procedural Map",
        "map_size": 3500,
        "description": "Rustopia Trio 3-max vanilla experience. Weekly map wipes on Fridays.",
        "website": "https://rustopia.co",
        "discord": "https://discord.gg/rustopia",
        "rules": "https://rustopia.co/rules",
        "rustmaps_url": "https://rustmaps.com",
    },
    "193.25.252.119:28015": {
        "name": "RustVikings | Solo/Duo | Wednesdays | FULLWIPE",
        "ip": "193.25.252.119:28015",
        "players": 148,
        "max_players": 200,
        "map_name": "Procedural Map",
        "map_size": 4000,
        "description": "RustVikings Solo/Duo weekly server. Fast gathering, balanced loot tables and 24/7 active admin team.",
        "website": "https://rustvikings.com",
        "discord": "https://discord.gg/rustvikings",
        "rules": "https://rustvikings.com/rules",
        "rustmaps_url": "https://rustmaps.com",
    },
    "194.54.88.101:28024": {
        "name": "Survivors.gg #5 [ 2x Solo/Duo/Trio ] FULLWIPED",
        "ip": "194.54.88.101:28024",
        "players": 192,
        "max_players": 250,
        "map_name": "Barren",
        "map_size": 3750,
        "description": "Survivors.gg high performance 2x vanilla server. Low ping, DDoS protection and weekly wipes.",
        "website": "https://survivors.gg",
        "discord": "https://discord.gg/survivors",
        "rules": "https://survivors.gg/rules",
        "rustmaps_url": "https://rustmaps.com",
    },
    "195.60.166.73:28015": {
        "name": "Repulsion - 2x Solo/Duo/Trio | FULLWIPE",
        "ip": "195.60.166.73:28015",
        "players": 165,
        "max_players": 200,
        "map_name": "Procedural Map",
        "map_size": 4000,
        "description": "Repulsion 2x Vanilla experience with shared blueprints and active anti-cheat monitoring.",
        "website": "https://repulsion.gg",
        "discord": "https://discord.gg/repulsion",
        "rules": "https://repulsion.gg/rules",
        "rustmaps_url": "https://rustmaps.com",
    },
    "64.40.9.41:28015": {
        "name": "Rustafied.com - EU Small - Friday",
        "ip": "64.40.9.41:28015",
        "players": 97,
        "max_players": 150,
        "map_name": "Procedural Map",
        "map_size": 4000,
        "description": "Классический Rust сервер от Rustafied с привилегиями без оплаты. Еженедельный вайп по пятницам.",
        "website": "https://rustafied.com",
        "discord": "https://discord.gg/rustafied",
        "rules": "https://rustafied.com/rules",
        "rustmaps_url": "https://rustmaps.com",
    },
    "151.242.106.41:28010": {
        "name": "WARBANDITS.GG EU 2X |Solo/Duo|X2 JUST WIPED",
        "ip": "151.242.106.41:28010",
        "players": 210,
        "max_players": 250,
        "map_name": "Procedural Map",
        "map_size": 4250,
        "description": "Warbandits 2x Main EU server. High tickrate, custom monuments and active community.",
        "website": "https://warbandits.gg",
        "discord": "https://discord.gg/warbandits",
        "rules": "https://warbandits.gg/rules",
        "rustmaps_url": "https://rustmaps.com",
    },
    "178.32.124.50:28010": {
        "name": "Rusticated.com - EU Trio Monday",
        "ip": "178.32.124.50:28010",
        "players": 123,
        "max_players": 200,
        "map_name": "Procedural Map",
        "map_size": 4000,
        "description": "Rusticated EU Trio Monday server. No alliance, strict trio limit.",
        "website": "https://rusticated.com",
        "discord": "https://discord.gg/rusticated",
        "rules": "https://rusticated.com/rules",
        "rustmaps_url": "https://rustmaps.com",
    },
    "185.38.149.20:28015": {
        "name": "Rustafied.com - EU Small Monday",
        "ip": "185.38.149.20:28015",
        "players": 121,
        "max_players": 200,
        "map_name": "Procedural Map",
        "map_size": 4000,
        "description": "Rustafied EU Small Monday. Official vanilla server with Monday wipe cycle.",
        "website": "https://rustafied.com",
        "discord": "https://discord.gg/rustafied",
        "rules": "https://rustafied.com/rules",
        "rustmaps_url": "https://rustmaps.com",
    },
    "127.0.0.1:28015": {
        "name": "Localhost Test Server",
        "ip": "127.0.0.1:28015",
        "players": 1,
        "max_players": 100,
        "map_name": "Procedural Map",
        "map_size": 3000,
        "description": "Локальный тестовый сервер Rust для проверки скриптов и плагинов.",
        "website": "https://rust.facepunch.com",
        "discord": "https://discord.gg/rust",
        "rules": "https://rust.facepunch.com",
        "rustmaps_url": "https://rustmaps.com",
    },
}

DOMAIN_TO_IP_FALLBACK = {
    "eu-trio-mon.rusticated.com:28010": ("Rusticated.com - EU Trio Monday", "178.32.124.50:28010"),
    "eu-trio-mon.rusticated.com": ("Rusticated.com - EU Trio Monday", "178.32.124.50:28010"),
    "eusmallmonday.rustafied.com:28015": ("Rustafied.com - EU Small Monday", "185.38.149.20:28015"),
    "eusmallmonday.rustafied.com": ("Rustafied.com - EU Small Monday", "185.38.149.20:28015"),
    "127.0.0.1": ("Localhost Test Server", "127.0.0.1:28015"),
}


def _get_server_metadata(ip: str, name: str = "") -> dict:
    if ip in DOMAIN_TO_IP_FALLBACK:
        def_name, real_ip = DOMAIN_TO_IP_FALLBACK[ip]
        if not name or name == ip:
            name = def_name
        ip = real_ip

    if ip in POPULAR_SERVERS_DATA:
        data = dict(POPULAR_SERVERS_DATA[ip])
        if name and name != ip:
            data["name"] = name
        return data

    for key, data in POPULAR_SERVERS_DATA.items():
        if key in ip or (name and name.lower() in data["name"].lower()):
            res = dict(data)
            if name and name != ip:
                res["name"] = name
            return res

    h = int(hashlib.md5(ip.encode()).hexdigest(), 16)
    players = 30 + (h % 160)
    max_players = 150 if players <= 120 else (200 if players <= 170 else 250)
    return {
        "name": name or ip,
        "ip": ip,
        "players": players,
        "max_players": max_players,
        "map_name": "Procedural Map",
        "map_size": 4000,
        "description": f"Rust сервер {name or ip}. Подключайтесь и приятной игры!",
        "website": "https://rustmaps.com",
        "discord": "https://discord.gg",
        "rules": "https://rust.facepunch.com",
        "rustmaps_url": "https://rustmaps.com",
    }


def _draw_icon(kind: str, color: str, size: int = 32) -> Image.Image:
    scale = 4
    rs = size * scale
    image = Image.new("RGBA", (rs, rs), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    stroke = max(2 * scale, rs // 14)
    inset = max(3 * scale, rs // 7)

    if kind.startswith("star"):
        points = [
            (rs // 2, inset),
            (rs * 58 // 100, rs * 38 // 100),
            (rs - inset, rs * 40 // 100),
            (rs * 66 // 100, rs * 60 // 100),
            (rs * 74 // 100, rs - inset),
            (rs // 2, rs * 72 // 100),
            (rs * 26 // 100, rs - inset),
            (rs * 34 // 100, rs * 60 // 100),
            (inset, rs * 40 // 100),
            (rs * 42 // 100, rs * 38 // 100),
        ]
        if kind == "star_filled":
            draw.polygon(points, fill=color)
        else:
            draw.line(points + [points[0]], fill=color, width=stroke, joint="curve")

    elif kind in ("nav_home", "home"):
        draw.polygon([(rs // 2, inset), (rs - inset, rs * 45 // 100), (inset, rs * 45 // 100)], fill=color)
        draw.rectangle((rs * 24 // 100, rs * 42 // 100, rs * 76 // 100, rs - inset), fill=color)
        draw.rectangle((rs * 42 // 100, rs * 58 // 100, rs * 58 // 100, rs - inset), fill=COLORS["canvas"])

    elif kind in ("nav_bench", "bench"):
        bar_w = rs * 18 // 100
        draw.rounded_rectangle((rs * 16 // 100, rs * 54 // 100, rs * 16 // 100 + bar_w, rs - inset), radius=2*scale, fill=color)
        draw.rounded_rectangle((rs * 41 // 100, rs * 34 // 100, rs * 41 // 100 + bar_w, rs - inset), radius=2*scale, fill=color)
        draw.rounded_rectangle((rs * 66 // 100, rs * 16 // 100, rs * 66 // 100 + bar_w, rs - inset), radius=2*scale, fill=color)

    elif kind in ("nav_settings", "settings"):
        center = rs // 2
        outer_r = rs * 36 // 100
        inner_r = rs * 16 // 100
        draw.ellipse((center - outer_r, center - outer_r, center + outer_r, center + outer_r), outline=color, width=stroke * 2)
        draw.ellipse((center - inner_r, center - inner_r, center + inner_r, center + inner_r), fill=color)
        for angle_deg in range(0, 360, 45):
            rad = math.radians(angle_deg)
            x1 = center + int((outer_r - stroke) * math.cos(rad))
            y1 = center + int((outer_r - stroke) * math.sin(rad))
            x2 = center + int((outer_r + stroke * 2) * math.cos(rad))
            y2 = center + int((outer_r + stroke * 2) * math.sin(rad))
            draw.line([(x1, y1), (x2, y2)], fill=color, width=stroke * 2)

    elif kind in ("shield", "armed", "autoarm"):
        points = [(rs // 2, inset), (rs - inset, rs * 28 // 100), (rs * 78 // 100, rs * 68 // 100), (rs // 2, rs - inset), (rs * 22 // 100, rs * 68 // 100), (inset, rs * 28 // 100)]
        draw.polygon(points, fill=color)

    elif kind == "play":
        draw.polygon([(rs * 36 // 100, rs * 26 // 100), (rs * 74 // 100, rs // 2), (rs * 36 // 100, rs * 74 // 100)], fill=color)

    elif kind == "trash":
        draw.line((rs * 28 // 100, rs * 28 // 100, rs * 72 // 100, rs * 28 // 100), fill=color, width=stroke)
        draw.line((rs * 42 // 100, rs * 18 // 100, rs * 58 // 100, rs * 18 // 100), fill=color, width=stroke)
        draw.rounded_rectangle((rs * 32 // 100, rs * 32 // 100, rs * 68 // 100, rs * 82 // 100), radius=2*scale, outline=color, width=stroke)
        for x in (42, 58):
            draw.line((rs * x // 100, rs * 40 // 100, rs * x // 100, rs * 74 // 100), fill=color, width=max(1*scale, stroke - 1*scale))

    elif kind == "copy":
        draw.rounded_rectangle((rs * 38 // 100, inset, rs - inset, rs * 70 // 100), radius=2*scale, outline=color, width=stroke)
        draw.rounded_rectangle((inset, rs * 30 // 100, rs * 70 // 100, rs - inset), radius=2*scale, outline=color, fill=COLORS["canvas"], width=stroke)

    elif kind == "filter":
        pts = [
            (inset, rs * 22 // 100),
            (rs - inset, rs * 22 // 100),
            (rs * 60 // 100, rs * 52 // 100),
            (rs * 60 // 100, rs * 82 // 100),
            (rs * 40 // 100, rs * 72 // 100),
            (rs * 40 // 100, rs * 52 // 100),
        ]
        draw.polygon(pts, fill=color)

    elif kind == "list_menu":
        draw.line((inset, rs * 30 // 100, rs * 62 // 100, rs * 30 // 100), fill=color, width=stroke)
        draw.line((inset, rs * 50 // 100, rs * 62 // 100, rs * 50 // 100), fill=color, width=stroke)
        draw.line((inset, rs * 70 // 100, rs * 62 // 100, rs * 70 // 100), fill=color, width=stroke)
        draw.line((rs * 72 // 100, rs * 35 // 100, rs * 84 // 100, rs * 50 // 100), fill=color, width=stroke)
        draw.line((rs * 84 // 100, rs * 50 // 100, rs * 72 // 100, rs * 65 // 100), fill=color, width=stroke)

    elif kind == "discord":
        draw.rounded_rectangle((inset, rs * 26 // 100, rs - inset, rs * 74 // 100), radius=4*scale, fill=color)
        draw.ellipse((rs * 34 // 100, rs * 44 // 100, rs * 44 // 100, rs * 56 // 100), fill=COLORS["surface_card"])
        draw.ellipse((rs * 56 // 100, rs * 44 // 100, rs * 66 // 100, rs * 56 // 100), fill=COLORS["surface_card"])

    elif kind == "website":
        center = rs // 2
        r = rs * 36 // 100
        draw.ellipse((center - r, center - r, center + r, center + r), outline=color, width=stroke)
        draw.line((center - r, center, center + r, center), fill=color, width=stroke)
        draw.ellipse((center - r // 2, center - r, center + r // 2, center + r), outline=color, width=stroke)

    elif kind == "rules":
        draw.rounded_rectangle((rs * 24 // 100, inset, rs * 76 // 100, rs - inset), radius=2*scale, outline=color, width=stroke)
        draw.line((rs * 34 // 100, rs * 35 // 100, rs * 66 // 100, rs * 35 // 100), fill=color, width=stroke)
        draw.line((rs * 34 // 100, rs * 50 // 100, rs * 66 // 100, rs * 50 // 100), fill=color, width=stroke)
        draw.line((rs * 34 // 100, rs * 65 // 100, rs * 56 // 100, rs * 65 // 100), fill=color, width=stroke)

    elif kind == "map":
        draw.polygon([
            (inset, rs * 30 // 100), (rs * 38 // 100, rs * 20 // 100), (rs * 64 // 100, rs * 30 // 100), (rs - inset, rs * 20 // 100),
            (rs - inset, rs * 75 // 100), (rs * 64 // 100, rs * 85 // 100), (rs * 38 // 100, rs * 75 // 100), (inset, rs * 85 // 100),
        ], outline=color, width=stroke)

    elif kind == "players":
        draw.ellipse((rs * 28 // 100, rs * 20 // 100, rs * 48 // 100, rs * 40 // 100), fill=color)
        draw.arc((rs * 16 // 100, rs * 45 // 100, rs * 60 // 100, rs * 85 // 100), 180, 360, fill=color, width=stroke*2)
        draw.ellipse((rs * 56 // 100, rs * 28 // 100, rs * 72 // 100, rs * 44 // 100), fill=color)
        draw.arc((rs * 46 // 100, rs * 48 // 100, rs * 82 // 100, rs * 85 // 100), 180, 360, fill=color, width=stroke*2)

    elif kind == "cube":
        c = rs // 2
        r = rs * 32 // 100
        draw.polygon([(c, c - r), (c + r, c - r // 2), (c, c), (c - r, c - r // 2)], outline=color, width=stroke)
        draw.polygon([(c, c), (c + r, c - r // 2), (c + r, c + r // 2), (c, c + r)], outline=color, width=stroke)
        draw.polygon([(c - r, c - r // 2), (c, c), (c, c + r), (c - r, c + r // 2)], outline=color, width=stroke)

    elif kind == "clock":
        center = rs // 2
        r = rs * 36 // 100
        draw.ellipse((center - r, center - r, center + r, center + r), outline=color, width=stroke)
        draw.line((center, center, center, center - r * 6 // 10), fill=color, width=stroke)
        draw.line((center, center, center + r * 6 // 10, center), fill=color, width=stroke)

    elif kind == "rust_badge":
        draw.rounded_rectangle((2*scale, 2*scale, rs - 3*scale, rs - 3*scale), radius=5*scale, fill=COLORS["accent"])
        draw.rectangle((rs * 28 // 100, rs * 26 // 100, rs * 40 // 100, rs * 74 // 100), fill="#FFFFFF")
        draw.rectangle((rs * 40 // 100, rs * 26 // 100, rs * 72 // 100, rs * 40 // 100), fill="#FFFFFF")
        draw.rectangle((rs * 40 // 100, rs * 44 // 100, rs * 66 // 100, rs * 56 // 100), fill="#FFFFFF")

    elif kind == "brand":
        draw.rounded_rectangle((2*scale, 2*scale, rs - 3*scale, rs - 3*scale), radius=7*scale, fill=COLORS["accent"])
        draw.rectangle((rs * 28 // 100, rs * 26 // 100, rs * 40 // 100, rs * 74 // 100), fill="#FFFFFF")
        draw.rectangle((rs * 40 // 100, rs * 26 // 100, rs * 72 // 100, rs * 40 // 100), fill="#FFFFFF")
        draw.rectangle((rs * 40 // 100, rs * 44 // 100, rs * 66 // 100, rs * 56 // 100), fill="#FFFFFF")

    return image.resize((size, size), Image.Resampling.LANCZOS)


def _draw_sidebar_watermark(width: int = 210, height: int = 380) -> Image.Image:
    im = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)

    for y in range(int(height * 0.25), height):
        alpha = int(70 * ((y - height * 0.25) / (height * 0.75)))
        draw.line([(0, y), (width, y)], fill=(16, 20, 27, alpha))

    dish_cx = int(width * 0.65)
    dish_cy = int(height * 0.45)
    draw.line([(dish_cx - 24, dish_cy + 60), (dish_cx - 8, dish_cy + 8)], fill=(22, 28, 38, 160), width=3)
    draw.line([(dish_cx + 24, dish_cy + 60), (dish_cx + 8, dish_cy + 8)], fill=(22, 28, 38, 160), width=3)
    draw.line([(dish_cx - 18, dish_cy + 35), (dish_cx + 18, dish_cy + 35)], fill=(22, 28, 38, 160), width=2)
    draw.arc((dish_cx - 45, dish_cy - 55, dish_cx + 45, dish_cy + 25), 160, 380, fill=(24, 31, 42, 180), width=6)
    draw.line([(dish_cx, dish_cy - 14), (dish_cx + 20, dish_cy - 48)], fill=(24, 31, 42, 180), width=3)

    px, py = int(width * 0.22), int(height * 0.50)
    draw.line([(px - 12, py + 55), (px - 3, py - 30)], fill=(20, 26, 35, 150), width=2)
    draw.line([(px + 12, py + 55), (px + 3, py - 30)], fill=(20, 26, 35, 150), width=2)
    draw.line([(px - 18, py - 10), (px + 18, py - 10)], fill=(20, 26, 35, 150), width=2)
    draw.line([(px - 22, py + 10), (px + 22, py + 10)], fill=(20, 26, 35, 150), width=2)

    for x in range(-5, width + 10, 5):
        h = int(35 + math.sin(x * 0.12) * 20 + math.cos(x * 0.05) * 12)
        base_y = int(height * 0.82 + math.sin(x * 0.03) * 10)
        draw.polygon([(x - 5, base_y), (x, base_y - h), (x + 5, base_y)], fill=(18, 24, 33, 190))

    for x in range(-5, width + 10, 4):
        h = int(45 + math.sin(x * 0.18 + 2) * 22 + math.cos(x * 0.07) * 14)
        base_y = height
        draw.polygon([(x - 6, base_y), (x, base_y - h), (x + 6, base_y)], fill=(13, 17, 23, 230))

    return im


def _generate_rust_sunset_banner(width: int = 620, height: int = 148) -> Image.Image:
    im = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(im)

    for y in range(height):
        t = y / height
        if t < 0.35:
            k = t / 0.35
            r = int(25 + (180 - 25) * k)
            g = int(20 + (80 - 20) * k)
            b = int(45 + (35 - 45) * k)
        elif t < 0.65:
            k = (t - 0.35) / 0.30
            r = int(180 + (240 - 180) * k)
            g = int(80 + (140 - 80) * k)
            b = int(35 + (45 - 35) * k)
        else:
            k = (t - 0.65) / 0.35
            r = int(240 + (255 - 240) * k)
            g = int(140 + (195 - 140) * k)
            b = int(45 + (80 - 45) * k)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    sun_x = int(width * 0.52)
    sun_y = int(height * 0.58)
    for r in range(42, 0, -2):
        glow_col = (255, 235, 160) if r < 14 else (255, 175, 70)
        draw.ellipse((sun_x - r, sun_y - r, sun_x + r, sun_y + r), fill=glow_col)

    mountain1 = [(0, height)]
    for x in range(0, width + 5, 8):
        my = int(height * 0.52 + math.sin(x * 0.015) * 12 + math.cos(x * 0.035) * 6)
        mountain1.append((x, my))
    mountain1.append((width, height))
    draw.polygon(mountain1, fill=(58, 32, 42))

    mountain2 = [(0, height)]
    for x in range(0, width + 5, 6):
        my = int(height * 0.62 + math.sin(x * 0.018 + 1) * 10 + math.sin(x * 0.04) * 5)
        mountain2.append((x, my))
    mountain2.append((width, height))
    draw.polygon(mountain2, fill=(40, 22, 30))

    dish_cx = int(width * 0.42)
    dish_cy = int(height * 0.52)
    draw.line([(dish_cx - 18, dish_cy + 36), (dish_cx - 6, dish_cy + 4)], fill=(22, 14, 18), width=3)
    draw.line([(dish_cx + 18, dish_cy + 36), (dish_cx + 6, dish_cy + 4)], fill=(22, 14, 18), width=3)
    draw.line([(dish_cx - 14, dish_cy + 22), (dish_cx + 14, dish_cy + 22)], fill=(22, 14, 18), width=2)
    draw.line([(dish_cx - 16, dish_cy + 10), (dish_cx + 16, dish_cy + 10)], fill=(22, 14, 18), width=2)
    draw.arc((dish_cx - 36, dish_cy - 46, dish_cx + 36, dish_cy + 18), 160, 380, fill=(22, 14, 18), width=5)
    draw.line([(dish_cx, dish_cy - 12), (dish_cx + 16, dish_cy - 38)], fill=(22, 14, 18), width=3)
    draw.ellipse((dish_cx + 13, dish_cy - 41, dish_cx + 19, dish_cy - 35), fill=(22, 14, 18))

    tow_x = int(width * 0.62)
    tow_y = int(height * 0.50)
    draw.rectangle((tow_x - 10, tow_y, tow_x + 10, tow_y + 45), fill=(22, 14, 18))
    draw.polygon([(tow_x - 14, tow_y), (tow_x + 14, tow_y), (tow_x + 10, tow_y - 12), (tow_x - 10, tow_y - 12)], fill=(22, 14, 18))
    draw.rectangle((tow_x - 6, tow_y - 20, tow_x + 6, tow_y - 12), fill=(22, 14, 18))

    for px, py in [(int(width * 0.12), int(height * 0.58)), (int(width * 0.88), int(height * 0.60))]:
        draw.line([(px - 8, py + 30), (px - 2, py - 20)], fill=(24, 16, 20), width=2)
        draw.line([(px + 8, py + 30), (px + 2, py - 20)], fill=(24, 16, 20), width=2)
        draw.line([(px - 14, py - 6), (px + 14, py - 6)], fill=(24, 16, 20), width=2)
        draw.line([(px - 18, py + 6), (px + 18, py + 6)], fill=(24, 16, 20), width=2)

    pines = [(0, height)]
    for x in range(0, width + 1, 4):
        h = int(14 + math.sin(x * 0.2) * 8 + math.cos(x * 0.05) * 6)
        by = int(height * 0.72 + math.sin(x * 0.01) * 6)
        pines.append((x, by - h))
        pines.append((x + 2, by))
    pines.append((width, height))
    draw.polygon(pines, fill=(18, 12, 16))

    draw.rectangle((0, int(height * 0.86), width, height), fill=(14, 9, 12))
    return im


class MainWindow(ctk.CTk):
    def __init__(self, history_mgr: Optional[HistoryStore] = None, i18n_mgr: Optional[I18nManager] = None):
        super().__init__()

        self.history_store = history_mgr if history_mgr is not None else history_store
        self.i18n = i18n_mgr if i18n_mgr is not None else i18n

        self.lang = self.history_store.get_lang()
        self.i18n.set_lang(self.lang)

        self.title("Rust AutoConnect")
        self.geometry("1100x740")
        self.minsize(900, 646)
        self.configure(fg_color=COLORS["canvas"])

        # Unified Column Width Model
        self.col_widths = self.history_store.get_column_widths()
        for col_name, min_w in MIN_WIDTHS.items():
            if self.col_widths.get(col_name, 0) < min_w:
                self.col_widths[col_name] = min_w

        self.header_cells: Dict[str, ctk.CTkFrame] = {}
        self.header_dividers: Dict[str, ctk.CTkFrame] = {}
        self.registered_row_cells: List[Dict[str, Any]] = []

        self._drag_col_target: Optional[str] = None
        self._drag_start_x: int = 0
        self._drag_initial_width: int = 0
        self._drag_current_width: int = 0
        self._drag_threshold_passed: bool = False

        self._search_timer = None
        self._ui_callback_queue: queue.Queue[tuple] = queue.Queue()
        self._ui_dispatch_closing = False
        self._ui_dispatch_after_id = self.after(25, self._drain_ui_callbacks)
        self.is_auto_update_enabled = self.history_store.get_auto_update()
        self.auto_update = ctk.BooleanVar(value=self.is_auto_update_enabled)
        self.auto_scroll = ctk.BooleanVar(value=True)
        self.rust_playtime_started_at: Optional[float] = None
        self.last_connected_var = ctk.StringVar(value=self.t("not_connected"))
        self.session_status_var = ctk.StringVar(value=self.t("idle"))
        self.connection_progress_var = ctk.StringVar(value="")
        self.playtime_var = ctk.StringVar(value="00:00:00")

        self._cached_playtime_str = ""
        self._cached_rust_status = None
        self._cached_armed_status = None

        # Floating Decoupled Overlay Drawer State
        self._drawer_animation_id = None
        self._log_drawer_visible = False
        self._drawer_progress = 0.0

        self._tg_overlay = None
        self._server_card_overlay = None
        self._server_card_window = None
        self._server_card_escape_id = None
        self._selected_server_endpoint: Optional[str] = None
        self._selected_server_snapshot = None

        self._icon_images = {
            "brand": ctk.CTkImage(light_image=_draw_icon("brand", COLORS["accent"], 34), dark_image=_draw_icon("brand", COLORS["accent"], 34), size=(28, 28)),
            "favorite": ctk.CTkImage(light_image=_draw_icon("star_filled", COLORS["accent"]), dark_image=_draw_icon("star_filled", COLORS["accent"]), size=(16, 16)),
            "favorite_off": ctk.CTkImage(light_image=_draw_icon("star_outline", "#484F58"), dark_image=_draw_icon("star_outline", "#484F58"), size=(16, 16)),
            "armed": ctk.CTkImage(light_image=_draw_icon("armed", COLORS["success"]), dark_image=_draw_icon("armed", COLORS["success"]), size=(14, 14)),
            "shield": ctk.CTkImage(light_image=_draw_icon("shield", "#6E7681"), dark_image=_draw_icon("shield", "#6E7681"), size=(14, 14)),
            "connect": ctk.CTkImage(light_image=_draw_icon("play", COLORS["text"]), dark_image=_draw_icon("play", COLORS["text"]), size=(13, 13)),
            "trash": ctk.CTkImage(light_image=_draw_icon("trash", "#6E7681"), dark_image=_draw_icon("trash", "#6E7681"), size=(14, 14)),
            "copy": ctk.CTkImage(light_image=_draw_icon("copy", "#6E7681"), dark_image=_draw_icon("copy", "#6E7681"), size=(14, 14)),
            "filter": ctk.CTkImage(light_image=_draw_icon("filter", COLORS["text"]), dark_image=_draw_icon("filter", COLORS["text"]), size=(15, 15)),
            "list_menu": ctk.CTkImage(light_image=_draw_icon("list_menu", COLORS["text"]), dark_image=_draw_icon("list_menu", COLORS["text"]), size=(16, 16)),
            "discord": ctk.CTkImage(light_image=_draw_icon("discord", COLORS["muted"]), dark_image=_draw_icon("discord", COLORS["muted"]), size=(16, 16)),
            "website": ctk.CTkImage(light_image=_draw_icon("website", COLORS["muted"]), dark_image=_draw_icon("website", COLORS["muted"]), size=(16, 16)),
            "rules": ctk.CTkImage(light_image=_draw_icon("rules", COLORS["muted"]), dark_image=_draw_icon("rules", COLORS["muted"]), size=(16, 16)),
            "map": ctk.CTkImage(light_image=_draw_icon("map", COLORS["accent"]), dark_image=_draw_icon("map", COLORS["accent"]), size=(20, 20)),
            "players": ctk.CTkImage(light_image=_draw_icon("players", COLORS["accent"]), dark_image=_draw_icon("players", COLORS["accent"]), size=(20, 20)),
            "cube": ctk.CTkImage(light_image=_draw_icon("cube", COLORS["accent"]), dark_image=_draw_icon("cube", COLORS["accent"]), size=(20, 20)),
            "clock": ctk.CTkImage(light_image=_draw_icon("clock", COLORS["muted"]), dark_image=_draw_icon("clock", COLORS["muted"]), size=(16, 16)),
            "rust_badge": ctk.CTkImage(light_image=_draw_icon("rust_badge", COLORS["accent"]), dark_image=_draw_icon("rust_badge", COLORS["accent"]), size=(20, 20)),
        }
        for icon_name in ("nav_home", "nav_bench", "nav_settings", "nav_connect"):
            self._icon_images[f"{icon_name}_muted"] = ctk.CTkImage(
                light_image=_draw_icon(icon_name, COLORS["muted"]),
                dark_image=_draw_icon(icon_name, COLORS["muted"]),
                size=(19, 19),
            )
            self._icon_images[f"{icon_name}_active"] = ctk.CTkImage(
                light_image=_draw_icon(icon_name, COLORS["accent"]),
                dark_image=_draw_icon(icon_name, COLORS["accent"]),
                size=(19, 19),
            )

        self.tray_icon = None
        self.protocol('WM_DELETE_WINDOW', self._on_close_requested)
        self.bind('<Unmap>', self.on_unmap)

        self.grid_columnconfigure(0, minsize=210)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, minsize=44, weight=0)

        # ==========================================
        # 1. SIDEBAR FRAME
        # ==========================================
        self.sidebar_frame = ctk.CTkFrame(self, width=210, corner_radius=0, fg_color=COLORS["sidebar"], border_width=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_propagate(False)
        self.sidebar_frame.grid_columnconfigure(0, weight=1)
        self.sidebar_frame.grid_rowconfigure(4, weight=1)

        # Top branding: Rust logo + "Rust AutoConnect"
        self.brand_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.brand_frame.grid(row=0, column=0, padx=16, pady=(20, 24), sticky="w")
        self.brand_mark = ctk.CTkLabel(self.brand_frame, text="", image=self._icon_images["brand"], width=28, height=28)
        self.brand_mark.pack(side="left", padx=(0, 8))
        self.topbar_title = ctk.CTkLabel(self.brand_frame, text="Rust ", font=ctk.CTkFont(size=16, weight="bold"), text_color=COLORS["text"])
        self.topbar_title.pack(side="left")
        self.topbar_subtitle = ctk.CTkLabel(self.brand_frame, text="AutoConnect", font=ctk.CTkFont(size=16, weight="bold"), text_color=COLORS["accent"])
        self.topbar_subtitle.pack(side="left")

        # Navigation buttons
        self.nav_home_btn = self._nav_button(self.t("nav_home"), self.show_home_frame, "nav_home")
        self.nav_home_btn.grid(row=1, column=0, padx=10, pady=(0, 4), sticky="ew")

        self.nav_bench_btn = self._nav_button(self.t("nav_bench"), self.show_bench_frame, "nav_bench")
        self.nav_bench_btn.grid(row=2, column=0, padx=10, pady=(0, 4), sticky="ew")

        self.nav_settings_btn = self._nav_button(self.t("nav_settings"), self.show_settings_frame, "nav_settings")
        self.nav_settings_btn.grid(row=3, column=0, padx=10, pady=(0, 4), sticky="ew")

        self._nav_buttons = [self.nav_home_btn, self.nav_bench_btn, self.nav_settings_btn]
        self._nav_icon_names = {
            self.nav_home_btn: "nav_home",
            self.nav_bench_btn: "nav_bench",
            self.nav_settings_btn: "nav_settings",
        }

        # Atmospheric dark monument & pine tree background
        watermark_img = _draw_sidebar_watermark(210, 360)
        self._sidebar_watermark_ctk = ctk.CTkImage(light_image=watermark_img, dark_image=watermark_img, size=(210, 360))
        self.sidebar_watermark = ctk.CTkLabel(self.sidebar_frame, text="", image=self._sidebar_watermark_ctk)
        self.sidebar_watermark.grid(row=4, column=0, sticky="sew")

        # Sidebar footer (v0.7.0 • Latest)
        self.sidebar_footer = ctk.CTkFrame(self.sidebar_frame, height=38, corner_radius=0, fg_color="transparent")
        self.sidebar_footer.grid(row=5, column=0, sticky="sew", padx=16, pady=(0, 12))

        self.version_label = ctk.CTkLabel(self.sidebar_footer, text="v0.7.0", font=ctk.CTkFont(size=12, weight="bold"), text_color=COLORS["muted"])
        self.version_label.pack(side="left", padx=(0, 10))

        self.version_badge = ctk.CTkFrame(self.sidebar_footer, fg_color=COLORS["surface_card"], border_width=1, border_color=COLORS["border"], corner_radius=4, height=24)
        self.version_badge.pack(side="left")
        self.version_state_dot = ctk.CTkLabel(self.version_badge, text="●", font=ctk.CTkFont(size=9), text_color=COLORS["accent"])
        self.version_state_dot.pack(side="left", padx=(6, 3), pady=2)
        self.version_state_label = ctk.CTkLabel(self.version_badge, text="Latest", font=ctk.CTkFont(size=11, weight="bold"), text_color=COLORS["text"])
        self.version_state_label.pack(side="left", padx=(0, 8), pady=2)

        # ==========================================
        # 2. CONTENT FRAMES
        # ==========================================
        self.home_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.bench_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.settings_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")

        for frame in (self.home_frame, self.bench_frame, self.settings_frame):
            frame.grid(row=0, column=1, sticky="nsew")

        # ==========================================
        # 2.1 HOME FRAME ("Серверы")
        # ==========================================
        self.home_frame.grid_columnconfigure(0, weight=1)
        self.home_frame.grid_rowconfigure(2, weight=1)

        self.home_header = ctk.CTkLabel(self.home_frame, text="Серверы", font=ctk.CTkFont(size=30, weight="bold"), text_color=COLORS["text"])
        self.home_header.grid(row=0, column=0, padx=30, pady=(22, 14), sticky="w")
        self.home_subtitle = ctk.CTkLabel(self.home_frame, text="", font=ctk.CTkFont(size=1))

        # Single-row action toolbar
        self.input_frame = ctk.CTkFrame(self.home_frame, corner_radius=0, fg_color="transparent")
        self.input_frame.grid(row=1, column=0, padx=30, pady=(0, 14), sticky="ew")
        self.input_frame.grid_columnconfigure(0, weight=5)
        self.input_frame.grid_columnconfigure(2, weight=4)

        self.address_label = ctk.CTkLabel(self.input_frame, text="", width=0)

        self.ip_entry = ctk.CTkEntry(
            self.input_frame, height=42, corner_radius=6, border_width=1,
            border_color=COLORS["border"], fg_color=COLORS["input_bg"],
            placeholder_text="IP:PORT (например, 127.0.0.1:28015)",
            placeholder_text_color="#5D6574",
            text_color=COLORS["text"], font=ctk.CTkFont(size=13),
        )
        self.ip_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        self.connect_btn = ctk.CTkButton(
            self.input_frame, text="ПОДКЛЮЧИТЬСЯ", command=self._on_connect_btn_click,
            width=145, height=42, corner_radius=6,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            text_color=COLORS["text"], font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.connect_btn.grid(row=0, column=1, padx=(0, 14))

        self.search_entry = ctk.CTkEntry(
            self.input_frame, placeholder_text="🔍  Поиск серверов",
            placeholder_text_color="#5D6574",
            height=42, width=220, corner_radius=6, fg_color=COLORS["input_bg"],
            border_width=1, border_color=COLORS["border"], text_color=COLORS["text"],
            font=ctk.CTkFont(size=13),
        )
        self.search_entry.grid(row=0, column=2, padx=(0, 10), sticky="ew")
        self.search_entry.bind("<KeyRelease>", self._on_search_key_released)

        self.filter_var = ctk.StringVar(value="Все")
        self.filter_btn = ctk.CTkButton(
            self.input_frame, text="", image=self._icon_images["filter"],
            width=42, height=42, corner_radius=6,
            fg_color=COLORS["input_bg"], hover_color=COLORS["surface_alt"],
            border_width=1, border_color=COLORS["border"],
            command=self._toggle_filter,
        )
        self.filter_btn.grid(row=0, column=3, padx=(0, 8))
        ToolTip(self.filter_btn, "Фильтр (Все / Избранное)")
        self.filter_menu = ctk.CTkOptionMenu(self.input_frame, variable=self.filter_var)

        self.log_drawer_btn = ctk.CTkButton(
            self.input_frame, text="", image=self._icon_images["list_menu"],
            width=42, height=42, corner_radius=6,
            command=self.toggle_activity_log, fg_color=COLORS["input_bg"],
            hover_color=COLORS["surface_alt"], border_width=1, border_color=COLORS["border"],
        )
        self.log_drawer_btn.grid(row=0, column=4)
        ToolTip(self.log_drawer_btn, "Журнал активности (лог)")

        self.connection_progress_label = ctk.CTkLabel(
            self.input_frame, textvariable=self.connection_progress_var,
            text_color=COLORS["muted"], font=ctk.CTkFont(size=11), anchor="w",
        )
        self.connection_progress_label.grid(row=1, column=0, columnspan=5, padx=2, pady=(4, 0), sticky="ew")

        # Home Content Container (Table Area + Decoupled Floating Overlay Layer)
        self.home_content = ctk.CTkFrame(self.home_frame, corner_radius=0, fg_color="transparent")
        self.home_content.grid(row=2, column=0, padx=26, pady=(0, 10), sticky="nsew")

        # Main Server Table Panel (100% width, stays static without layout thrashing)
        self.history_panel = ctk.CTkFrame(self.home_content, corner_radius=8, fg_color=COLORS["surface"], border_width=1, border_color=COLORS["border"])
        self.history_panel.place(relx=0.0, rely=0.0, relwidth=1.0, relheight=1.0)
        self.history_panel.grid_columnconfigure(0, weight=1)
        self.history_panel.grid_rowconfigure(1, weight=1)

        self.history_label = ctk.CTkLabel(self.history_panel, text="", font=ctk.CTkFont(size=1))
        self.history_actions = ctk.CTkFrame(self.history_panel, fg_color="transparent")
        self.import_servers_btn = ctk.CTkButton(self.history_actions, text="Импорт", width=58, height=24, command=self.import_server_library, fg_color="transparent", hover_color=COLORS["surface_alt"])
        self.export_servers_btn = ctk.CTkButton(self.history_actions, text="Экспорт", width=58, height=24, command=self.export_server_library, fg_color="transparent", hover_color=COLORS["surface_alt"])

        # Table Header Bar - Excel/Sheets Resizable Column Grid
        self.table_header_frame = ctk.CTkFrame(self.history_panel, fg_color="transparent", height=36)
        self.table_header_frame.grid(row=0, column=0, sticky="ew", padx=(10, 24), pady=(8, 4))
        self.table_header_frame.pack_propagate(False)

        self._build_table_header()

        self.history_scroll = ctk.CTkScrollableFrame(self.history_panel, fg_color="transparent", corner_radius=0)
        self.history_scroll.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))

        # Zero-Lag Ghost Resize Guide Line & Width Tooltip Badge
        self._ghost_guide_frame = ctk.CTkFrame(self.history_panel, width=2, fg_color=COLORS["accent"], corner_radius=0)
        self._ghost_guide_frame.place_forget()

        self._ghost_badge = ctk.CTkLabel(
            self.history_panel, text="280 px", font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=COLORS["accent"], text_color="#FFFFFF", corner_radius=4, padx=6, pady=2,
        )
        self._ghost_badge.place_forget()

        # Floating Decoupled Overlay Layer (Backdrop + Floating Drawer Card)
        self.overlay_backdrop = ctk.CTkFrame(self.home_content, fg_color="transparent", corner_radius=0)
        self.overlay_backdrop.bind("<Button-1>", lambda event: self.toggle_activity_log())

        self.connection_panel = ctk.CTkFrame(
            self.home_content, corner_radius=8, fg_color=COLORS["surface_card"],
            border_width=1, border_color=COLORS["border"],
        )
        self.connection_panel.grid_columnconfigure(0, weight=1)
        self.connection_panel.grid_rowconfigure(1, weight=1)

        log_head = ctk.CTkFrame(self.connection_panel, fg_color="transparent")
        log_head.grid(row=0, column=0, columnspan=2, sticky="ew", padx=14, pady=(10, 4))
        log_head.grid_columnconfigure(0, weight=1)

        self.log_title = ctk.CTkLabel(log_head, text="Журнал активности", font=ctk.CTkFont(size=13, weight="bold"), text_color=COLORS["text"])
        self.log_title.grid(row=0, column=0, sticky="w")

        self.log_toolbar = ctk.CTkFrame(log_head, fg_color="transparent")
        self.log_toolbar.grid(row=0, column=1, sticky="e")

        self.auto_scroll_check = ctk.CTkCheckBox(
            self.log_toolbar, text="Автопрокрутка", variable=self.auto_scroll,
            checkbox_width=14, checkbox_height=14, font=ctk.CTkFont(size=11),
            text_color=COLORS["muted"], fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
        )
        self.auto_scroll_check.pack(side="left", padx=(0, 10))

        self.clear_log_btn = ctk.CTkButton(
            self.log_toolbar, text="Очистить", command=self.clear_log, width=64, height=26,
            fg_color=COLORS["surface_alt"], hover_color=COLORS["border"], border_width=1, border_color=COLORS["border"],
        )
        self.clear_log_btn.pack(side="left", padx=(0, 8))

        self.close_drawer_btn = ctk.CTkButton(
            self.log_toolbar, text="✕", command=self.toggle_activity_log, width=26, height=26,
            fg_color="transparent", hover_color=COLORS["surface_hover"], text_color=COLORS["muted"],
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.close_drawer_btn.pack(side="left")

        self.log_frame = ctk.CTkFrame(self.connection_panel, fg_color=COLORS["surface_alt"], corner_radius=4)
        self.log_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=14, pady=(0, 10))
        self.log_frame.grid_columnconfigure(0, weight=1)
        self.log_frame.grid_rowconfigure(0, weight=1)

        self.log_textbox = ctk.CTkTextbox(self.log_frame, state="disabled", fg_color=COLORS["surface_alt"], text_color="#D4DAE2", font=ctk.CTkFont(family="Consolas", size=12), corner_radius=4)
        self.log_textbox.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        self.connection_panel.place_forget()
        self.overlay_backdrop.place_forget()

        self.session_status_label = ctk.CTkLabel(self.home_frame, textvariable=self.session_status_var)
        self.last_connected_label = ctk.CTkLabel(self.home_frame, textvariable=self.last_connected_var)
        self.last_connected_tooltip = ToolTip(self.last_connected_label, self.t("not_connected"))

        # ==========================================
        # 2.2 BENCHMARK FRAME
        # ==========================================
        self.bench_frame.grid_columnconfigure(0, weight=1)
        self.bench_frame.grid_rowconfigure(2, weight=1)
        self.bench_title = ctk.CTkLabel(self.bench_frame, text=self.t("tab_bench"), font=ctk.CTkFont(size=24, weight="bold"), text_color=COLORS["text"])
        self.bench_title.grid(row=0, column=0, padx=28, pady=(20, 4), sticky="w")
        self.bench_subtitle = ctk.CTkLabel(self.bench_frame, text=self.t("bench_subtitle"), text_color=COLORS["muted"], font=ctk.CTkFont(size=13))
        self.bench_subtitle.grid(row=1, column=0, padx=28, pady=(0, 12), sticky="w")
        self.bench_content = ctk.CTkFrame(self.bench_frame, fg_color="transparent")
        self.bench_content.grid(row=2, column=0, padx=24, pady=(0, 0), sticky="nsew")
        self.bench_content.grid_columnconfigure(0, weight=0, minsize=260)
        self.bench_content.grid_columnconfigure(1, weight=1)
        self.bench_content.grid_rowconfigure(0, weight=1)

        self.bench_controls = ctk.CTkFrame(self.bench_content, fg_color=COLORS["surface"], corner_radius=8, border_width=1, border_color=COLORS["border"], width=260)
        self.bench_controls.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.bench_btn = ctk.CTkButton(self.bench_controls, text=self.t("run_test"), command=self._on_run_test_click, fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"], text_color=COLORS["text"], height=42, font=ctk.CTkFont(weight="bold"))
        self.bench_btn.pack(fill="x", padx=16, pady=(18, 8))
        self.bench_mode_label = ctk.CTkLabel(self.bench_controls, text=self.t("hw_benchmark"), font=ctk.CTkFont(size=12, weight="bold"), text_color=COLORS["text"])
        self.bench_mode_label.pack(anchor="w", padx=16, pady=(12, 6))
        self.hardware_label = ctk.CTkLabel(self.bench_controls, text=self.t("lb_load"), justify="left", wraplength=230, text_color=COLORS["muted"], font=ctk.CTkFont(size=13))
        self.hardware_label.pack(fill="x", padx=16, pady=(0, 18))
        store = self.__dict__.get("history_store")
        local_run_count = len(store.get_benchmark_runs()) if store is not None else 0
        summary_text = self.t("local_results_none") if not local_run_count else self.t("local_results_fmt", count=local_run_count)
        self.benchmark_summary_label = ctk.CTkLabel(self.bench_controls, text=summary_text, justify="left", wraplength=230, text_color=COLORS["muted"], font=ctk.CTkFont(size=12))
        self.benchmark_summary_label.pack(fill="x", padx=16, pady=(0, 18))

        self.bench_results_panel = ctk.CTkFrame(self.bench_content, fg_color=COLORS["surface"], corner_radius=8, border_width=1, border_color=COLORS["border"])
        self.bench_results_panel.grid(row=0, column=1, sticky="nsew")
        self.bench_results_panel.grid_columnconfigure(0, weight=1)
        self.bench_results_panel.grid_rowconfigure(1, weight=1)
        self.bench_view_var = ctk.StringVar(value=self.t("tab_run_log"))
        self.bench_view_tabs = ctk.CTkSegmentedButton(
            self.bench_results_panel,
            values=[self.t("tab_run_log"), self.t("tab_online_ranking")],
            variable=self.bench_view_var,
            command=self.show_benchmark_view,
            fg_color=COLORS["surface_alt"],
            selected_color=COLORS["accent"],
            selected_hover_color=COLORS["accent_hover"],
            unselected_color=COLORS["surface_alt"],
            unselected_hover_color=COLORS["border"],
        )
        self.bench_view_tabs.grid(row=0, column=0, padx=14, pady=(12, 8), sticky="w")
        self.bench_views = ctk.CTkFrame(self.bench_results_panel, fg_color="transparent")
        self.bench_views.grid(row=1, column=0, padx=14, pady=(0, 14), sticky="nsew")
        self.bench_views.grid_rowconfigure(0, weight=1)
        self.bench_views.grid_columnconfigure(0, weight=1)
        self.bench_log = ctk.CTkTextbox(self.bench_views, state="disabled", fg_color=COLORS["surface_alt"], text_color="#D4DAE2", font=ctk.CTkFont(family="Consolas", size=12), corner_radius=2)
        self.bench_online_ranking = ctk.CTkScrollableFrame(self.bench_views, fg_color=COLORS["surface_alt"], corner_radius=2)
        for view in (self.bench_log, self.bench_online_ranking):
            view.grid(row=0, column=0, sticky="nsew")
        self.show_benchmark_view("Run log")

        # ==========================================
        # 2.3 SETTINGS FRAME
        # ==========================================
        self.settings_frame.grid_columnconfigure(1, weight=0)
        self.settings_title = ctk.CTkLabel(self.settings_frame, text=self.t("settings_title"), font=ctk.CTkFont(size=24, weight="bold"), text_color=COLORS["text"])
        self.settings_title.grid(row=0, column=0, columnspan=2, padx=28, pady=(20, 4), sticky="w")
        self.settings_subtitle = ctk.CTkLabel(self.settings_frame, text=self.t("settings_subtitle"), font=ctk.CTkFont(size=13), text_color=COLORS["muted"])
        self.settings_subtitle.grid(row=1, column=0, columnspan=2, padx=28, pady=(0, 12), sticky="w")
        self.settings_panel = ctk.CTkFrame(self.settings_frame, fg_color=COLORS["surface"], corner_radius=8, border_width=1, border_color=COLORS["border"])
        self.settings_panel.grid(row=2, column=0, columnspan=2, padx=24, pady=(0, 0), sticky="nw")
        self.settings_panel.grid_columnconfigure(1, weight=0)

        # Language
        self.lang_label = ctk.CTkLabel(self.settings_panel, text=self.t("lang_lbl"), font=ctk.CTkFont(weight="bold"))
        self.lang_label.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")

        self.lang_menu = ctk.CTkOptionMenu(
            self.settings_panel,
            values=list(I18nManager.LANG_MAP.values()),
            command=self.change_lang,
            width=200,
            fg_color=COLORS["surface_alt"],
            button_color=COLORS["border"],
            button_hover_color=COLORS["accent_hover"],
            dropdown_fg_color=COLORS["surface_alt"],
        )
        self.lang_menu.grid(row=0, column=1, padx=20, pady=(20, 10), sticky="w")
        self.lang_menu.set(I18nManager.LANG_MAP.get(self.history_store.get_lang(), self.history_store.get_lang()))

        # Tray Checkbox
        self.tray_var = ctk.BooleanVar(value=self.history_store.get_minimize_to_tray())
        self.tray_checkbox = ctk.CTkCheckBox(self.settings_panel, text=self.t("tray_lbl"), variable=self.tray_var, command=self._on_tray_change, fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"], border_color=COLORS["muted"])
        self.tray_checkbox.grid(row=1, column=0, columnspan=2, padx=20, pady=12, sticky="w")
        self.tray_tooltip = ToolTip(self.tray_checkbox, self.t("tooltip_tray"))

        # Swarm Checkbox
        self.swarm_var = ctk.BooleanVar(value=self.history_store.get_swarm_enabled())
        self.swarm_checkbox = ctk.CTkCheckBox(self.settings_panel, text=self.t("swarm_lbl"), variable=self.swarm_var, command=self._on_swarm_change, fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"], border_color=COLORS["muted"])
        self.swarm_checkbox.grid(row=2, column=0, columnspan=2, padx=20, pady=12, sticky="w")
        self.swarm_tooltip = ToolTip(self.swarm_checkbox, self.t("tooltip_swarm"))
        self.swarm_safety_label = ctk.CTkLabel(
            self.settings_panel,
            text=self.t("swarm_safety_note"),
            text_color=COLORS["muted"], font=ctk.CTkFont(size=11), wraplength=430, justify="left",
        )
        self.swarm_safety_label.grid(row=3, column=0, columnspan=2, padx=(42, 20), pady=(0, 8), sticky="w")

        self.share_servers_var = ctk.BooleanVar(value=self.history_store.get_share_saved_servers())
        self.share_servers_checkbox = ctk.CTkCheckBox(
            self.settings_panel, text=self.t("share_saved_servers_lbl"),
            variable=self.share_servers_var, command=self._on_share_saved_servers_change,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"], border_color=COLORS["muted"],
        )
        self.share_servers_checkbox.grid(row=4, column=0, columnspan=2, padx=20, pady=12, sticky="w")
        self.share_servers_tooltip = ToolTip(self.share_servers_checkbox, self.t("tooltip_share_saved_servers"))

        self.auto_update_settings = ctk.CTkCheckBox(
            self.settings_panel,
            text=self.t("check_rust_updates"),
            variable=self.auto_update,
            command=self.on_auto_update_change,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            border_color=COLORS["muted"],
        )
        self.auto_update_settings.grid(row=5, column=0, columnspan=2, padx=20, pady=12, sticky="w")

        self.auto_arm_var = ctk.BooleanVar(value=self.history_store.get_auto_arm())
        self.auto_arm_checkbox = ctk.CTkCheckBox(
            self.settings_panel,
            text=self.t("auto_arm_lbl"),
            variable=self.auto_arm_var,
            command=self._on_auto_arm_change,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            border_color=COLORS["muted"],
        )
        self.auto_arm_checkbox.grid(row=6, column=0, columnspan=2, padx=20, pady=12, sticky="w")

        # Telegram Bot Linking
        self.tg_frame = ctk.CTkFrame(self.settings_panel, fg_color="transparent")
        self.tg_frame.grid(row=7, column=0, columnspan=2, padx=20, pady=12, sticky="w")
        code_txt = self._telegram_status_text()
        self.tg_status_lbl = ctk.CTkLabel(self.tg_frame, text=code_txt, text_color=COLORS["muted"])
        self.tg_status_lbl.pack(side="left", padx=(0, 10))
        self.tg_link_btn = ctk.CTkButton(
            self.tg_frame,
            text=self.t("tg_link_btn"),
            command=self._on_tg_link_click,
            width=120,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color=COLORS["text"],
        )
        self.tg_link_btn.pack(side="left")
        self._refresh_telegram_controls()
        self.after(200, self._refresh_telegram_status_async)

        # ==========================================
        # 3. FULL-WIDTH BOTTOM STATUS BAR (3 sections)
        # ==========================================
        self.footer = ctk.CTkFrame(self, height=44, corner_radius=0, fg_color="#0D1015", border_width=1, border_color="#181D26")
        self.footer.grid(row=1, column=0, columnspan=2, sticky="nsew")
        self.footer.grid_propagate(False)
        self.footer.grid_columnconfigure(0, weight=1)
        self.footer.grid_columnconfigure(1, weight=1)
        self.footer.grid_columnconfigure(2, weight=1)

        # 1. Rust Status (Left) with 3-State Status Dot Widget
        self.rust_status_frame = ctk.CTkFrame(self.footer, fg_color="transparent")
        self.rust_status_frame.grid(row=0, column=0, padx=(18, 16), pady=8, sticky="w")
        self.rust_badge_icon = ctk.CTkLabel(self.rust_status_frame, text="", image=self._icon_images["rust_badge"], width=20, height=20)
        self.rust_badge_icon.pack(side="left", padx=(0, 8))

        self.rust_status_dot = ctk.CTkLabel(self.rust_status_frame, text="●", font=ctk.CTkFont(size=11), text_color=COLORS["muted"])
        self.rust_status_dot.pack(side="left", padx=(0, 5))

        self.rust_status_label = ctk.CTkLabel(self.rust_status_frame, text="Rust: не запущен", font=ctk.CTkFont(size=12, weight="bold"), text_color=COLORS["muted"])
        self.rust_status_label.pack(side="left")
        self.rust_status_tooltip = ToolTip(self.rust_status_frame, self.t("rust_not_running"))

        # 2. Playtime (Center)
        self.playtime_frame = ctk.CTkFrame(self.footer, fg_color="transparent")
        self.playtime_frame.grid(row=0, column=1, pady=8, sticky="n")
        self.playtime_icon = ctk.CTkLabel(self.playtime_frame, text="", image=self._icon_images["clock"], width=16, height=16)
        self.playtime_icon.pack(side="left", padx=(0, 6))
        self.playtime_text = ctk.CTkLabel(self.playtime_frame, text="Время в игре: 00:00:00", font=ctk.CTkFont(size=12), text_color=COLORS["muted"])
        self.playtime_text.pack(side="left")

        # 3. Auto-reconnect status (Right)
        self.auto_reconn_frame = ctk.CTkFrame(self.footer, fg_color="transparent")
        self.auto_reconn_frame.grid(row=0, column=2, padx=(8, 18), pady=8, sticky="e")
        self.footer_armed_dot = ctk.CTkLabel(self.auto_reconn_frame, text="●", font=ctk.CTkFont(size=12), text_color=COLORS["muted"])
        self.footer_armed_dot.pack(side="left", padx=(0, 6))
        self.footer_armed_label = ctk.CTkLabel(self.auto_reconn_frame, text="Автоподключение: выключено", font=ctk.CTkFont(size=12, weight="bold"), text_color=COLORS["muted"])
        self.footer_armed_label.pack(side="left", padx=(0, 8))
        self.disarm_btn = ctk.CTkButton(self.auto_reconn_frame, text="Выключить", width=74, height=24, command=self.disarm_server, fg_color=COLORS["surface_alt"], hover_color=COLORS["border"], border_width=1, border_color=COLORS["border"])
        self.disarm_btn.pack(side="left")

        self.refresh_history_ui()
        self._refresh_session_state()
        self.show_home_frame()

    # ==========================================
    # EXCEL / SHEETS RESIZABLE TABLE COLUMNS
    # ==========================================
    def _build_table_header(self):
        hdr_frame = self.__dict__.get("table_header_frame")
        if hdr_frame is None:
            return
        for widget in hdr_frame.winfo_children():
            widget.destroy()

        self.header_cells.clear()
        self.header_dividers.clear()

        widths = self.__dict__.get("col_widths", DEFAULT_COL_WIDTHS)

        # 1. Star column
        h_star = ctk.CTkFrame(hdr_frame, width=widths.get("star", 32), height=36, fg_color="transparent")
        h_star.pack(side="left", padx=(2, 0))
        h_star.pack_propagate(False)
        ctk.CTkLabel(h_star, text="★", anchor="center", text_color=COLORS["muted"], font=ctk.CTkFont(size=11, weight="bold")).place(relx=0.5, rely=0.5, anchor="center")
        self.header_cells["star"] = h_star

        self._create_header_divider("star", "name")

        # 2. Name column
        h_name = ctk.CTkFrame(hdr_frame, width=widths.get("name", 260), height=36, fg_color="transparent")
        h_name.pack(side="left", padx=(4, 0))
        h_name.pack_propagate(False)
        ctk.CTkLabel(h_name, text="Название сервера" if self.lang == "RU" else "Server Name", anchor="w", text_color=COLORS["muted"], font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", fill="x", expand=True, pady=8)
        self.header_cells["name"] = h_name

        self._create_header_divider("name", "addr")

        # 3. Address column
        h_addr = ctk.CTkFrame(hdr_frame, width=widths.get("addr", 180), height=36, fg_color="transparent")
        h_addr.pack(side="left", padx=(4, 0))
        h_addr.pack_propagate(False)
        ctk.CTkLabel(h_addr, text="Адрес" if self.lang == "RU" else "Address", anchor="w", text_color=COLORS["muted"], font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", fill="x", expand=True, pady=8)
        self.header_cells["addr"] = h_addr

        self._create_header_divider("addr", "players")

        # 4. Players column
        h_players = ctk.CTkFrame(hdr_frame, width=widths.get("players", 76), height=36, fg_color="transparent")
        h_players.pack(side="left", padx=(4, 0))
        h_players.pack_propagate(False)
        ctk.CTkLabel(h_players, text="Игроки" if self.lang == "RU" else "Players", anchor="center", text_color=COLORS["muted"], font=ctk.CTkFont(size=11, weight="bold")).place(relx=0.5, rely=0.5, anchor="center")
        self.header_cells["players"] = h_players

        self._create_header_divider("players", "local")

        # 5. Local Status column
        h_local = ctk.CTkFrame(hdr_frame, width=widths.get("local", 56), height=36, fg_color="transparent")
        h_local.pack(side="left", padx=(4, 0))
        h_local.pack_propagate(False)
        ctk.CTkLabel(h_local, text="Статус" if self.lang == "RU" else "Status", anchor="center", text_color=COLORS["muted"], font=ctk.CTkFont(size=11, weight="bold")).place(relx=0.5, rely=0.5, anchor="center")
        self.header_cells["local"] = h_local

        self._create_header_divider("local", "action")

        # 6. Action column
        h_action = ctk.CTkFrame(hdr_frame, width=widths.get("action", 110), height=36, fg_color="transparent")
        h_action.pack(side="left", padx=(4, 6))
        h_action.pack_propagate(False)
        ctk.CTkLabel(h_action, text="Действие" if self.lang == "RU" else "Action", anchor="center", text_color=COLORS["muted"], font=ctk.CTkFont(size=11, weight="bold")).place(relx=0.5, rely=0.5, anchor="center")
        self.header_cells["action"] = h_action

    def _create_header_divider(self, left_col: str, right_col: str):
        hdr_frame = self.__dict__.get("table_header_frame")
        if hdr_frame is None:
            return
        hitbox = ctk.CTkFrame(hdr_frame, width=10, height=26, fg_color="transparent", cursor="sb_h_double_arrow")
        hitbox.pack(side="left", padx=0)
        hitbox.pack_propagate(False)

        line = ctk.CTkFrame(hitbox, width=2, height=18, fg_color=COLORS["divider"], corner_radius=1)
        line.place(relx=0.5, rely=0.5, anchor="center")

        def _on_enter(event):
            line.configure(fg_color=COLORS["divider_hover"])

        def _on_leave(event):
            line.configure(fg_color=COLORS["divider"])

        def _on_press(event):
            self._drag_col_target = left_col
            self._drag_start_x = event.x_root
            widths = self.__dict__.get("col_widths", DEFAULT_COL_WIDTHS)
            self._drag_initial_width = widths.get(left_col, DEFAULT_COL_WIDTHS.get(left_col, 100))
            self._drag_current_width = self._drag_initial_width
            self._drag_threshold_passed = False

            # Position and show Zero-Lag Ghost Guide Line
            hist_panel = self.__dict__.get("history_panel")
            ghost_line = self.__dict__.get("_ghost_guide_frame")
            ghost_badge = self.__dict__.get("_ghost_badge")
            if hist_panel is not None and ghost_line is not None:
                try:
                    local_x = event.x_root - hist_panel.winfo_rootx()
                    ghost_line.place(x=local_x, y=0, relheight=1.0, width=2)
                    ghost_line.lift()
                    if ghost_badge is not None:
                        ghost_badge.configure(text=f"{self._drag_initial_width} px")
                        badge_x = min(max(10, local_x + 8), hist_panel.winfo_width() - 70)
                        ghost_badge.place(x=badge_x, y=6)
                        ghost_badge.lift()
                except Exception:
                    pass

        def _on_motion(event):
            if not self._drag_col_target:
                return
            delta = event.x_root - self._drag_start_x
            if not self._drag_threshold_passed:
                if abs(delta) >= 2:
                    self._drag_threshold_passed = True
                else:
                    return

            min_w = MIN_WIDTHS.get(self._drag_col_target, 40)
            new_w = max(min_w, self._drag_initial_width + delta)
            self._drag_current_width = new_w

            # Move ONLY the Ghost Guide Line without touching any row/cell widgets
            hist_panel = self.__dict__.get("history_panel")
            ghost_line = self.__dict__.get("_ghost_guide_frame")
            ghost_badge = self.__dict__.get("_ghost_badge")
            if hist_panel is not None and ghost_line is not None:
                try:
                    local_x = event.x_root - hist_panel.winfo_rootx()
                    ghost_line.place(x=local_x, y=0, relheight=1.0, width=2)
                    if ghost_badge is not None:
                        ghost_badge.configure(text=f"{new_w} px")
                        badge_x = min(max(10, local_x + 8), hist_panel.winfo_width() - 70)
                        ghost_badge.place(x=badge_x, y=6)
                except Exception:
                    pass

        def _on_release(event):
            # Hide Ghost Guide Line
            ghost_line = self.__dict__.get("_ghost_guide_frame")
            if ghost_line is not None and hasattr(ghost_line, "place_forget"):
                try:
                    ghost_line.place_forget()
                except Exception:
                    pass
            ghost_badge = self.__dict__.get("_ghost_badge")
            if ghost_badge is not None and hasattr(ghost_badge, "place_forget"):
                try:
                    ghost_badge.place_forget()
                except Exception:
                    pass

            if self._drag_col_target:
                if "col_widths" not in self.__dict__:
                    self.col_widths = dict(DEFAULT_COL_WIDTHS)
                if self._drag_threshold_passed and self._drag_current_width > 0:
                    self.col_widths[self._drag_col_target] = self._drag_current_width
                    self.apply_column_widths()
                store = self.__dict__.get("history_store")
                if store is not None and hasattr(store, "set_column_widths"):
                    store.set_column_widths(self.col_widths)
                self._drag_col_target = None
                self._drag_threshold_passed = False

        def _on_double_click(event):
            self.auto_fit_column(left_col)

        for w in (hitbox, line):
            w.bind("<Enter>", _on_enter)
            w.bind("<Leave>", _on_leave)
            w.bind("<Button-1>", _on_press)
            w.bind("<B1-Motion>", _on_motion)
            w.bind("<ButtonRelease-1>", _on_release)
            w.bind("<Double-Button-1>", _on_double_click)

        self.header_dividers[left_col] = hitbox

    def auto_fit_column(self, col_key: str):
        if "col_widths" not in self.__dict__:
            self.col_widths = dict(DEFAULT_COL_WIDTHS)

        if col_key == "name":
            max_len = 16
            for row in self.__dict__.get("registered_row_cells", []):
                fn = row.get("full_name", "")
                if len(fn) > max_len:
                    max_len = len(fn)
            ideal_w = min(420, max(MIN_WIDTHS["name"], int(max_len * 7.5) + 30))
            self.col_widths["name"] = ideal_w
        elif col_key == "addr":
            self.col_widths["addr"] = 180
        elif col_key == "players":
            self.col_widths["players"] = 76
        elif col_key == "local":
            self.col_widths["local"] = 56
        elif col_key == "action":
            self.col_widths["action"] = 110
        elif col_key == "star":
            self.col_widths["star"] = 32

        self.apply_column_widths()
        store = self.__dict__.get("history_store")
        if store is not None and hasattr(store, "set_column_widths"):
            store.set_column_widths(self.col_widths)

    def apply_column_widths(self):
        widths = self.__dict__.get("col_widths", DEFAULT_COL_WIDTHS)
        cells_map = self.__dict__.get("header_cells", {})
        for col_name, cell_frame in cells_map.items():
            if getattr(cell_frame, "winfo_exists", lambda: True)():
                w = widths.get(col_name, DEFAULT_COL_WIDTHS.get(col_name, 100))
                cell_frame.configure(width=w)

        name_w = widths.get("name", 260)
        max_chars = max(8, int((name_w - 16) / 7.2))

        rows_list = self.__dict__.get("registered_row_cells", [])
        for row_data in rows_list:
            cells = row_data.get("cells", {})
            for col_name, cell_frame in cells.items():
                if col_name in widths and getattr(cell_frame, "winfo_exists", lambda: True)():
                    w = widths[col_name]
                    cell_frame.configure(width=w)

            title_lbl = row_data.get("title_label")
            full_name = row_data.get("full_name", "")
            if title_lbl and getattr(title_lbl, "winfo_exists", lambda: True)() and full_name:
                if len(full_name) > max_chars:
                    title_lbl.configure(text=f"{full_name[:max_chars-1]}…")
                else:
                    title_lbl.configure(text=full_name)

    def _nav_button(self, text, command, icon_name):
        btn = ctk.CTkButton(
            self.sidebar_frame, text=f"  {text}", image=self._icon_images[f"{icon_name}_muted"],
            compound="left", command=command, anchor="w", height=44,
            corner_radius=6, fg_color="transparent", hover_color=COLORS["surface_alt"],
            text_color=COLORS["muted"], font=ctk.CTkFont(size=13, weight="bold"),
        )
        return btn

    def _toggle_filter(self):
        filter_v = self.__dict__.get("filter_var")
        current = filter_v.get() if filter_v is not None else "Все"
        new_filter = "Избранное" if current in ("Все", "All", self.t("filter_all")) else "Все"
        if filter_v is not None:
            filter_v.set(new_filter)
        self.refresh_history_ui()

    def _on_search_key_released(self, _event):
        if self.__dict__.get("_search_timer") is not None:
            try:
                self.after_cancel(self._search_timer)
            except Exception:
                pass
        self._search_timer = self.after(200, self.refresh_history_ui)

    # ==========================================
    # 60 FPS SIDE-BY-SIDE SLIDING DRAWER ENGINE
    # ==========================================
    def toggle_activity_log(self) -> None:
        self._set_activity_log_visible(not self._log_drawer_visible, animate=True)

    def cancel_drawer_animation(self) -> None:
        if self.__dict__.get("_drawer_animation_id") is not None:
            try:
                self.after_cancel(self._drawer_animation_id)
            except Exception:
                pass
            self._drawer_animation_id = None

    def _set_activity_log_visible(self, visible: bool, animate: bool = True) -> None:
        conn_panel = self.__dict__.get("connection_panel")
        if conn_panel is None:
            return

        hist_panel = self.__dict__.get("history_panel")
        log_btn = self.__dict__.get("log_drawer_btn")
        backdrop = self.__dict__.get("overlay_backdrop")

        if not visible and self._drawer_progress <= 0.001 and self.__dict__.get("_drawer_animation_id") is None:
            self._log_drawer_visible = False
            self._drawer_progress = 0.0
            if hasattr(conn_panel, "place_forget"):
                conn_panel.place_forget()
            if backdrop is not None and hasattr(backdrop, "place_forget"):
                backdrop.place_forget()
            if hist_panel is not None and hasattr(hist_panel, "place"):
                hist_panel.place(relx=0.0, rely=0.0, relwidth=1.0, relheight=1.0)
            if log_btn is not None and getattr(log_btn, "winfo_exists", lambda: True)():
                log_btn.configure(fg_color=COLORS["input_bg"], border_color=COLORS["border"])
            return

        if visible and self._drawer_progress >= 0.999 and self.__dict__.get("_drawer_animation_id") is None:
            self._log_drawer_visible = True
            self._drawer_progress = 1.0
            if backdrop is not None and hasattr(backdrop, "place"):
                backdrop.place(relx=0.0, rely=0.0, relwidth=1.0, relheight=1.0)
            if hist_panel is not None and hasattr(hist_panel, "place"):
                hist_panel.place(relx=0.0, rely=0.0, relwidth=0.55, relheight=1.0)
            if hasattr(conn_panel, "place"):
                conn_panel.place(relx=0.56, rely=0.0, relwidth=0.44, relheight=1.0)
            if hasattr(conn_panel, "lift"):
                conn_panel.lift()
            if log_btn is not None and getattr(log_btn, "winfo_exists", lambda: True)():
                log_btn.configure(fg_color=COLORS["surface_alt"], border_color=COLORS["accent"])
            return

        self.cancel_drawer_animation()
        self._log_drawer_visible = visible

        if not animate:
            self._drawer_progress = 1.0 if visible else 0.0
            if visible:
                if backdrop is not None and hasattr(backdrop, "place"):
                    backdrop.place(relx=0.0, rely=0.0, relwidth=1.0, relheight=1.0)
                if hist_panel is not None and hasattr(hist_panel, "place"):
                    hist_panel.place(relx=0.0, rely=0.0, relwidth=0.55, relheight=1.0)
                if hasattr(conn_panel, "place"):
                    conn_panel.place(relx=0.56, rely=0.0, relwidth=0.44, relheight=1.0)
                if hasattr(conn_panel, "lift"):
                    conn_panel.lift()
                if log_btn is not None and getattr(log_btn, "winfo_exists", lambda: True)():
                    log_btn.configure(fg_color=COLORS["surface_alt"], border_color=COLORS["accent"])
            else:
                if backdrop is not None and hasattr(backdrop, "place_forget"):
                    backdrop.place_forget()
                if hasattr(conn_panel, "place_forget"):
                    conn_panel.place_forget()
                if hist_panel is not None and hasattr(hist_panel, "place"):
                    hist_panel.place(relx=0.0, rely=0.0, relwidth=1.0, relheight=1.0)
                if log_btn is not None and getattr(log_btn, "winfo_exists", lambda: True)():
                    log_btn.configure(fg_color=COLORS["input_bg"], border_color=COLORS["border"])
            return

        total_steps = 11
        interval_ms = 16
        start_prog = self._drawer_progress
        target_prog = 1.0 if visible else 0.0

        if visible:
            if backdrop is not None and hasattr(backdrop, "place"):
                backdrop.place(relx=0.0, rely=0.0, relwidth=1.0, relheight=1.0)
            if hasattr(conn_panel, "lift"):
                conn_panel.lift()
            if log_btn is not None and getattr(log_btn, "winfo_exists", lambda: True)():
                log_btn.configure(fg_color=COLORS["surface_alt"], border_color=COLORS["accent"])
        else:
            if log_btn is not None and getattr(log_btn, "winfo_exists", lambda: True)():
                log_btn.configure(fg_color=COLORS["input_bg"], border_color=COLORS["border"])

        step = 0

        def anim_step():
            nonlocal step
            if not getattr(self, "winfo_exists", lambda: True)():
                self._drawer_animation_id = None
                return
            if conn_panel is not None and not getattr(conn_panel, "winfo_exists", lambda: True)():
                self._drawer_animation_id = None
                return
            if hist_panel is not None and not getattr(hist_panel, "winfo_exists", lambda: True)():
                self._drawer_animation_id = None
                return

            step += 1
            t = step / float(total_steps)
            ease = 1.0 - (1.0 - t) ** 3
            prog = start_prog + (target_prog - start_prog) * ease
            self._drawer_progress = prog

            try:
                if prog > 0.01:
                    hist_w = 1.0 - (0.45 * prog)
                    log_relx = 1.0 - (0.44 * prog)
                    if hist_panel is not None and hasattr(hist_panel, "place"):
                        hist_panel.place(relx=0.0, rely=0.0, relwidth=hist_w, relheight=1.0)
                    if hasattr(conn_panel, "place"):
                        conn_panel.place(relx=log_relx, rely=0.0, relwidth=0.44, relheight=1.0)
                else:
                    if hasattr(conn_panel, "place_forget"):
                        conn_panel.place_forget()
                    if backdrop is not None and hasattr(backdrop, "place_forget"):
                        backdrop.place_forget()
                    if hist_panel is not None and hasattr(hist_panel, "place"):
                        hist_panel.place(relx=0.0, rely=0.0, relwidth=1.0, relheight=1.0)
            except Exception:
                self._drawer_animation_id = None
                return

            if "update_idletasks" in self.__dict__ or hasattr(self, "update_idletasks"):
                try:
                    self.update_idletasks()
                except Exception:
                    pass

            if step < total_steps:
                self._drawer_animation_id = self.after(interval_ms, anim_step)
            else:
                self._drawer_animation_id = None
                self._drawer_progress = target_prog
                try:
                    if not visible:
                        if hasattr(conn_panel, "place_forget"):
                            conn_panel.place_forget()
                        if backdrop is not None and hasattr(backdrop, "place_forget"):
                            backdrop.place_forget()
                        if hist_panel is not None and hasattr(hist_panel, "place"):
                            hist_panel.place(relx=0.0, rely=0.0, relwidth=1.0, relheight=1.0)
                    else:
                        if hist_panel is not None and hasattr(hist_panel, "place"):
                            hist_panel.place(relx=0.0, rely=0.0, relwidth=0.55, relheight=1.0)
                        if hasattr(conn_panel, "place"):
                            conn_panel.place(relx=0.56, rely=0.0, relwidth=0.44, relheight=1.0)
                except Exception:
                    pass

        anim_step()

    def _refresh_session_state(self):
        if self.__dict__.get("rust_playtime_started_at") is not None:
            elapsed = int(time.monotonic() - self.rust_playtime_started_at)
            hours, remainder = divmod(elapsed, 3600)
            minutes, seconds = divmod(remainder, 60)
            if hours > 0:
                play_str = f"{hours} ч. {minutes} мин." if self.lang == "RU" else f"{hours}h {minutes}m"
            else:
                play_str = f"{minutes} мин." if self.lang == "RU" else f"{minutes}m"
            formatted_text = f"Время в игре: {play_str}"
            is_active = True
        else:
            formatted_text = "Время в игре: 00:00:00"
            is_active = False

        if self.__dict__.get("_cached_playtime_str") != formatted_text:
            self._cached_playtime_str = formatted_text
            p_text = self.__dict__.get("playtime_text")
            if p_text is not None and getattr(p_text, "winfo_exists", lambda: True)():
                p_text.configure(text=formatted_text, text_color=COLORS["text"] if is_active else COLORS["muted"])

        self._refresh_session_state_once()
        self._session_state_after_id = self.after(1000, self._refresh_session_state)

    def _refresh_session_state_once(self):
        store = self.__dict__.get("history_store")
        if store is None:
            return
        armed = store.get_armed_server()
        if self.__dict__.get("_cached_armed_status") != armed:
            self._cached_armed_status = armed
            f_dot = self.__dict__.get("footer_armed_dot")
            f_lbl = self.__dict__.get("footer_armed_label")
            d_btn = self.__dict__.get("disarm_btn")
            if armed:
                if f_dot is not None and getattr(f_dot, "winfo_exists", lambda: True)():
                    f_dot.configure(text_color=COLORS["success"])
                if f_lbl is not None and getattr(f_lbl, "winfo_exists", lambda: True)():
                    f_lbl.configure(text="Автоподключение: включено", text_color=COLORS["text"])
                if d_btn is not None and getattr(d_btn, "winfo_exists", lambda: True)():
                    d_btn.configure(state="normal", text="Выключить")
            else:
                if f_dot is not None and getattr(f_dot, "winfo_exists", lambda: True)():
                    f_dot.configure(text_color=COLORS["muted"])
                if f_lbl is not None and getattr(f_lbl, "winfo_exists", lambda: True)():
                    f_lbl.configure(text="Автоподключение: выключено", text_color=COLORS["muted"])
                if d_btn is not None and getattr(d_btn, "winfo_exists", lambda: True)():
                    d_btn.configure(state="disabled", text="Выключить")

    def set_connection_state(self, state: str, target: Optional[str] = None):
        state_map = {
            "Idle": self.t("idle"),
            "Monitoring": self.t("monitoring_status"),
            "Launching": self.t("launching"),
            "Queueing": self.t("queue_waiting"),
            "Connected": self.t("rust_running"),
            "Launch failed": self.t("launch_failed"),
        }
        display_state = state_map.get(state, self.t(state))
        if "session_status_var" in self.__dict__:
            self.session_status_var.set(display_state)
        if state == "Idle" and "connection_progress_var" in self.__dict__:
            self.connection_progress_var.set("")
        if target and "last_connected_var" in self.__dict__:
            display_target = target if len(target) <= 42 else f"{target[:20]}…{target[-18:]}"
            self.last_connected_var.set(display_target)
            if "last_connected_tooltip" in self.__dict__:
                self.last_connected_tooltip.text = target

    def set_connection_progress(self, stage: str, elapsed: float, warning: bool = False) -> None:
        if "connection_progress_var" not in self.__dict__:
            return
        self.connection_progress_var.set(f"{stage}  •  {elapsed:.1f}s")
        if "connection_progress_label" in self.__dict__:
            self.connection_progress_label.configure(text_color=COLORS["danger"] if warning else COLORS["muted"])

    def set_connection_phase(self, phase: str):
        labels = {
            "scheduled": self.t("smart_phase_scheduled"),
            "watch": self.t("smart_phase_watch"),
            "turbo": self.t("smart_phase_turbo"),
            "waiting_for_wipe_restart": self.t("waiting_wipe_restart"),
            "launch_requested": "A2S confirmed - preparing Steam launch",
            "queued": self.t("queue_waiting"),
            "awaiting_log_confirmation": "Steam launched - waiting for Rust log",
            "connected": self.t("rust_running"),
            "cooldown": "Reconnect cooldown",
            "waiting_update": "Waiting for Rust update",
        }
        text = labels.get(phase)
        if text and "session_status_var" in self.__dict__:
            self.session_status_var.set(text)

    # ==========================================
    # 3-STATE RUST PROCESS INDICATOR
    # ==========================================
    def set_rust_status(self, state: Any) -> None:
        if self.__dict__.get("_cached_rust_status") == state:
            return
        self._cached_rust_status = state

        if state is True or state == "running":
            is_running = True
            is_starting = False
            status_text = "Rust: запущен" if self.__dict__.get("lang", "RU") == "RU" else "Rust: running"
            dot_color = COLORS["success"]
            label_color = COLORS["text"]
            tooltip_key = "rust_running"
        elif state == "starting":
            is_running = False
            is_starting = True
            status_text = "Rust: запуск..." if self.__dict__.get("lang", "RU") == "RU" else "Rust: starting..."
            dot_color = COLORS["warning"]
            label_color = COLORS["warning"]
            tooltip_key = "launching"
        else:
            is_running = False
            is_starting = False
            status_text = "Rust: не запущен" if self.__dict__.get("lang", "RU") == "RU" else "Rust: not running"
            dot_color = COLORS["muted"]
            label_color = COLORS["muted"]
            tooltip_key = "rust_not_running"

        if is_running and self.__dict__.get("rust_playtime_started_at") is None:
            self.rust_playtime_started_at = time.monotonic()
        elif not is_running and not is_starting:
            self.rust_playtime_started_at = None
            if "playtime_var" in self.__dict__:
                self.playtime_var.set("00:00:00")

        r_dot = self.__dict__.get("rust_status_dot")
        if r_dot is not None and getattr(r_dot, "winfo_exists", lambda: True)():
            r_dot.configure(text_color=dot_color)
        r_lbl = self.__dict__.get("rust_status_label")
        if r_lbl is not None and getattr(r_lbl, "winfo_exists", lambda: True)():
            r_lbl.configure(text=status_text, text_color=label_color)
        if "rust_status_tooltip" in self.__dict__:
            self.rust_status_tooltip.text = self.t(tooltip_key)

    def set_version_status(self, version: str, status: str, color: str) -> None:
        v_lbl = self.__dict__.get("version_label")
        if v_lbl is not None:
            v_lbl.configure(text=version if version.startswith("v") else f"v{version}")
        display_status = self.t(status) if status in ("Checking...", "Offline", "Latest") else status
        v_state = self.__dict__.get("version_state_label")
        if v_state is not None:
            v_state.configure(text=display_status)
        v_dot = self.__dict__.get("version_state_dot")
        if v_dot is not None:
            v_dot.configure(text_color=color)

    def update_benchmark_summary(self, run: dict):
        b_lbl = self.__dict__.get("benchmark_summary_label")
        store = self.__dict__.get("history_store")
        if b_lbl is None or store is None:
            return
        run_count = len(store.get_benchmark_runs(run.get("configuration_key", "")))
        b_lbl.configure(
            text=self.t("current_config_summary", time=run.get('total_time', 0), count=run_count)
        )

    def show_home_frame(self):
        self.home_frame.tkraise()
        self._highlight_nav(self.nav_home_btn)

    def show_bench_frame(self):
        self.bench_frame.tkraise()
        self._highlight_nav(self.nav_bench_btn)

    def show_settings_frame(self):
        self.settings_frame.tkraise()
        self._highlight_nav(self.nav_settings_btn)

    def _highlight_nav(self, active_btn):
        for button in self._nav_buttons:
            icon_name = self._nav_icon_names[button]
            button.configure(fg_color="transparent", text_color=COLORS["muted"], image=self._icon_images[f"{icon_name}_muted"])
        active_icon = self._nav_icon_names[active_btn]
        active_btn.configure(fg_color=COLORS["surface_alt"], text_color=COLORS["accent"], image=self._icon_images[f"{active_icon}_active"])

    def _on_tray_change(self):
        self.history_store.set_minimize_to_tray(self.tray_var.get())

    def _on_auto_arm_change(self):
        self.history_store.set_auto_arm(self.auto_arm_var.get())

    def _on_share_saved_servers_change(self):
        self.history_store.set_share_saved_servers(self.share_servers_var.get())

    def _on_tg_link_click(self):
        self.tg_link_btn.configure(state="disabled", text=self.t("tg_status_pairing"))
        self.tg_status_lbl.configure(text=self.t("tg_status_pairing"))

        def work():
            code = telegram_service.generate_link_code(self.lang)
            self.dispatch_ui(self._finish_telegram_link, code)

        threading.Thread(target=work, daemon=True, name="telegram-link").start()

    def _finish_telegram_link(self, code: Optional[str]) -> None:
        if not getattr(self, "winfo_exists", lambda: True)():
            return
        if not code:
            self._refresh_telegram_controls()
            self._show_telegram_link_overlay(error=True)
            if "tg_status_lbl" in self.__dict__:
                self.tg_status_lbl.configure(text=self._telegram_status_text())
            return
        if "tg_status_lbl" in self.__dict__:
            self.tg_status_lbl.configure(text=self.t("tg_status_pairing"))
        self._refresh_telegram_controls()
        self._show_telegram_link_overlay(code=code)

    def _on_tg_unlink_click(self) -> None:
        self.tg_link_btn.configure(state="disabled", text=self.t("tg_status_unlinking"))

        def unlink() -> None:
            success = telegram_service.unlink()
            self.dispatch_ui(self._finish_telegram_unlink, success)

        threading.Thread(target=unlink, daemon=True, name="telegram-unlink").start()

    def _finish_telegram_unlink(self, success: bool) -> None:
        if not getattr(self, "winfo_exists", lambda: True)():
            return
        if not success:
            self._refresh_telegram_controls()
            self._show_telegram_link_overlay(error=True)
            return
        if "tg_status_lbl" in self.__dict__:
            self.tg_status_lbl.configure(text=self._telegram_status_text())
        self._refresh_telegram_controls()

    def _refresh_telegram_controls(self) -> None:
        if "tg_link_btn" not in self.__dict__:
            return
        if telegram_service.is_linked:
            self.tg_link_btn.configure(
                text=self.t("tg_unlink_btn"), command=self._on_tg_unlink_click, state="normal"
            )
        else:
            self.tg_link_btn.configure(
                text=self.t("tg_link_btn"), command=self._on_tg_link_click, state="normal"
            )

    def _telegram_status_text(self) -> str:
        if telegram_service.display_name:
            return self.t("tg_status_linked", name=telegram_service.display_name)
        if telegram_service.is_linked:
            return self.t("tg_status_linked", name=self.t("tg_status_user"))
        if telegram_service.link_code:
            return self.t("tg_status_pairing")
        return self.t("tg_status_unlinked")

    def _refresh_telegram_status_async(self) -> None:
        def fetch_status() -> None:
            status = telegram_service.get_link_status()
            if status is not None:
                self.dispatch_ui(self._apply_telegram_status, status)
        threading.Thread(target=fetch_status, daemon=True, name="telegram-status").start()

    def _apply_telegram_status(self, _status: dict) -> None:
        if getattr(self, "winfo_exists", lambda: True)():
            if "tg_status_lbl" in self.__dict__:
                self.tg_status_lbl.configure(text=self._telegram_status_text())
            self._refresh_telegram_controls()

    def _show_telegram_link_overlay(self, code: Optional[str] = None, error: bool = False) -> None:
        self._close_telegram_link_overlay()
        overlay = ctk.CTkFrame(self, fg_color="#080A0E", corner_radius=0)
        overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        overlay.lift()
        self._tg_overlay = overlay

        card = ctk.CTkFrame(
            overlay,
            width=480,
            height=310 if code else 220,
            fg_color=COLORS["surface_card"],
            border_width=1,
            border_color=COLORS["border"],
        )
        card.place(relx=0.5, rely=0.5, anchor="center")
        card.grid_propagate(False)
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card,
            text=self.t("tg_bot_title"),
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=COLORS["text"],
        ).grid(row=0, column=0, padx=28, pady=(28, 8), sticky="w")

        message = self.t("tg_link_failed") if error else self.t("tg_overlay_intro")
        ctk.CTkLabel(
            card,
            text=message,
            justify="left",
            wraplength=410,
            font=ctk.CTkFont(size=13),
            text_color=COLORS["muted"],
        ).grid(row=1, column=0, padx=28, pady=(0, 14), sticky="w")

        if code:
            ctk.CTkLabel(
                card,
                text=self.t("tg_overlay_code_label"),
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=COLORS["muted"],
            ).grid(row=2, column=0, padx=28, sticky="w")
            code_label = ctk.CTkLabel(
                card,
                text=code,
                font=ctk.CTkFont(family="Consolas", size=24, weight="bold"),
                text_color=COLORS["accent"],
                fg_color=COLORS["canvas"],
                corner_radius=8,
                height=48,
            )
            code_label.grid(row=3, column=0, padx=28, pady=(6, 12), sticky="ew")
            code_label.bind("<Button-1>", lambda _event: self._copy_telegram_code(code, copy_button))
            copy_button = ctk.CTkButton(
                card,
                text=self.t("tg_copy_code"),
                command=lambda: self._copy_telegram_code(code, copy_button),
                width=160,
                fg_color=COLORS["accent"],
                hover_color=COLORS["accent_hover"],
                text_color=COLORS["text"],
            )
            copy_button.grid(row=4, column=0, padx=28, pady=(0, 10), sticky="w")
            close_row = 5
        else:
            close_row = 2

        ctk.CTkButton(
            card,
            text=self.t("tg_close"),
            command=self._close_telegram_link_overlay,
            width=120,
            fg_color="transparent",
            hover_color=COLORS["surface_alt"],
            border_width=1,
            border_color=COLORS["border"],
        ).grid(row=close_row, column=0, padx=28, pady=(0, 22), sticky="e")
        overlay.bind("<Escape>", lambda _event: self._close_telegram_link_overlay())
        try:
            overlay.focus_set()
        except Exception:
            pass

    def _copy_telegram_code(self, code: str, button) -> None:
        self.clipboard_clear()
        self.clipboard_append(code)
        self.update_idletasks()
        button.configure(text=self.t("tg_code_copied"))
        self.after(1400, lambda: button.winfo_exists() and button.configure(text=self.t("tg_copy_code")))

    def _close_telegram_link_overlay(self) -> None:
        overlay = self.__dict__.get("_tg_overlay")
        if overlay is not None and getattr(overlay, "winfo_exists", lambda: True)():
            try:
                overlay.destroy()
            except Exception:
                pass
        self._tg_overlay = None

    def dispatch_ui(self, callback, *args, **kwargs):
        if getattr(self, "_ui_dispatch_closing", False):
            return
        if threading.current_thread() is threading.main_thread():
            try:
                if getattr(self, "winfo_exists", lambda: True)():
                    callback(*args, **kwargs)
            except Exception as error:
                from ..core.logger import app_logger
                app_logger.warning(f"UI callback failed: {type(error).__name__}")
            return
        self._ui_callback_queue.put((callback, args, kwargs))

    def _dispatch_ui(self, callback, *args, **kwargs):
        dispatcher = getattr(self, "dispatch_ui", None)
        if callable(dispatcher) and getattr(dispatcher, "__func__", None) != MainWindow.dispatch_ui:
            dispatcher(callback, *args, **kwargs)
            return
        self.dispatch_ui(callback, *args, **kwargs)

    def _drain_ui_callbacks(self) -> None:
        while not getattr(self, "_ui_dispatch_closing", False) and getattr(self, "winfo_exists", lambda: True)():
            try:
                callback, args, kwargs = self._ui_callback_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback(*args, **kwargs)
            except Exception:
                continue
        if not getattr(self, "_ui_dispatch_closing", False) and getattr(self, "winfo_exists", lambda: True)():
            self._ui_dispatch_after_id = self.after(25, self._drain_ui_callbacks)

    def _on_swarm_change(self):
        from ..services.swarm_service import swarm_service
        is_checked = self.swarm_var.get()
        if is_checked:
            if not swarm_service.is_configured:
                self.history_store.set_swarm_enabled(False)
                swarm_service.is_enabled = False
                swarm_service._notify_status(swarm_service.configuration_status)
                return
            self.history_store.set_swarm_enabled(True)
            swarm_service.is_enabled = True
            swarm_service.start()
        else:
            self.history_store.set_swarm_enabled(False)
            swarm_service.is_enabled = False
            swarm_service.stop()

    def change_lang(self, choice: str):
        code = choice.split(" ")[0]
        self.lang = code
        self.i18n.set_lang(code)
        self.history_store.set_lang(code)
        threading.Thread(
            target=telegram_service.update_locale,
            args=(code,),
            daemon=True,
            name="telegram-locale",
        ).start()

        self.title("Rust AutoConnect")
        self.nav_home_btn.configure(text=f"  {self.t('nav_home')}")
        self.nav_bench_btn.configure(text=f"  {self.t('nav_bench')}")
        self.nav_settings_btn.configure(text=f"  {self.t('nav_settings')}")
        self.bench_title.configure(text=self.t("tab_bench"))
        self.bench_subtitle.configure(text=self.t("bench_subtitle"))
        self.bench_mode_label.configure(text=self.t("hw_benchmark"))
        self.bench_view_tabs.configure(values=[self.t("tab_run_log"), self.t("tab_online_ranking")])
        self.bench_btn.configure(text=self.t("run_test"))
        self.settings_title.configure(text=self.t("settings_title"))
        self.settings_subtitle.configure(text=self.t("settings_subtitle"))
        self.lang_label.configure(text=self.t("lang_lbl"))
        self.tray_checkbox.configure(text=self.t("tray_lbl"))
        self.swarm_checkbox.configure(text=self.t("swarm_lbl"))
        self.swarm_safety_label.configure(text=self.t("swarm_safety_note"))
        self.share_servers_checkbox.configure(text=self.t("share_saved_servers_lbl"))
        self.auto_update_settings.configure(text=self.t("check_rust_updates"))
        self.home_header.configure(text="Серверы" if code == "RU" else "Servers")
        self.search_entry.configure(placeholder_text="🔍  Поиск серверов" if code == "RU" else "🔍  Search servers")
        self.ip_entry.configure(placeholder_text="IP:PORT (например, 127.0.0.1:28015)" if code == "RU" else "IP:PORT (e.g. 127.0.0.1:28015)")
        if not getattr(self, "is_polling", False):
            self.connect_btn.configure(text="ПОДКЛЮЧИТЬСЯ" if code == "RU" else "CONNECT")
        self.auto_arm_checkbox.configure(text=self.t("auto_arm_lbl"))
        self.tg_status_lbl.configure(text=self._telegram_status_text())
        self._refresh_telegram_controls()
        self._build_table_header()
        self.refresh_history_ui()

    def t(self, key: str, **kwargs) -> str:
        i18n_mgr = self.__dict__.get("i18n")
        if i18n_mgr is not None:
            return i18n_mgr.t(key, **kwargs)
        from ..core.i18n import i18n
        return i18n.t(key, **kwargs)

    def on_auto_update_change(self):
        self.is_auto_update_enabled = self.auto_update.get()
        self.history_store.set_auto_update(self.is_auto_update_enabled)

    def _on_connect_btn_click(self):
        pass

    def _on_run_test_click(self):
        pass

    def show_benchmark_view(self, view_name: str) -> None:
        ranking_names = {self.t("tab_online_ranking"), "Online ranking", "Ranking"}
        is_ranking = view_name in ranking_names
        selected_name = self.t("tab_online_ranking") if is_ranking else self.t("tab_run_log")
        if self.bench_view_var.get() != selected_name:
            self.bench_view_var.set(selected_name)

        for view in (self.bench_log, self.bench_online_ranking):
            view.grid_remove()
        view = self.bench_online_ranking if is_ranking else self.bench_log
        view.grid(row=0, column=0, sticky="nsew")
        if is_ranking:
            self._load_online_benchmark_ranking()

    def _clear_benchmark_view(self, view) -> None:
        for widget in view.winfo_children():
            widget.destroy()

    def _load_online_benchmark_ranking(self) -> None:
        self._clear_benchmark_view(self.bench_online_ranking)
        loading = ctk.CTkLabel(self.bench_online_ranking, text=self.t("lb_load"), text_color=COLORS["muted"])
        loading.pack(anchor="w", padx=12, pady=12)

        def load() -> None:
            from ..services.leaderboard_service import leaderboard_service
            rows = leaderboard_service.fetch_configurations(limit=50)
            error = leaderboard_service.last_error
            self._dispatch_ui(self._render_online_benchmark_ranking, rows, error)

        threading.Thread(target=load, daemon=True, name="benchmark-ranking").start()

    def _render_online_benchmark_ranking(self, rows, error: Optional[str]) -> None:
        if self.bench_view_var.get() not in (self.t("tab_online_ranking"), "Online ranking", "Ranking"):
            return
        self._clear_benchmark_view(self.bench_online_ranking)
        if error:
            ctk.CTkLabel(self.bench_online_ranking, text=self.t("ranking_unavailable_fmt", err=error), text_color=COLORS["muted"]).pack(anchor="w", padx=12, pady=12)
            return
        if not rows:
            ctk.CTkLabel(self.bench_online_ranking, text=self.t("no_bench_results_yet"), text_color=COLORS["muted"]).pack(anchor="w", padx=12, pady=12)
            return
        def ranking_time(item) -> float:
            value = item.get("median_total_time", item.get("best_total_time", item.get("total_time")))
            return float(value) if isinstance(value, (int, float)) else float("inf")

        ranked_rows = sorted(rows, key=lambda item: (ranking_time(item), str(item.get("cpu", "")).casefold()))

        heading = ctk.CTkFrame(self.bench_online_ranking, fg_color="transparent", corner_radius=0)
        heading.pack(fill="x", padx=14, pady=(12, 5))
        ctk.CTkLabel(heading, text="RANKING", anchor="w", font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")
        ctk.CTkLabel(heading, text="Lower load time is better", anchor="e", text_color=COLORS["muted"], font=ctk.CTkFont(size=11)).pack(side="right")

        columns = ctk.CTkFrame(self.bench_online_ranking, fg_color=COLORS["surface"], corner_radius=3)
        columns.pack(fill="x", padx=14, pady=(0, 6))
        columns.grid_columnconfigure(1, weight=1)
        for column, text, anchor in ((0, "#", "center"), (1, "HARDWARE", "w"), (2, "BEST", "e"), (3, "RUNS", "e")):
            ctk.CTkLabel(columns, text=text, anchor=anchor, text_color=COLORS["muted"], font=ctk.CTkFont(size=10, weight="bold")).grid(row=0, column=column, padx=(10 if column == 0 else 6, 10), pady=7, sticky="ew")

        from textwrap import fill
        for index, row_data in enumerate(ranked_rows, start=1):
            total = ranking_time(row_data)
            score = f"{total:.2f}s" if total != float("inf") else "-"
            is_best = index == 1
            cpu_text = fill(str(row_data.get("cpu", "Unknown CPU")), width=22, break_long_words=False, break_on_hyphens=True)
            storage_text = fill(str(row_data.get("storage", "Unknown storage")), width=24, break_long_words=False, break_on_hyphens=True)
            row = ctk.CTkFrame(
                self.bench_online_ranking,
                fg_color=COLORS["surface"] if is_best else "transparent",
                corner_radius=4,
                border_width=1 if is_best else 0,
                border_color=COLORS["accent"] if is_best else COLORS["surface"],
            )
            row.pack(fill="x", padx=14, pady=3)
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(row, text=str(index), width=28, text_color=COLORS["accent"] if is_best else COLORS["muted"], font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, rowspan=2, padx=(10, 4), pady=8)
            ctk.CTkLabel(
                row,
                text=cpu_text,
                anchor="w",
                justify="left",
                wraplength=190,
                font=ctk.CTkFont(size=12, weight="bold"),
            ).grid(row=0, column=1, padx=6, pady=(8, 0), sticky="ew")
            ctk.CTkLabel(
                row,
                text=storage_text,
                anchor="w",
                justify="left",
                wraplength=190,
                text_color=COLORS["muted"],
                font=ctk.CTkFont(size=11),
            ).grid(row=1, column=1, padx=6, pady=(0, 8), sticky="ew")
            ctk.CTkLabel(row, text=score, anchor="e", text_color=COLORS["accent"], font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=2, rowspan=2, padx=8, sticky="e")
            ctk.CTkLabel(row, text=str(row_data.get("run_count", "-")), anchor="e", text_color=COLORS["muted"], font=ctk.CTkFont(size=11)).grid(row=0, column=3, rowspan=2, padx=(2, 12), sticky="e")

    def set_address(self, value: str) -> None:
        entry = self.__dict__.get("ip_entry")
        if entry is None:
            return
        state = entry.cget("state")
        entry.configure(state="normal")
        entry.delete(0, "end")
        entry.insert(0, value)
        entry.configure(state=state)

    def refresh_history_ui(self):
        if self.__dict__.get("_selected_server_endpoint"):
            return
        scroll = self.__dict__.get("history_scroll")
        if scroll is None:
            return
        for widget in scroll.winfo_children():
            widget.destroy()

        if "registered_row_cells" in self.__dict__:
            self.registered_row_cells.clear()

        filter_v = self.__dict__.get("filter_var")
        filter_text = filter_v.get() if filter_v is not None else "Все"
        show_favs_only = (filter_text in ("Избранное", "Favorites", self.t("filter_favorites")))

        search_e = self.__dict__.get("search_entry")
        search_query = search_e.get().lower().strip() if search_e is not None else ""

        store = self.__dict__.get("history_store")
        favorites = store.get_favorites() if store is not None else []
        armed_server = store.get_armed_server() if store is not None else None

        pop_list = [
            {"name": data["name"], "ip": pop_ip, "added_at": 0}
            for pop_ip, data in POPULAR_SERVERS_DATA.items()
        ]
        combined_items = store.get_active_history(pop_list) if store is not None else []

        visible_items = []
        for item in combined_items:
            ip = item['ip']
            display_name = item.get('name', '')
            meta_info = _get_server_metadata(ip, display_name)
            final_name = meta_info.get("name", display_name or ip)
            final_ip = meta_info.get("ip", ip)

            if search_query:
                if search_query not in final_ip.lower() and search_query not in final_name.lower():
                    continue

            is_fav = any(f.get("ip") in (ip, final_ip) for f in favorites)
            if show_favs_only and not is_fav:
                continue

            visible_items.append((final_ip, final_name, meta_info, is_fav, item.get("added_at", 0)))

        visible_items.sort(key=lambda entry: (not entry[3], -entry[4]))

        col_widths = self.__dict__.get("col_widths", DEFAULT_COL_WIDTHS)
        name_col_w = col_widths.get("name", 260)
        max_chars = max(8, int((name_col_w - 16) / 7.2))

        for final_ip, final_name, meta_info, is_fav, _ in visible_items:
            players_count = f"{meta_info.get('players', 97)}/{meta_info.get('max_players', 150)}"
            is_armed = (armed_server in (final_ip, meta_info.get("ip", "")))

            # Fixed-height row container
            row_frame = ctk.CTkFrame(scroll, height=48, corner_radius=6, fg_color="transparent")
            row_frame.pack(fill="x", padx=4, pady=1)
            row_frame.pack_propagate(False)

            row_cells = {}

            # 1. Star Favorite container
            star_box = ctk.CTkFrame(row_frame, width=col_widths.get("star", 32), height=48, fg_color="transparent")
            star_box.pack(side="left", padx=(2, 0))
            star_box.pack_propagate(False)
            fav_btn = ctk.CTkButton(
                star_box, text="", image=self._icon_images["favorite"] if is_fav else self._icon_images["favorite_off"],
                width=24, height=30, corner_radius=4, fg_color="transparent", hover_color=COLORS["surface_alt"],
                command=lambda i=final_ip, n=final_name: self.toggle_favorite(i, n),
            )
            fav_btn.place(relx=0.5, rely=0.5, anchor="center")
            ToolTip(fav_btn, self.t("toggle_fav_tooltip"))
            row_cells["star"] = star_box

            # Cell divider
            div1 = ctk.CTkFrame(row_frame, width=10, height=26, fg_color="transparent")
            div1.pack(side="left", padx=0)
            ctk.CTkFrame(div1, width=1, height=18, fg_color=COLORS["divider_subtle"]).place(relx=0.5, rely=0.5, anchor="center")

            # 2. Server Name container
            name_box = ctk.CTkFrame(row_frame, width=col_widths.get("name", 260), height=48, fg_color="transparent")
            name_box.pack(side="left", padx=(4, 0))
            name_box.pack_propagate(False)
            title_display = final_name if len(final_name) <= max_chars else f"{final_name[:max_chars-1]}…"
            title_label = ctk.CTkLabel(
                name_box, text=title_display, anchor="w",
                font=ctk.CTkFont(size=12, weight="bold"), text_color=COLORS["text"],
            )
            title_label.pack(side="left", fill="x", expand=True, pady=12)
            ToolTip(title_label, final_name)
            row_cells["name"] = name_box

            # Cell divider
            div2 = ctk.CTkFrame(row_frame, width=10, height=26, fg_color="transparent")
            div2.pack(side="left", padx=0)
            ctk.CTkFrame(div2, width=1, height=18, fg_color=COLORS["divider_subtle"]).place(relx=0.5, rely=0.5, anchor="center")

            # 3. Address container
            addr_box = ctk.CTkFrame(row_frame, width=col_widths.get("addr", 180), height=48, fg_color="transparent")
            addr_box.pack(side="left", padx=(4, 0))
            addr_box.pack_propagate(False)
            ip_display = final_ip if len(final_ip) <= 19 else f"{final_ip[:17]}…"
            addr_label = ctk.CTkLabel(
                addr_box, text=ip_display, anchor="w",
                font=ctk.CTkFont(family="Consolas", size=11), text_color=COLORS["muted"],
            )
            addr_label.pack(side="left", fill="x", expand=True, pady=12)
            copy_btn = ctk.CTkButton(
                addr_box, text="", image=self._icon_images["copy"], width=20, height=20, corner_radius=4,
                fg_color="transparent", hover_color=COLORS["surface_alt"],
                command=lambda value=final_ip: self._copy_server_card_text(value),
            )
            copy_btn.pack(side="right", padx=(2, 0), pady=14)
            ToolTip(copy_btn, "Копировать адрес" if self.lang in ("RU", "UK") else "Copy address")
            row_cells["addr"] = addr_box

            # Cell divider
            div3 = ctk.CTkFrame(row_frame, width=10, height=26, fg_color="transparent")
            div3.pack(side="left", padx=0)
            ctk.CTkFrame(div3, width=1, height=18, fg_color=COLORS["divider_subtle"]).place(relx=0.5, rely=0.5, anchor="center")

            # 4. Players container
            players_box = ctk.CTkFrame(row_frame, width=col_widths.get("players", 76), height=48, fg_color="transparent")
            players_box.pack(side="left", padx=(4, 0))
            players_box.pack_propagate(False)
            players_label = ctk.CTkLabel(
                players_box, text=players_count, anchor="center",
                text_color=COLORS["text_secondary"], font=ctk.CTkFont(size=11),
            )
            players_label.place(relx=0.5, rely=0.5, anchor="center")
            row_cells["players"] = players_box

            # Cell divider
            div4 = ctk.CTkFrame(row_frame, width=10, height=26, fg_color="transparent")
            div4.pack(side="left", padx=0)
            ctk.CTkFrame(div4, width=1, height=18, fg_color=COLORS["divider_subtle"]).place(relx=0.5, rely=0.5, anchor="center")

            # 5. Local Status Dot container
            status_box = ctk.CTkFrame(row_frame, width=col_widths.get("local", 56), height=48, fg_color="transparent")
            status_box.pack(side="left", padx=(4, 0))
            status_box.pack_propagate(False)
            status_dot = ctk.CTkLabel(
                status_box, text="●", anchor="center",
                text_color=COLORS["success"], font=ctk.CTkFont(size=12),
            )
            status_dot.place(relx=0.5, rely=0.5, anchor="center")
            row_cells["local"] = status_box

            # Cell divider
            div5 = ctk.CTkFrame(row_frame, width=10, height=26, fg_color="transparent")
            div5.pack(side="left", padx=0)
            ctk.CTkFrame(div5, width=1, height=18, fg_color=COLORS["divider_subtle"]).place(relx=0.5, rely=0.5, anchor="center")

            # 6. Action container (AutoArm, Delete, Connect)
            action_box = ctk.CTkFrame(row_frame, width=col_widths.get("action", 110), height=48, fg_color="transparent")
            action_box.pack(side="left", padx=(4, 6))
            action_box.pack_propagate(False)

            arm_row_btn = ctk.CTkButton(
                action_box, text="",
                image=self._icon_images["armed"] if is_armed else self._icon_images["shield"],
                width=28, height=28, corner_radius=6,
                fg_color=COLORS["surface_card"] if is_armed else "transparent",
                border_width=1 if is_armed else 0,
                border_color=COLORS["success"] if is_armed else COLORS["border"],
                hover_color=COLORS["surface_alt"],
                command=lambda i=final_ip, n=final_name: self.toggle_armed(i, n),
            )
            arm_row_btn.pack(side="left", padx=(0, 4), pady=10)
            ToolTip(arm_row_btn, "Автоподключение: включено" if is_armed else "Взвести автоподключение (AutoArm)")

            del_row_btn = ctk.CTkButton(
                action_box, text="", image=self._icon_images["trash"], width=28, height=28,
                corner_radius=6, fg_color="transparent", hover_color=COLORS["surface_alt"],
                command=lambda i=final_ip, n=final_name: self.remove_from_history(i, n),
            )
            del_row_btn.pack(side="left", padx=(0, 4), pady=10)
            ToolTip(del_row_btn, "Удалить сервер из списка")

            connect_row_btn = ctk.CTkButton(
                action_box, text="", image=self._icon_images["connect"], width=28, height=28,
                corner_radius=6, fg_color=COLORS["surface_card"], hover_color=COLORS["border"],
                command=lambda i=final_ip: self._connect_history_server(i),
            )
            connect_row_btn.pack(side="left", pady=10)
            ToolTip(connect_row_btn, "Подключиться")
            row_cells["action"] = action_box

            if "registered_row_cells" in self.__dict__:
                self.registered_row_cells.append({
                    "cells": row_cells,
                    "title_label": title_label,
                    "full_name": final_name,
                    "ip": final_ip,
                })

            # Right-Click Context Menu
            def _popup_menu(event, cur_ip=final_ip, cur_name=final_name, cur_armed=is_armed):
                menu = tk.Menu(self, tearoff=0, bg="#1A1E27", fg="#FFFFFF", activebackground=COLORS["accent"], activeforeground="#FFFFFF", bd=1, relief="solid")
                menu.add_command(label="▶  " + ("Подключиться" if self.lang == "RU" else "Connect"), command=lambda: self._connect_history_server(cur_ip))
                arm_lbl = ("🛡️  Снять автоподключение" if cur_armed else "🛡️  Взвести автоподключение") if self.lang == "RU" else ("🛡️  Disarm AutoConnect" if cur_armed else "🛡️  Arm AutoConnect")
                menu.add_command(label=arm_lbl, command=lambda: self.toggle_armed(cur_ip, cur_name))
                menu.add_separator()
                menu.add_command(label="📋  " + ("Копировать адрес" if self.lang == "RU" else "Copy address"), command=lambda: self._copy_server_card_text(cur_ip))
                menu.add_command(label="ℹ  " + ("Информация о сервере" if self.lang == "RU" else "Server details"), command=lambda: self.show_server_card(cur_ip))
                menu.add_separator()
                menu.add_command(label="🗑️  " + ("Удалить из списка" if self.lang == "RU" else "Delete server"), command=lambda: self.remove_from_history(cur_ip, cur_name))
                try:
                    menu.tk_popup(event.x_root, event.y_root)
                finally:
                    menu.grab_release()

            for widget in (row_frame, name_box, title_label, addr_box, addr_label, players_box, players_label, status_box, status_dot):
                widget.bind("<Button-1>", lambda event, i=final_ip: self.show_server_card(i))
                widget.bind("<Button-3>", _popup_menu)
                widget.bind("<Button-2>", _popup_menu)
                widget.bind("<Enter>", lambda event, rf=row_frame: rf.configure(fg_color=COLORS["surface_hover"]))
                widget.bind("<Leave>", lambda event, rf=row_frame: rf.configure(fg_color="transparent"))

    def toggle_armed(self, ip_port: str, name: str = ""):
        import tkinter.messagebox as messagebox
        store = self.__dict__.get("history_store")
        if store is None:
            return
        is_currently_armed = (store.get_armed_server() == ip_port)
        if not is_currently_armed:
            msg = self.t("arm_warning_msg")
            if not messagebox.askyesno(self.t("arm_warning_title"), msg, parent=self):
                return

        store.set_armed_server(ip_port)
        self.refresh_history_ui()
        if store.get_armed_server() == ip_port:
            self.select_history(ip_port)
        self._refresh_session_state_once()

    def disarm_server(self):
        store = self.__dict__.get("history_store")
        if store is None:
            return
        armed = store.get_armed_server()
        if not armed:
            return
        store.set_armed_server(armed)
        self.refresh_history_ui()
        self._refresh_session_state_once()

    def toggle_favorite(self, ip_port: str, name: str):
        store = self.__dict__.get("history_store")
        if store is not None:
            store.toggle_favorite(ip_port, name)
            self.refresh_history_ui()

    def edit_server_metadata(self, ip_port: str):
        self.show_server_card(ip_port)

    def export_server_library(self):
        from tkinter import filedialog, messagebox

        destination = filedialog.asksaveasfilename(
            parent=self,
            title=self.t("export_lib_title"),
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt")],
        )
        if not destination:
            return
        try:
            with open(destination, "w", encoding="utf-8") as file:
                file.write(self.history_store.export_server_text())
            messagebox.showinfo(self.t("export_complete"), self.t("export_complete_msg"), parent=self)
        except OSError as error:
            messagebox.showerror(self.t("export_failed"), self.t("export_failed_msg", err=type(error).__name__), parent=self)

    def import_server_library(self):
        from tkinter import filedialog, messagebox
        import json

        source = filedialog.askopenfilename(
            parent=self,
            title=self.t("import_lib_title"),
            filetypes=[("Text files", "*.txt"), ("Legacy JSON files", "*.json")],
        )
        if not source:
            return
        try:
            with open(source, "r", encoding="utf-8") as file:
                contents = file.read()
            if source.lower().endswith(".json"):
                added, updated = self.history_store.import_server_library(json.loads(contents))
                unresolved = 0
            else:
                added, updated, unresolved = self.history_store.import_server_text(contents)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            messagebox.showerror(self.t("import_failed"), self.t("import_failed_msg", err=type(error).__name__), parent=self)
            return
        self.refresh_history_ui()
        messagebox.showinfo(
            self.t("import_complete"),
            self.t("import_complete_msg", added=added, updated=updated, unresolved=unresolved),
            parent=self,
        )

    def remove_from_history(self, ip_port: str, display_name: str = ""):
        import tkinter.messagebox as messagebox

        name = display_name or ip_port
        if not messagebox.askyesno(
            self.t("delete_server_title"),
            self.t("delete_server_msg", name=name),
            parent=self,
        ):
            return
        self.history_store.remove_from_history(ip_port)
        self.refresh_history_ui()

    def start_inline_edit(self, frame, btn, ip, current_name):
        btn.pack_forget()
        entry = ctk.CTkEntry(frame, font=ctk.CTkFont(family="Arial", size=14))
        entry.insert(0, current_name)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        entry.focus()

        saving = False

        def save_inline(event=None):
            nonlocal saving
            if saving:
                return
            saving = True
            try:
                entry.unbind("<FocusOut>")
                entry.unbind("<Return>")
                if hasattr(entry, "_entry"):
                    entry._entry.unbind("<FocusOut>")
                    entry._entry.unbind("<Return>")
            except Exception:
                pass
            new_name = entry.get().strip()
            if new_name:
                self.history_store.update_server_name(ip, new_name)
                current_text = self.ip_entry.get()
                if current_text.endswith(f"({ip})"):
                    self.set_address(f"{new_name} ({ip})")
            self.refresh_history_ui()

        entry.bind("<Return>", save_inline)
        entry.bind("<FocusOut>", save_inline)
        if hasattr(entry, "_entry"):
            entry._entry.bind("<Return>", save_inline)
            entry._entry.bind("<FocusOut>", save_inline)
        return save_inline

    def select_history(self, ip_port: str):
        self.set_address(ip_port)

    @staticmethod
    def _safe_external_url(value: str) -> str:
        if not isinstance(value, str):
            return ""
        parsed = urlparse(value.strip())
        return value.strip() if parsed.scheme in {"http", "https"} and parsed.netloc else ""

    def _copy_server_card_text(self, value: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(value)
        self.update_idletasks()

    def _open_server_card_url(self, value: str) -> None:
        safe = self._safe_external_url(value)
        if safe:
            webbrowser.open_new_tab(safe)

    def hide_server_card(self) -> None:
        self._hide_server_card(clear_selection=True)

    def _hide_server_card(self, *, clear_selection: bool) -> None:
        if clear_selection:
            self._selected_server_endpoint = None
            self._selected_server_snapshot = None
        escape_id = self.__dict__.get("_server_card_escape_id")
        self._server_card_escape_id = None
        if escape_id:
            try:
                self.unbind("<Escape>", escape_id)
            except Exception:
                pass

        card = self.__dict__.get("_server_card_window")
        if card is not None and getattr(card, "winfo_exists", lambda: True)():
            try:
                card.grab_release()
            except Exception:
                pass
            try:
                card.destroy()
            except Exception:
                pass
        self._server_card_window = None

        overlay = self.__dict__.get("_server_card_overlay")
        if overlay is not None and getattr(overlay, "winfo_exists", lambda: True)():
            try:
                overlay.destroy()
            except Exception:
                pass
        self._server_card_overlay = None

    def show_server_card(self, ip_port: str, snapshot=None, *, loading: bool = False) -> None:
        item = next((entry for entry in self.history_store.get_history() if entry.get("ip") == ip_port), None)
        item_name = item.get("name", "") if item else ""
        meta_info = _get_server_metadata(ip_port, item_name)

        self._hide_server_card(clear_selection=False)
        self._selected_server_endpoint = ip_port

        if snapshot is None:
            snapshot = SimpleNamespace(
                name=meta_info.get("name", ip_port),
                players=meta_info.get("players", 97),
                max_players=meta_info.get("max_players", 150),
                map_name=meta_info.get("map_name", "Procedural Map"),
                map_size=meta_info.get("map_size", 4000),
                description=meta_info.get("description", ""),
                website=meta_info.get("website", ""),
                discord=meta_info.get("discord", ""),
                rules=meta_info.get("rules", ""),
                rustmaps_url=meta_info.get("rustmaps_url", ""),
                banner_url="",
                status="online",
                links=(meta_info.get("discord", ""), meta_info.get("website", ""), meta_info.get("rules", "")),
            )

        self._selected_server_snapshot = snapshot

        # Dimmed backdrop
        overlay = ctk.CTkFrame(self, fg_color="#080A0E", corner_radius=0)
        overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        overlay.lift()
        self._server_card_overlay = overlay
        overlay.bind("<Button-1>", lambda event: self.hide_server_card())

        # Centered modal card
        card = ctk.CTkFrame(
            overlay, width=620, height=560, fg_color="#13171F",
            corner_radius=12, border_width=1, border_color="#28303E",
        )
        card.place(relx=0.5, rely=0.5, anchor="center")
        card.pack_propagate(False)
        card.lift()
        card.bind("<Button-1>", lambda event: "break")
        try:
            card.grab_set()
        except Exception:
            pass
        self._server_card_window = card

        # Top atmospheric Rust sunset monument banner
        banner_img = _generate_rust_sunset_banner(width=620, height=144)
        banner_ctk_img = ctk.CTkImage(light_image=banner_img, dark_image=banner_img, size=(620, 144))
        hero_label = ctk.CTkLabel(card, text="", image=banner_ctk_img, height=144, corner_radius=10)
        hero_label.pack(fill="x", padx=0, pady=(0, 0))

        # Close button in top-right corner
        close_btn = ctk.CTkButton(
            card, text="✕", width=30, height=30, corner_radius=15,
            command=self.hide_server_card, fg_color="#1A202A", hover_color=COLORS["accent"],
            text_color=COLORS["text"], font=ctk.CTkFont(size=13, weight="bold"),
        )
        close_btn.place(relx=1.0, x=-14, y=14, anchor="ne")
        close_btn.lift()

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=22, pady=(12, 16))

        # Title
        title_text = getattr(snapshot, "name", "") or ip_port
        title_lbl = ctk.CTkLabel(body, text=title_text, font=ctk.CTkFont(size=20, weight="bold"), text_color=COLORS["text"], anchor="center")
        title_lbl.pack(fill="x", pady=(0, 2))

        # Address + Copy
        addr_row = ctk.CTkFrame(body, fg_color="transparent")
        addr_row.pack(anchor="center", pady=(0, 6))
        addr_lbl = ctk.CTkLabel(addr_row, text=ip_port, font=ctk.CTkFont(family="Consolas", size=12), text_color=COLORS["muted"])
        addr_lbl.pack(side="left")
        copy_icon_btn = ctk.CTkButton(
            addr_row, text="", image=self._icon_images["copy"], width=20, height=20, corner_radius=3,
            fg_color="transparent", hover_color=COLORS["surface_alt"],
            command=lambda: self._copy_server_card_text(ip_port),
        )
        copy_icon_btn.pack(side="left", padx=(4, 0))

        # Quick Status row
        players_val = f"{getattr(snapshot, 'players', None) or 97} / {getattr(snapshot, 'max_players', None) or 150}"
        quick_info_row = ctk.CTkFrame(body, fg_color="transparent")
        quick_info_row.pack(anchor="center", pady=(0, 10))
        ctk.CTkLabel(quick_info_row, text=f"👤  {players_val} игроков", font=ctk.CTkFont(size=12), text_color=COLORS["muted"]).pack(side="left", padx=(0, 12))
        ctk.CTkLabel(quick_info_row, text="|", font=ctk.CTkFont(size=12), text_color=COLORS["border"]).pack(side="left", padx=(0, 12))
        ctk.CTkLabel(quick_info_row, text="●", font=ctk.CTkFont(size=11), text_color=COLORS["success"]).pack(side="left", padx=(0, 4))
        ctk.CTkLabel(quick_info_row, text="Локальный: онлайн", font=ctk.CTkFont(size=12), text_color=COLORS["muted"]).pack(side="left")

        # 3 Feature Stat Tiles
        stats_frame = ctk.CTkFrame(body, fg_color="transparent")
        stats_frame.pack(fill="x", pady=(0, 12))
        for col_idx in range(3):
            stats_frame.grid_columnconfigure(col_idx, weight=1)

        tile1 = ctk.CTkFrame(stats_frame, fg_color=COLORS["surface_alt"], corner_radius=8, border_width=1, border_color=COLORS["border"])
        tile1.grid(row=0, column=0, padx=(0, 6), sticky="nsew")
        ctk.CTkLabel(tile1, text="", image=self._icon_images["players"], width=22, height=22).pack(side="left", padx=(12, 8), pady=12)
        tile1_text = ctk.CTkFrame(tile1, fg_color="transparent")
        tile1_text.pack(side="left", fill="both", expand=True, pady=8)
        ctk.CTkLabel(tile1_text, text="Игроки", font=ctk.CTkFont(size=11), text_color=COLORS["muted"], anchor="w").pack(anchor="w")
        ctk.CTkLabel(tile1_text, text=players_val, font=ctk.CTkFont(size=13, weight="bold"), text_color=COLORS["text"], anchor="w").pack(anchor="w")

        map_name_val = getattr(snapshot, "map_name", "Procedural Map") or "Procedural Map"
        tile2 = ctk.CTkFrame(stats_frame, fg_color=COLORS["surface_alt"], corner_radius=8, border_width=1, border_color=COLORS["border"])
        tile2.grid(row=0, column=1, padx=4, sticky="nsew")
        ctk.CTkLabel(tile2, text="", image=self._icon_images["map"], width=22, height=22).pack(side="left", padx=(12, 8), pady=12)
        tile2_text = ctk.CTkFrame(tile2, fg_color="transparent")
        tile2_text.pack(side="left", fill="both", expand=True, pady=8)
        ctk.CTkLabel(tile2_text, text="Карта", font=ctk.CTkFont(size=11), text_color=COLORS["muted"], anchor="w").pack(anchor="w")
        ctk.CTkLabel(tile2_text, text=map_name_val[:16], font=ctk.CTkFont(size=13, weight="bold"), text_color=COLORS["text"], anchor="w").pack(anchor="w")

        raw_size = getattr(snapshot, "map_size", 4000) or 4000
        size_display = f"{float(raw_size)/1000:.1f} km" if isinstance(raw_size, (int, float)) and raw_size > 100 else str(raw_size)
        tile3 = ctk.CTkFrame(stats_frame, fg_color=COLORS["surface_alt"], corner_radius=8, border_width=1, border_color=COLORS["border"])
        tile3.grid(row=0, column=2, padx=(6, 0), sticky="nsew")
        ctk.CTkLabel(tile3, text="", image=self._icon_images["cube"], width=22, height=22).pack(side="left", padx=(12, 8), pady=12)
        tile3_text = ctk.CTkFrame(tile3, fg_color="transparent")
        tile3_text.pack(side="left", fill="both", expand=True, pady=8)
        ctk.CTkLabel(tile3_text, text="Размер", font=ctk.CTkFont(size=11), text_color=COLORS["muted"], anchor="w").pack(anchor="w")
        ctk.CTkLabel(tile3_text, text=size_display, font=ctk.CTkFont(size=13, weight="bold"), text_color=COLORS["text"], anchor="w").pack(anchor="w")

        desc_text = getattr(snapshot, "description", "") or "Классический Rust сервер. Еженедельный вайп по пятницам. Активное комьюнити, баланс между выживанием и PvP. Удачи и приятной игры!"
        desc_box = ctk.CTkLabel(
            body, text=desc_text, justify="left", wraplength=560,
            text_color=COLORS["muted"], font=ctk.CTkFont(size=12),
        )
        desc_box.pack(fill="x", pady=(0, 10), anchor="w")

        # Community links
        links_frame = ctk.CTkFrame(body, fg_color="transparent")
        links_frame.pack(fill="x", pady=(0, 14), anchor="w")

        discord_url = getattr(snapshot, "discord", "") or "https://discord.gg"
        website_url = getattr(snapshot, "website", "") or "https://rustafied.com"
        rules_url = getattr(snapshot, "rules", "") or "https://rustafied.com/rules"

        d_btn = ctk.CTkButton(
            links_frame, text="Discord", image=self._icon_images["discord"], compound="left",
            width=90, height=28, fg_color="transparent", hover_color=COLORS["surface_alt"],
            text_color=COLORS["muted"], font=ctk.CTkFont(size=12),
            command=lambda: self._open_server_card_url(discord_url),
        )
        d_btn.pack(side="left", padx=(0, 14))

        w_btn = ctk.CTkButton(
            links_frame, text="Веб-сайт", image=self._icon_images["website"], compound="left",
            width=90, height=28, fg_color="transparent", hover_color=COLORS["surface_alt"],
            text_color=COLORS["muted"], font=ctk.CTkFont(size=12),
            command=lambda: self._open_server_card_url(website_url),
        )
        w_btn.pack(side="left", padx=(0, 14))

        r_btn = ctk.CTkButton(
            links_frame, text="Правила", image=self._icon_images["rules"], compound="left",
            width=90, height=28, fg_color="transparent", hover_color=COLORS["surface_alt"],
            text_color=COLORS["muted"], font=ctk.CTkFont(size=12),
            command=lambda: self._open_server_card_url(rules_url),
        )
        r_btn.pack(side="left")

        # Action Buttons
        actions_row = ctk.CTkFrame(body, fg_color="transparent")
        actions_row.pack(fill="x", pady=(4, 0))
        actions_row.grid_columnconfigure(0, weight=1)
        actions_row.grid_columnconfigure(1, weight=1)

        map_link = getattr(snapshot, "rustmaps_url", "") or "https://rustmaps.com"
        open_map_btn = ctk.CTkButton(
            actions_row, text="Открыть карту", height=42, corner_radius=6,
            fg_color=COLORS["surface_alt"], hover_color=COLORS["border"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text"], font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: self._open_server_card_url(map_link),
        )
        open_map_btn.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        connect_modal_btn = ctk.CTkButton(
            actions_row, text="ПОДКЛЮЧИТЬСЯ", height=42, corner_radius=6,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            text_color=COLORS["text"], font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: (self.hide_server_card(), self._connect_history_server(ip_port)),
        )
        connect_modal_btn.grid(row=0, column=1, padx=(8, 0), sticky="ew")

        self._server_card_escape_id = self.bind(
            "<Escape>", lambda _event: self.hide_server_card(), add="+",
        )

        banner_url = getattr(snapshot, "banner_url", "")
        if banner_url:
            self._load_server_card_banner(card, hero_label, banner_url)

    def _load_server_card_banner(self, card, label, url: str) -> None:
        def work() -> None:
            try:
                request = urllib.request.Request(url, headers={"Accept": "image/*"})
                with urllib.request.urlopen(request, timeout=4) as response:
                    data = response.read(2_000_001)
                if len(data) > 2_000_000:
                    return
                image = Image.open(io.BytesIO(data)).convert("RGB")
                image.thumbnail((620, 144), Image.Resampling.LANCZOS)
            except (OSError, ValueError):
                return
            self.dispatch_ui(self._apply_server_card_banner, card, label, image)
        threading.Thread(target=work, daemon=True, name="server-card-banner").start()

    @staticmethod
    def _apply_server_card_banner(card, label, image) -> None:
        try:
            alive = getattr(card, "winfo_exists", lambda: True)() and getattr(label, "winfo_exists", lambda: True)()
        except tk.TclError:
            return
        if not alive:
            return
        ctk_image = ctk.CTkImage(light_image=image, dark_image=image, size=image.size)
        label.configure(image=ctk_image)
        label._server_card_image = ctk_image

    def _connect_history_server(self, ip_port: str):
        self.set_address(ip_port)
        self._on_connect_btn_click()

    def get_target_ip(self) -> str:
        entry = self.__dict__.get("ip_entry")
        if entry is None:
            return ""
        target = entry.get().strip()
        if "(" in target and ")" in target:
            target = target.split("(")[-1].replace(")", "").strip()
        if target.lower().startswith("client.connect "):
            target = target.split(None, 1)[1].strip()
        return target

    def update_entry(self, text: str):
        self.set_address(text)

    def log(self, msg: str, color: Optional[str] = None):
        from ..core.logger import app_logger
        app_logger.info(msg)
        ts = time.strftime("[%H:%M:%S]")
        textbox = self.__dict__.get("log_textbox")
        if textbox is None:
            return
        textbox.configure(state="normal")

        textbox.insert("end", f"{ts} ")

        if color:
            tag_name = f"color_{color.replace('#', '')}"
            textbox.tag_config(tag_name, foreground=color)
            textbox.insert("end", f"{msg}\n", tag_name)
        else:
            textbox.insert("end", f"{msg}\n")

        lines = int(textbox.index('end-1c').split('.')[0])
        if lines > 500:
            textbox.delete('1.0', f'{lines - 500 + 1}.0')
        auto_scr = self.__dict__.get("auto_scroll")
        if auto_scr is not None and auto_scr.get():
            textbox.see("end")
        textbox.configure(state="disabled")

    def clear_log(self):
        textbox = self.__dict__.get("log_textbox")
        if textbox is not None:
            textbox.configure(state="normal")
            textbox.delete("1.0", "end")
            textbox.configure(state="disabled")

    def log_safe(self, msg: str, color: Optional[str] = None):
        self.dispatch_ui(self.log, msg, color=color)

    def create_tray_image(self):
        image = Image.new('RGB', (64, 64), color=(233, 75, 22))
        d = ImageDraw.Draw(image)
        d.text((24, 24), "R", fill=(255, 255, 255))
        return image

    def on_unmap(self, event):
        if event.widget == self and self.state() == 'iconic':
            store = self.__dict__.get("history_store")
            if store is not None and store.get_minimize_to_tray():
                self.withdraw_window()

    def _on_close_requested(self):
        store = self.__dict__.get("history_store")
        if store is not None and store.get_minimize_to_tray():
            self.withdraw_window()
        else:
            self.shutdown()

    def withdraw_window(self):
        self.withdraw()
        if not self.tray_icon:
            image = self.create_tray_image()
            menu = pystray.Menu(
                pystray.MenuItem(self.t("tray_show"), self.show_window, default=True),
                pystray.MenuItem(self.t("tray_quit"), self.quit_window)
            )
            self.tray_icon = pystray.Icon("RustAutoConnect", image, "Rust AutoConnect", menu)
            self.tray_icon.run_detached()

    def show_window(self, icon=None, item=None):
        tray = self.__dict__.get("tray_icon")
        if tray is not None:
            try:
                tray.stop()
            except Exception:
                pass
            self.tray_icon = None
        self.after(0, self.deiconify)

    def quit_window(self, icon=None, item=None):
        tray = self.__dict__.get("tray_icon")
        if tray is not None:
            try:
                tray.stop()
            except Exception:
                pass
            self.tray_icon = None
        self.after(0, self.shutdown)

    def shutdown(self):
        self._ui_dispatch_closing = True
        dispatch_id = self.__dict__.get("_ui_dispatch_after_id")
        if dispatch_id is not None:
            try:
                self.after_cancel(dispatch_id)
            except Exception:
                pass
            self._ui_dispatch_after_id = None

        search_id = self.__dict__.get("_search_timer")
        if search_id is not None:
            try:
                self.after_cancel(search_id)
            except Exception:
                pass
            self._search_timer = None

        session_id = self.__dict__.get("_session_state_after_id")
        if session_id is not None:
            try:
                self.after_cancel(session_id)
            except Exception:
                pass
            self._session_state_after_id = None

        self.cancel_drawer_animation()

        tray = self.__dict__.get("tray_icon")
        if tray is not None:
            try:
                tray.stop()
            except Exception:
                pass
            self.tray_icon = None

        try:
            self.destroy()
        except Exception:
            pass
