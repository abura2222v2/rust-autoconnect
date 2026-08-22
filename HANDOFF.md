# Handoff

## Current State

- Branch: `master`; latest pushed commit: `26ca4eb fix: harden wipe-aware connection monitoring`.
- Remote: `origin` -> `https://github.com/abura2222v2/rust-autoconnect.git`.
- The commit was pushed to `origin/master` on 2026-08-12.
- Current local working tree has only untracked local/tool files and this handoff file after this update. Do not add them by a broad `git add .`:
  `.bin/`, `.codex-remote-attachments/`, `.tools/`, `master_prompt.txt`, `supabase/.temp/cli-latest`, `test_async.py`.
- Stack: Python 3.13, CustomTkinter/Tk, pytest, Steam URL launch, A2S, Player.log tailing, optional Supabase/Swarm/Telegram, PyInstaller.
- Entry: `main.py`; primary controller: `src/app.py:AppController`.
- Latest local build: `dist/main/main.exe` (ignored by Git). Rebuild command is below.

## What Was Completed In Commit `26ca4eb`

### Safe Connect, wipe handling, and status truthfulness

- The only Rust launch mechanism is a Steam URL (`steam://run/252490//+connect host:port`). No memory reads/writes, injection, hooks, RCON, packet interception, or emulated game input are used.
- A server with capacity needs two fresh A2S replies before Steam is launched.
- A full server in a **manual** Connect can enter Rust's own queue, but only after two fresh replies prove it is a real full server. Armed auto-connect does not open Rust for a full server.
- A missing/zero-capacity A2S reply cannot be mistaken for a valid queue target.
- `Spawning` and `[Bootstrap] DONE!` are no longer treated as a successful server entry. `[Bootstrap] DONE!` is logged only as “Rust menu ready”.
- Telegram, Swarm availability, and UI “Connected” occur only after `Client connected` in the per-session `Player.log` watcher. If the log includes an endpoint, it must equal the selected raw or canonical endpoint.
- After the Steam URL opens, the same session keeps an A2S observation every five seconds until log confirmation or cancellation. It never opens Steam a second time. The Activity Log reports whether Rust is loading while the server is online or has stopped responding.
- New pre-wipe behavior: when a confirmed schedule/Force Wipe is within five minutes, an unlaunched Connect session holds on the old online map instead of launching Rust. It releases only after a reliable restart signal: fresh provider `offline`, or two A2S misses after a successful response, or planned wipe time has passed while the server is unavailable. Then normal two-A2S readiness is required before launch. It never closes or redirects an already-running Rust client.
- The schedule is an acceleration hint, never proof that a particular server is ready.

### UI and Telegram work already included in the commit

- Home and Benchmark splitters now use native `tk.PanedWindow` panes instead of the old custom preview overlay. This removed the mixed-DPI overlay/sash coordinate bug. The user should still manually test fast drag on their own display scaling.
- Telegram pairing overlay is in-app and copyable. The Bot Edge Function source supports the currently used webhook routes and menu localisation.
- EN/RU strings were updated for queue, launch observation, menu-ready and wipe-restart states. Other languages may still use the English fallback for newer keys.

## Key Files

- `AGENTS.md`, `GEMINI.md`, `.agents/rules/*.md`: mandatory workflow and project boundaries.
- `src/app.py`: Connect lifecycle, current-session cancellation, A2S polling, Steam launch, Player.log confirmation, wipe hold, auto-reconnect, benchmark orchestration.
- `src/core/smart_monitor.py`: `ConnectionSession`, `ConnectionPhase`, retry/turbo/wipe state machine.
- `src/core/a2s_client.py`: bounded cancellable A2S queries and query-port discovery.
- `src/services/log_watcher.py`: tails only appended Player.log lines, normally every ~0.5 s.
- `src/services/steam_service.py`: Steam URL construction and Rust update/build helpers.
- `src/gui/main_window.py`: Command Center layout, native split panes, settings, history, benchmark/ranking views.
- `src/core/history_store.py`: atomic local history/settings/profiles/armed endpoint.
- `src/services/server_intelligence_service.py` and `supabase/functions/server-intelligence/index.ts`: optional shared GameMonitoring cache; client cache signals are hints only.
- `src/services/swarm_service.py`: optional Supabase Realtime signal; it must never launch Rust without local A2S confirmation.
- `src/services/telegram_service.py` and `supabase/functions/telegram-bot/index.ts`: local pairing/status/preferences and Telegram Edge Function.
- `assets/i18n/en.json`, `assets/i18n/ru.json`: current core translations.
- `tests/test_smart_monitor.py`: wipe/phase/retry policy.
- `tests/test_launch_observation.py`: new post-Steam online/offline observation regressions with no real Rust/Steam.
- `tests/test_connect_e2e.py`: localhost mock A2S + temporary Player.log integration.
- `tests/test_app_operations.py`: controller lifecycle and log-confirmation regressions.
- `tests/gui_smoke.py`: local GUI screenshots; it does not exercise a physical mouse under the user’s DPI.

