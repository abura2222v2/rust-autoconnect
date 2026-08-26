# Changelog

## [Unreleased]

### Added
- A "Smart mode" toggle in Settings. Normal mode (now the default, and the only mode actually reachable) polls the target server every ~2 seconds from the moment Start is pressed and connects on the first online result, with no wipe-time awareness — for the "server closed before wipe, just keep hammering it" case. The existing wipe-aware quiet/watch/turbo logic is kept in `smart_monitor.py` behind a `smart_mode` flag for a future release; trying to switch the toggle on currently shows a "Smart mode is temporarily unavailable" toast and the toggle snaps back off. The wipe countdown on the server details card (a Smart-mode feature) shows the same toast when clicked.
- Auto-arm (reconnect an armed server after a log-confirmed disconnect) and Swarm (P2P server-status sharing) are unaffected by this toggle — both already worked independently of the wipe schedule and continue to work the same way in Normal mode.

## [0.7.0] - 2026-08-22

### Added
- The web UI (now the default interface) gained the same smart-connect engine the legacy desktop GUI had: wipe-aware turbo polling, a pre-wipe restart hold, real confirmation via Rust's own `Player.log`, and automatic reconnect on disconnect for an armed server.
- Live per-server status in the server table, backed by real A2S queries on a 30s background refresh cycle, replacing the previous hardcoded "online" indicator.
- A wipe-fingerprint check: the shared server-intelligence cache's map seed is now compared against a stored baseline near force-wipe time, catching a server restart even if a local A2S probe misses the brief offline window.
- Swarm (P2P hint) support is now wired into the web UI's connect flow, not just the legacy GUI.
- A wipe countdown to the next official force-wipe, shown in the server details card.
- A real per-server RustMaps.com link, resolved lazily in the background via A2S rules query, replacing the generic homepage placeholder.
- A persistent system tray icon (Show window / Quit) for the web UI.
- Background sync of saved servers to the shared provider cache, matching the existing desktop-GUI setting.

### Fixed
- CSRF: local `/api/*` endpoints now require a per-session token, closing a hole where any other open browser tab could silently drive the app (connect to an attacker-chosen server, wipe saved servers, unlink Telegram) while it was running.
- Stored XSS: server names and log lines are now HTML-escaped before being rendered, closing the injection vector the CSRF hole could otherwise chain into.
- A DNS lookup with an unreachable resolver could stall the entire connection-polling thread; resolution is now hard-bounded.
- SVG icons across the web UI were being clipped by a missing `viewBox`, rendering as unrecognizable fragments (the favorite-star icon in particular looked like a flag). All 35 occurrences fixed.
- The packaged Windows build was missing the web UI's static assets entirely (`src/web/static` was never listed in the PyInstaller `datas`), so a built `.exe` served a bare 404 instead of the app. `RustAutoConnect.spec` also excluded the `http`/`html` stdlib modules the web server depends on. Verified by an actual PyInstaller build.

### Changed
- Removed the in-game playtime counter from the web UI footer (unused).

## [1.0.0] - 2026-08-08
- Complete UI Redesign: Added a modern navigation sidebar.
- Integrated Server History inside the Home page.
- Added Infinite Scrolling (Pagination) and Search functionality to the Global Leaderboard.
- Fixed an issue where the settings menu threw a `ModuleNotFoundError`.
- Fixed hardware IDs to use accurate CPU and Disk serials.
- Fixed UI freeze during boot.
- Translated all files and codebase to English.

