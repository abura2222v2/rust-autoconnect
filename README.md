# Rust AutoConnect & Hardware Benchmark

An advanced, multi-threaded server auto-connector for Rust, and a global hardware benchmarking utility. 

## Features

- **Hardware Benchmark:** Test how fast your CPU and the storage containing Rust load the game. The benchmark tracks time-to-menu and map-load time. Public results are anonymous configuration statistics; no disk serial numbers are uploaded.
- **A2S Polling:** Rapidly queries the server to instantly detect when it goes online.
- **Auto-Update Detection:** Automatically detects when a Rust game update is required and forces Steam to update.
- **Log Watcher:** Reads Rust client logs to instantly reconnect if disconnected.
- **P2P Swarm:** Connects with other users via Supabase to instantly share server awake status.

## Usage

**Auto-Connect:**
Run the application, select a server from your history or enter a new one (`IP:PORT`), and click Start. The app will handle the rest.

**Hardware Benchmark:**
Click the **Запустить Тест** (Run Benchmark) button. The app will automatically launch Rust, time the loading sequence, and close the game when finished. View global rankings by clicking the **Мировой Топ** (World Top) button!