## Verification Last Run

Commands, run from the repository root:

```powershell
py -3 -m pytest tests -q --ignore=tests/stress_test.py --ignore=tests/simulate_reconnect_loop.py --basetemp .pytest_tmp\wipe_hold_full
py -3 -m compileall -q src
py -3 tests\gui_smoke.py
py -3 -m PyInstaller --noconfirm --onedir --windowed --add-data "assets;assets" main.py
git diff --check
```

Results on 2026-08-12:

- `122 passed`.
- Python compilation passed.
- GUI smoke passed and wrote screenshots under `.pytest_tmp/gui_smoke`.
- PyInstaller build completed; output is `dist/main/main.exe`.
- `git diff --check` passed before the handoff update.

For a new code change, run narrow tests first, then the full command above. GUI smoke and pytest should use separate `--basetemp` values when run in separate commands.

## Important Behavior / Product Decisions

- Manual **Connect** normally means enter immediately if the server is usable; it can use the server’s normal Rust queue when full.
- During the final five minutes before a known wipe, manual Connect and auto-connect wait for a restart instead of intentionally entering the old map.
- Armed auto-connect is only for the explicitly armed selected endpoint. It must not guess where the user manually joined.
- A2S `online`/player count and shared GameMonitoring cache are only signals; Player.log `Client connected` is the local confirmation of entry.
- Do not claim that a generic process exists, `Spawning`, a visible menu, or one A2S response proves entry to the selected server.
- Keep provider/Swarm work parallel and bounded. It must never delay the A2S/Steam critical path or cause repeated Steam launches.
- Log watcher reads a local text file only; no network or Rust-memory operations are involved in watching it.

## Remaining Work / Risks

- Physical fast splitter drag must be tested manually on the user's actual Windows DPI scaling. Automated GUI smoke validates layout/sizes but cannot fully reproduce pointer paint artifacts.
- One real end-to-end test with a benign server is still useful: start near a controlled restart, verify old map hold -> offline/restart -> two A2S replies -> Steam URL -> menu-ready -> `Client connected`. Do not test against a player’s real `Player.log` from automation.
- Rust log strings are not a documented stable public contract. The code intentionally accepts only `Client connected` as success; if Facepunch changes the format, update the parser and tests instead of weakening it to `Spawning`.
- DE/ES/FR/ZH/UK localisation is not complete for all newer strings; English fallback works.
- The optional provider/backend and Telegram paths require their production deployment/configuration to be verified separately. Do not read `.env`, `env.lock`, tokens, browser data, or external credentials to diagnose them.
- Benchmark remains a separate sensitive subsystem because it temporarily changes Rust configuration and can terminate Rust in guarded benchmark cleanup paths. Do not merge that behavior into Connect.
- Do not add raw scraping or anti-bot bypasses. Use only documented GameMonitoring API/backend cache paths.

## Safety and Git Rules

- Work only inside this repository.
- Never read or disclose `.env`, `env.lock`, API keys, tokens, cookies, certificates, browser data, or credentials.
- Never use `git add .` in this checkout; stage explicit source files only.
- Do not commit, push, create a PR, deploy Supabase, change production data, or alter database migrations without the user’s explicit approval for that action.
- Preserve user changes; never use destructive reset/clean/checkout commands.

## Suggested Next-Chat Prompt

```text
Read HANDOFF.md, AGENTS.md, GEMINI.md and .agents/rules first. Start with
git status --short --branch. Continue Rust AutoConnect from commit 26ca4eb.
Do not read secrets or untracked local tool files. Keep Connect safe: Steam URL,
A2S, process list and Player.log only; no Rust memory/injection/RCON/input.
Run targeted tests before edits and the full pytest/GUI smoke/diff review before
claiming completion. Current priority: inspect any new user-reported behavior
against the wipe-aware pre-launch hold and post-launch A2S observation logic.
```
