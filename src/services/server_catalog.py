# -*- coding: utf-8 -*-
"""Curated/fallback server metadata, independent of any UI toolkit.

Moved out of src/gui/main_window.py so the default web app (src/web/bridge.py)
no longer has to import the legacy Tkinter GUI module just to read this data.

Community links (website/discord/rules) and the RustMaps viewer link used to
live here as hand-typed guesses (verified 2026-09-04: several were simply
wrong, e.g. a fabricated Discord invite for the official Facepunch server).
They are no longer read from this file at all - src/web/bridge.py now sources
them live from server_intelligence_service, which parses the server
operator's own real listing instead of guessing.
"""
import hashlib

POPULAR_SERVERS_DATA = {
    "193.25.252.119:28015": {
        "name": "RustVikings | Solo/Duo | Wednesdays | FULLWIPE",
        "ip": "193.25.252.119:28015",
        "players": 148,
        "max_players": 200,
        "map_name": "Procedural Map",
        "map_size": 4000,
        "description": "RustVikings Solo/Duo weekly server. Fast gathering, balanced loot tables and 24/7 active admin team.",
    },
    "194.54.88.101:28024": {
        "name": "Survivors.gg #5 [ 2x Solo/Duo/Trio ] FULLWIPED",
        "ip": "194.54.88.101:28024",
        "players": 192,
        "max_players": 250,
        "map_name": "Barren",
        "map_size": 3750,
        "description": "Survivors.gg high performance 2x vanilla server. Low ping, DDoS protection and weekly wipes.",
    },
    "195.60.166.73:28015": {
        "name": "Repulsion - 2x Solo/Duo/Trio | FULLWIPE",
        "ip": "195.60.166.73:28015",
        "players": 165,
        "max_players": 200,
        "map_name": "Procedural Map",
        "map_size": 4000,
        "description": "Repulsion 2x Vanilla experience with shared blueprints and active anti-cheat monitoring.",
    },
    "64.40.9.41:28015": {
        "name": "Rustafied.com - EU Small - Friday",
        "ip": "64.40.9.41:28015",
        "players": 97,
        "max_players": 150,
        "map_name": "Procedural Map",
        "map_size": 4000,
        "description": "Classic Rustafied server with free-to-play privileges. Weekly wipe on Fridays.",
    },
    "151.242.106.41:28010": {
        "name": "WARBANDITS.GG EU 2X |Solo/Duo|X2 JUST WIPED",
        "ip": "151.242.106.41:28010",
        "players": 210,
        "max_players": 250,
        "map_name": "Procedural Map",
        "map_size": 4250,
        "description": "Warbandits 2x Main EU server. High tickrate, custom monuments and active community.",
    },
}

# Hostname -> (display name, canonical ip:port) for a small number of servers
# whose saved address is a hostname rather than a bare IP. Verified live
# (2026-09-04) before being listed here - a stale entry would silently
# redirect A2S status checks and card metadata to a dead address for anyone
# who saved the server by that hostname, which is worse than no entry at all.
DOMAIN_TO_IP_FALLBACK = {}


def get_server_metadata(ip: str, name: str = "") -> dict:
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
        "description": f"Rust server {name or ip}. Connect and have fun!",
    }
