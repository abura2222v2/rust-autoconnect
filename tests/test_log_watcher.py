"""Tests for src/services/log_watcher.py's log file path resolution.

Regression test for a real bug found via manual testing (2026-09-03): a
Rust install/session can write only to output_log.txt (in the Rust install
directory) and never touch Player.log at all. LogWatcher only ever checked
that alternate path when history_store.get_rust_path() was already set - but
that setting is normally only saved by the benchmark flow, so a user who
never ran a benchmark had their connection confirmation silently never fire,
regardless of what the log actually said.
"""
from src.core.config import config
from src.services.log_watcher import LogWatcher


def test_resolve_log_path_auto_detects_rust_install_when_no_saved_path(monkeypatch, tmp_path):
    """With no saved rust_path, the watcher must still find output_log.txt by
    auto-detecting the Rust install (the same lookup the benchmark flow
    uses), not silently stick to a Player.log that may not exist."""
    missing_player_log = tmp_path / "does_not_exist" / "Player.log"
    monkeypatch.setattr(type(config), "rust_log_path", property(lambda self: missing_player_log))
    monkeypatch.setattr("src.core.history_store.history_store.get_rust_path", lambda: "")

    fake_rust_dir = tmp_path / "Rust"
    fake_rust_dir.mkdir()
    output_log = fake_rust_dir / "output_log.txt"
    output_log.write_text("Connecting: 1.2.3.4:28015\n", encoding="utf-8")
    monkeypatch.setattr(
        "src.services.steam_service.find_rust_install_path", lambda: str(fake_rust_dir)
    )

    watcher = LogWatcher(on_disconnect=lambda reason: None, on_error=lambda err: None)
    resolved = watcher._resolve_log_path()
    assert resolved == output_log


def test_resolve_log_path_prefers_saved_rust_path_over_auto_detect(monkeypatch, tmp_path):
    """A user-saved rust_path (e.g. from the benchmark flow) must still win -
    auto-detection is only a fallback for when nothing was saved."""
    missing_player_log = tmp_path / "does_not_exist" / "Player.log"
    monkeypatch.setattr(type(config), "rust_log_path", property(lambda self: missing_player_log))

    saved_dir = tmp_path / "SavedRust"
    saved_dir.mkdir()
    saved_output_log = saved_dir / "output_log.txt"
    saved_output_log.write_text("Connecting: 1.2.3.4:28015\n", encoding="utf-8")
    monkeypatch.setattr("src.core.history_store.history_store.get_rust_path", lambda: str(saved_dir))

    def _fail_if_called():
        raise AssertionError("auto-detect must not run when a rust_path is already saved")

    monkeypatch.setattr("src.services.steam_service.find_rust_install_path", _fail_if_called)

    watcher = LogWatcher(on_disconnect=lambda reason: None, on_error=lambda err: None)
    resolved = watcher._resolve_log_path()
    assert resolved == saved_output_log


def test_resolve_log_path_falls_back_to_player_log_when_nothing_found(monkeypatch, tmp_path):
    """If neither a saved path nor auto-detection finds a Rust install, fall
    back to the default Player.log path exactly as before."""
    default_player_log = tmp_path / "Player.log"
    monkeypatch.setattr(type(config), "rust_log_path", property(lambda self: default_player_log))
    monkeypatch.setattr("src.core.history_store.history_store.get_rust_path", lambda: "")
    monkeypatch.setattr("src.services.steam_service.find_rust_install_path", lambda: None)

    watcher = LogWatcher(on_disconnect=lambda reason: None, on_error=lambda err: None)
    resolved = watcher._resolve_log_path()
    assert resolved == default_player_log
