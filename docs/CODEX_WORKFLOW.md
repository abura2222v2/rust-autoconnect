# Codex Workflow

This workflow keeps Codex changes safe, small, and verifiable.

## 1. Explore

- Stay inside the repository.
- Read existing instructions first: `AGENTS.md`, `GEMINI.md`, `.agents/rules/*.md`, `README.md`, `PROJECT.md`, and task-relevant files.
- Do not inspect secrets such as `.env`, private keys, tokens, cookies, or production credentials.
- Check `git status --short --branch` before significant edits.

## 2. Plan

- Identify the affected subsystem and the smallest useful change.
- Prefer existing helpers, module boundaries, and style.
- Ask before changing global settings, dependencies, plugins, production data, migrations, branches, commits, pushes, or PRs.

## 3. Implement

- Make narrow changes only.
- Preserve user edits and unrelated files.
- Keep documentation and code comments in English.
- Avoid destructive commands and broad rewrites.

## 4. Verify

- Run the narrowest relevant test first.
- For this project, the primary test command is:

```powershell
python -m pytest tests/
```

- GUI integration tests are opt-in because they require a healthy local Tcl/Tk installation:

```powershell
$env:RUN_GUI_TESTS = "1"
python -m pytest tests/test_gui.py
```

- A local visual smoke-test captures the Connect, Benchmark, and Settings screens
  without starting network, Steam, or production services:

```powershell
python tests/gui_smoke.py
```

- Also run the syntax and whitespace checks after Python changes:

```powershell
python -m compileall -q src tests
git diff --check
```

- If packaging or entry-point behavior changed, run only safe smoke, syntax, or build commands. Do not run the app entry point when it would load `.env` or production credentials unless the user explicitly approves a sanitized run.
- If verification cannot run, report the blocker and any limited checks that did run.

## 5. Git

- Do not commit, push, create a PR, switch branches, or modify `main`/`master` without explicit user approval.
- Review the final diff before handoff.

## 6. Handoff

- Update `HANDOFF.md` when useful for the next chat.
- Final responses should state what changed, what was verified, what remains, and any risks.
