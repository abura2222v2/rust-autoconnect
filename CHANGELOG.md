# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0] — 2026-08-07

### Added
- Initial release
- Server connection via Steam URI protocol (`steam://run/252490//+connect IP:PORT`)
- DNS domain resolution to real server IP
- Smart Query port detection with multiple offsets (+0, +3, +15, +123)
- A2S_INFO UDP polling with BrokenMessageError handling for Rust's RakNet protocol
- Dark theme UI built with CustomTkinter
- Server history panel with save (`+` button) and delete (`X` button)
- Auto-save server on Start
- Rust process detection indicator (green = running, red = closed)
- Multi-language support: Russian, English, Spanish, French, German, Chinese
- Language selector with full names in dropdown, short codes on button
- Persistent settings and history in `data.json`
- `run.bat` for quick launch on Windows

## [0.5.6] - 2026-08-08

### Fixed
- Re-architected log watcher to aggressively loop and reconnect on ANY disconnection, acting as a relentless auto-connect loop.
- Fixed log tailing blind spot caused by Windows file buffering. Now actively polling \os.path.getsize\ to guarantee immediate real-time reads of the Rust \Player.log\.
