# Handoff

## Current State

- Branch: `master`; working tree was clean after commit `cfc4f89`.
- Latest commits:
  - `cfc4f89 Fix splitter drag flicker`
  - `1e2533d Improve client reliability and command center`
- Remote: `origin` points to `https://github.com/abura2222v2/rust-autoconnect.git`.
- Stack: Python 3.13, CustomTkinter desktop GUI, pytest, Steam/Rust integration, Supabase REST integration, PyInstaller/Inno Setup packaging.
- Entry point: `main.py`.
- Main controller: `src/app.py:AppController` extends `src/gui/main_window.py:MainWindow`.

## Active Product Direction

The app is a dark Command Center for connecting to Rust servers, reconnect monitoring, server history, a guarded local benchmark, and an online anonymous benchmark ranking.

- Keep the current Command Center layout and compact dark/orange visual language.
- Preserve the existing connection, history, watcher, benchmark, settings, and ranking workflows unless the user explicitly asks to remove or redesign one.
- Do not add RCON, Steam automation, Supabase schema changes, automatic updates, or new external services without approval.
- The drag splitter fix is intentionally minimal: no hover tooltip or hover recolor, drag updates at 60 FPS, double-click reset remains. If it still fails on the user's DPI/display, inspect `src/gui/main_window.py` and reproduce with a real mouse before changing geometry again.

## Key Files

- `AGENTS.md`: repository rules and safety constraints.
- `docs/CODEX_WORKFLOW.md`: development, test, security, and Git workflow.
- `main.py`: application entry point.
- `src/app.py`: orchestration, task lifecycle, benchmark flow, retries, release checks.
- `src/gui/main_window.py`: all primary GUI layouts, splitters, views, UI dispatch queue.
- `src/gui/tooltip.py`: generic tooltip helper; do not attach it to resize splitters.
- `src/core/a2s_client.py`: cancellable A2S querying and query-port discovery.
- `src/core/history_store.py`: atomic local settings/history/benchmark retry queue.
- `src/services/leaderboard_service.py`: anonymous ranking HTTP integration.
- `src/services/release_service.py`: GitHub Releases version check.
- `tests/test_gui.py`: GUI lifecycle, splitters, UI dispatch, and Command Center controls.
- `tests/test_app_operations.py`: benchmark uploads/retry queue/release-status behavior.
- `tests/gui_smoke.py`: local smoke screenshots for Connect, Benchmark, and Settings.
- `.env.example`: environment variable template. Never read local `.env`.

## Verification

The Tcl/Tk component for the local Python 3.13 installation was repaired. GUI tests now run normally; do not set `RUN_GUI_TESTS`.

Run checks sequentially because GUI smoke-test and pytest use separate temporary application data:

```powershell
python -m pytest tests/ -q --basetemp .pytest_tmp\pytest_full
python -m compileall -q src tests
git diff --check
python tests/gui_smoke.py
```

Last verified after the splitter fix:

- `79 passed` in pytest.
- `python -m compileall -q src tests` passed.
- `git diff --check` passed.
- `python tests/gui_smoke.py` passed and wrote screenshots to `.pytest_tmp/gui_smoke`.

## Safety and Git

- Stay inside this repository unless the user explicitly approves an external system change.
- Never read or disclose `.env`, tokens, keys, cookies, or production credentials.
- Do not alter Supabase production data or run dangerous migrations.
- Preserve user changes. Never use `git reset --hard`, `git clean`, `git checkout --`, or broad destructive file operations.
- Do not commit, push, create a PR, change branches, or change `main`/`master` without explicit user approval.
- The old tracked `.env` was removed from the current tree, but any previously exposed secret must still be rotated because Git history may contain it.

## Known Risks

- Splitter behavior has automated geometry coverage, but physical pointer behavior at the user's display scaling still needs manual confirmation.
- Online ranking sends an anonymous installation identifier plus benchmark hardware summary/timings. It does not send username, local paths, or serial numbers. Treat changes to this data flow as privacy-sensitive.
- GitHub release status is informational only. The app never downloads or installs an update automatically.
- GUI smoke-test does not use real Steam/Rust, production Supabase credentials, or a live server.

## Next Chat Template

- Goal:
- Relevant files:
- Current Git status and branch:
- Changes made in this chat:
- Verification run:
- Remaining work:
- Risks or blockers:
