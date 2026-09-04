#!/usr/bin/env python3
"""Always-on A2S prober for Rust AutoConnect.

Why this exists: the shared server cache is filled by a third-party
aggregator (gamemonitoring.net), which lags by minutes, only covers servers
that are in its catalogue, and rates its own wipe times as "medium"
confidence. This process runs on a machine that is always on, asks the
servers themselves over A2S, and writes the real answer back - so every
user's app sees a status that is seconds old instead of minutes old, and
small servers the aggregator never heard of get a status at all.

It deliberately holds no state of its own: the queue comes from the backend
and the results go straight back to it. Nothing is stored on disk.

Anti-cheat note: this only reads public A2S (Source query protocol) replies
from game servers - the exact same thing the desktop app already does. It
never touches a game client, never uses RCON, and never connects to a server
as a player.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable

# Reuse the app's own A2S client so the prober and the desktop app agree on
# how a server is probed (query-port offset discovery, per-server port cache)
# instead of maintaining a second, subtly different implementation.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.core.a2s_client import A2SClient  # noqa: E402


API_URL = os.environ.get("PROBER_API_URL", "").rstrip("/")
SECRET = os.environ.get("PROBER_SECRET", "")
# Supabase's gateway requires the app's publishable key on every call; the
# write permission comes from PROBER_SECRET, never from this key.
API_KEY = os.environ.get("PROBER_API_KEY", "")
CYCLE_SECONDS = float(os.environ.get("PROBER_CYCLE_SECONDS", "60"))
CONCURRENCY = int(os.environ.get("PROBER_CONCURRENCY", "10"))
BATCH_LIMIT = int(os.environ.get("PROBER_BATCH_LIMIT", "200"))
HTTP_TIMEOUT = float(os.environ.get("PROBER_HTTP_TIMEOUT", "20"))

_stopping = False


def log(message: str) -> None:
    """Print to stdout; systemd/journald owns timestamps and rotation."""
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}", flush=True)


def _request(path: str, payload: dict[str, Any]) -> Any:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{API_URL}{path}",
        data=body,
        headers={
            "content-type": "application/json",
            "x-prober-secret": SECRET,
            "apikey": API_KEY,
            "authorization": f"Bearer {API_KEY}",
        },
    )
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def fetch_queue() -> list[dict[str, Any]]:
    payload = _request("/server-intelligence/probe-queue", {"limit": BATCH_LIMIT})
    entries = payload.get("endpoints") if isinstance(payload, dict) else None
    return entries if isinstance(entries, list) else []


def dedupe(entries: Iterable[dict[str, Any]]) -> list[tuple[str, int]]:
    """One probe per host:port, no matter how many users saved it."""
    seen: dict[tuple[str, int], None] = {}
    for entry in entries:
        endpoint = entry.get("endpoint") if isinstance(entry, dict) else None
        if not isinstance(endpoint, str) or ":" not in endpoint:
            continue
        host, _, port_text = endpoint.rpartition(":")
        try:
            port = int(port_text)
        except ValueError:
            continue
        if not host or not 1 <= port <= 65535:
            continue
        seen.setdefault((host, port), None)
    return list(seen.keys())


async def probe_all(client: A2SClient, targets: list[tuple[str, int]]) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(max(1, CONCURRENCY))
    results: list[dict[str, Any]] = []

    async def probe(host: str, port: int) -> None:
        async with semaphore:
            try:
                status = await client.get_server_status(host, port)
            except Exception as error:  # a single bad server must not stop the cycle
                log(f"probe failed for {host}:{port}: {type(error).__name__}")
                return
        results.append(
            {
                "endpoint": f"{host}:{port}",
                "online": bool(status.alive),
                "players": int(status.player_count),
                "max_players": int(status.max_players),
                "query_port": int(status.query_port),
                "name": status.server_name[:240],
                "map": status.map_name[:240],
            }
        )

    await asyncio.gather(*(probe(host, port) for host, port in targets))
    return results


def report(results: list[dict[str, Any]]) -> None:
    # Send in chunks so one oversized request can't fail the whole cycle.
    for start in range(0, len(results), 50):
        chunk = results[start:start + 50]
        _request("/server-intelligence/probe-report", {"results": chunk})


async def run_cycle(client: A2SClient) -> None:
    entries = fetch_queue()
    targets = dedupe(entries)
    if not targets:
        log("queue empty - nothing to probe this cycle")
        return
    started = time.monotonic()
    results = await probe_all(client, targets)
    online = sum(1 for item in results if item["online"])
    report(results)
    log(
        f"probed {len(results)}/{len(targets)} endpoints "
        f"({online} online) in {time.monotonic() - started:.1f}s"
    )


def _handle_signal(signum, _frame) -> None:
    global _stopping
    _stopping = True
    log(f"signal {signum} received - finishing current cycle and exiting")


async def main() -> int:
    if not API_URL or not SECRET or not API_KEY:
        log("PROBER_API_URL, PROBER_SECRET and PROBER_API_KEY must all be set")
        return 2

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    client = A2SClient()
    log(f"prober started: cycle={CYCLE_SECONDS}s concurrency={CONCURRENCY} limit={BATCH_LIMIT}")

    while not _stopping:
        cycle_started = time.monotonic()
        try:
            await run_cycle(client)
        except urllib.error.HTTPError as error:
            log(f"backend rejected the request: HTTP {error.code}")
        except urllib.error.URLError as error:
            log(f"backend unreachable: {error.reason}")
        except Exception as error:
            log(f"cycle failed: {type(error).__name__}: {error}")

        remaining = CYCLE_SECONDS - (time.monotonic() - cycle_started)
        while remaining > 0 and not _stopping:
            await asyncio.sleep(min(1.0, remaining))
            remaining -= 1.0
    log("prober stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
