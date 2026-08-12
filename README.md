# AutoConnect for Rust

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-windows-lightgray.svg)]()

AutoConnect is a robust, log-based server connection manager for the game Rust. Designed with strict adherence to Easy Anti-Cheat (EAC) guidelines, it provides automated server queuing, crash recovery, and wipe scheduling without injecting into the game's memory space.

## Features

![Connect](assets/screenshots/connect.png)

- **Safe Log-Based Monitoring**: Uses only Steam URLs, A2S server queries, the Windows process list, and the player's own Rust log. It never reads game memory, injects code, hooks Rust, uses RCON, or emulates input.
- **Smart Auto-Arming**: Automatically detects when you successfully connect to a server and "arms" the connection. If your game crashes or you are disconnected unexpectedly, AutoConnect will instantly restart Rust and place you back in the queue.
- **Force Wipe Intelligence**: Calculates the official first-Thursday wipe window from 19:00 London time, corrects scheduling from recent network time, and uses bounded quiet/watch/turbo polling.
- **Swarm Peer Network**: Optional Supabase Realtime hints. A client announces availability only after its own Rust log confirms connection; every receiver independently confirms with A2S before launching.
- **Shared Server Catalogue**: Optional GameMonitoring-backed cache deduplicates provider checks for saved servers. It shares only server addresses, never player lists, logs, Steam IDs, or account data; cached offline and wipe data are hints, while local A2S remains the launch decision.
- **Performance Benchmarking**: Automated testing framework that measures game loading times (Time-to-Menu and Map Load) by playing standardized `.dem` files.
- **Telegram Integration**: Receive queue updates and wipe notifications directly to your phone via the integrated Telegram bot framework.

## Architecture

The application is built on a modern asynchronous Python stack (`asyncio`) to guarantee minimal memory footprint and zero interface stuttering, even during intense background polling.

- **GUI**: CustomTkinter
- **Networking**: `asyncio` UDP A2S Client for non-blocking server queries
- **Data Persistence**: JSON-based local history store
- **Realtime Infrastructure**: Supabase Edge Functions & WebSockets

## Force Wipe and time accuracy

| Stage | Behaviour |
| --- | --- |
| 30 minutes before / after | A2S checks every 30 seconds; Rust build check every minute |
| First five minutes after Force Wipe | A2S turbo checks every second, bounded to five minutes |
| Server disappears early or late | One separate bounded turbo window after the offline signal |
| Rust update detected | Steam Downloads opens once; Connect waits for the local build ID to match |

The official monthly default is the first Thursday at 19:00 London time. Server owners can use a different schedule or restart early, so the countdown is an acceleration signal, not a promise that a particular server is ready. The application uses server time from its update check when available and falls back transparently to Windows time offline.

## Installation & Setup

1. **Prerequisites**: Python 3.10 or higher.
2. **Clone the repository**:
   ```bash
   git clone https://github.com/abura2222v2/rust-autoconnect.git
   cd rust-autoconnect
   ```
3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
4. **Run**:
   ```bash
   python main.py
   ```

## Building the Executable

To compile AutoConnect into a standalone Windows executable (`.exe`):

```bash
pyinstaller --noconfirm --onedir --windowed --add-data "assets;assets" "main.py"
```

The executable intentionally contains only public runtime configuration. A
Windows code-signing certificate can establish publisher identity and reduce
SmartScreen warnings, but it cannot safely hide code or any value embedded in
an executable. Keep service-role keys, Telegram tokens and other secrets only
in Supabase Edge Secrets or local developer files.

## Supabase connection and privacy

The downloaded application works without asking a player to create or paste a
Supabase key. It contains only the project's **publishable** connection value,
which is intentionally safe to distribute when Supabase Row Level Security is
enabled. It lets the app call public Edge Function routes and optional Realtime
Swarm; it cannot administer the database.

Never put a Supabase service-role key, a personal access token, Telegram bot
token, or Edge Function secret in GitHub, the source code, or the `.exe`.
Those values stay in Supabase Edge Secrets. If a self-hosted fork needs its own
backend, its maintainer creates a separate project and supplies its own public
configuration; ordinary players do nothing.

## Contributing

Contributions are welcome. Please ensure that all modifications strictly adhere to the log-parsing philosophy. Any pull requests introducing memory manipulation or injection techniques will be rejected immediately to maintain EAC compliance.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
