# Rust AutoConnect & Hardware Benchmark

Rust AutoConnect is a desktop helper for monitoring a chosen Rust server, reconnecting after an application-observed disconnect, and running an optional local hardware benchmark.

## Features

- **Hardware Benchmark:** Measures menu and map-load time. Public ranking data is anonymous configuration statistics; no disk serial numbers are uploaded.
- **Smart A2S Polling:** Uses a low-load schedule normally, accelerates in the configured wipe window or after a server-down/Swarm hint, and confirms locally before launching Steam.
- **Rust Update Check:** Reports when a Rust update is available; it never installs an update automatically.
- **Safe Auto-Reconnect:** Reads the local Rust log and watches the Windows process only for a server explicitly armed by the player.
- **Swarm Hints:** Optional Supabase Realtime hints can wake a local confirmation probe. A peer report never launches Rust on its own.

## Usage

**Auto-Connect:**

Select a server from history or enter `IP:PORT`, then click **Connect**. For a planned wipe, open **Server details** by double-clicking a history entry and enter the next wipe in UTC. The timer changes only the checking frequency; it is not a guarantee that the server will wipe at that time.

**Hardware Benchmark:**

Click **Run Benchmark**. It launches Rust, measures loading, then restores the original configuration. View results in **Ranking**.

## Safety and configuration

Normal connection uses public A2S server queries, Windows process detection, the local Rust log, and Steam's `+connect` command. It does **not** read or write Rust memory, inject code, intercept packets, emulate input, use RCON, or bypass EAC.

Benchmark is separate and explicitly confirmed because it temporarily modifies Rust configuration/demo files. It is not used by auto-connect or auto-reconnect.

`assets/public-config.json` may contain only public values: the project URL, `SUPABASE_PUBLISHABLE_KEY`, and a public benchmark URL. Never put a personal `sbp_` token, `sb_secret`, service-role key, or shared `SWARM_SECRET` in source code, `.env.local`, Git, or an executable. Elevated Supabase credentials belong only in a server environment.

## Shared server intelligence

`SERVER_INTELLIGENCE_URL` is optional.  When configured, clients read a shared cache for the selected endpoint and may opt in to report that their own A2S probe found it available. The report contains only `endpoint`; it does not upload a Rust log, Steam ID, account data, or a client identifier. Provider credentials and rate-limit secrets stay only in the Edge Function. See [deployment notes](docs/SERVER_INTELLIGENCE.md).
