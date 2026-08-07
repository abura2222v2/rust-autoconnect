# Rust AutoConnect

A lightweight Windows desktop tool that automatically connects you to Rust game servers via Steam. Enter a server IP or domain, and the app resolves the real IP, monitors the server status, and launches the game when the server is ready.

## Features

- **Smart DNS Resolution** — paste a domain like `monday.eu.moose.gg:28010` and the app finds the real IP automatically
- **Smart Query Port Detection** — scans multiple port offsets (+0, +3, +15, +123) to find the server's query port, even behind DDoS protection
- **Auto-Connect via Steam** — launches Rust through `steam://run/252490//+connect IP:PORT` when the server responds
- **Server History** — save servers with their names, click to re-select, delete old entries
- **Rust Process Indicator** — real-time green/red status showing if Rust is currently running on your PC
- **Multi-Language** — full interface localization: 🇷🇺 Russian, 🇬🇧 English, 🇪🇸 Spanish, 🇫🇷 French, 🇩🇪 German, 🇨🇳 Chinese
- **Dark Theme** — modern dark UI built with CustomTkinter

## Download

### Option 1: Standalone EXE (no Python needed)
Go to [**Releases**](../../releases) and download `RustAutoConnect.exe`.
Place it in any folder — `data.json` (your settings and server history) will be saved next to it.

### Option 2: Run from source (Python)
```bash
# Clone the repository
git clone https://github.com/abura2222v2/rust-autoconnect.git
cd rust-autoconnect

# Install dependencies
pip install -r requirements.txt

# Run
python main.py
```

Or simply double-click `run.bat` on Windows.

## Usage

1. **Enter server address** — type `IP:PORT` or `Domain:PORT` in the input field
2. **Save to history** — click `+` to save the server without connecting
3. **Start monitoring** — click `Start` to begin polling the server
4. The app resolves the domain → checks if the server is alive → polls every 3 seconds
5. After 2 successful responses, it automatically launches Rust via Steam
6. Click `Stop` to cancel monitoring at any time

### Tips
- You can paste addresses from [BattleMetrics](https://www.battlemetrics.com/servers/rust) directly
- The app never touches Rust game files — it only communicates via Steam URI protocol and UDP queries
- Server history persists in `data.json` next to the executable

## How It Works

```
User enters domain:port
        ↓
  DNS Resolution (socket.gethostbyname)
        ↓
  Smart Query Port Scan (A2S_INFO on port offsets)
        ↓
  Polling Loop (every 3 seconds)
        ↓
  2 consecutive responses → steam://run/252490//+connect IP:PORT
        ↓
  Rust launches via Steam
```

## Requirements

- Windows 10/11
- Steam installed with Rust (App ID 252490)
- Python 3.10+ (only if running from source)

## Dependencies

| Package | Purpose |
|---|---|
| [customtkinter](https://github.com/TomSchimansky/CustomTkinter) | Modern dark-themed UI |
| [python-a2s](https://github.com/Yepoleb/python-a2s) | Source Engine server queries (A2S_INFO) |

## License

[MIT](LICENSE)
