# Handoff

## Current State

- Branch: `master`
- Last verified Git status: run `git status --short --branch` before relying on this handoff.
- Stack: Python GUI utility using CustomTkinter, pytest, Supabase REST/WebSocket integration, PyInstaller/Inno Setup packaging files
- Entry point: `main.py`
- Main application controller: `src/app.py`

## Project Rules

- Primary agent rules: `AGENTS.md`
- Existing operating memory: `GEMINI.md`
- Detailed safety rules: `.agents/rules/*.md`
- Workflow guide: `docs/CODEX_WORKFLOW.md`

## Common Commands

```powershell
python -m pytest tests/
python -m compileall -q src tests
git diff --check
```

Run GUI integration tests only on a machine with a working Tcl/Tk installation:

```powershell
$env:RUN_GUI_TESTS = "1"
python -m pytest tests/test_gui.py
```

Do not run `python main.py` as a routine smoke command if it loads `.env` or production credentials. Ask the user before an app run that requires real local configuration.

## Safety Notes

- Stay inside this repository.
- Do not read `.env` or other secrets.
- Do not install dependencies, change global Codex settings, run destructive Git commands, commit, push, create PRs, switch branches, or touch production data without explicit user approval.

## Next Chat Template

- Goal:
- Relevant files:
- Current changes:
- Verification run:
- Remaining work:
- Risks or blockers:
