"""Integration tests for the web UI's real hardware benchmark
(WebBridge.run_benchmark in src/web/bridge.py).

This replaces a fake stub that computed a number from an md5 hash of the CPU
name and never launched Rust at all. These tests drive the real cfg
backup/restore and log-watching state machine end to end - through a fake
Rust install directory and a fake log file - so a regression here (which
would touch the user's real Rust cfg files) gets caught before it ships.
Never touches Steam: os.startfile is patched so a test can never actually
launch the real game.
"""
import asyncio
import copy
import threading
import time
from pathlib import Path

import pytest

from src.core.config import config
from src.core.history_store import DEFAULT_DATA, history_store
from src.web.bridge import WebBridge


@pytest.fixture(autouse=True)
def isolate_history_file(monkeypatch, tmp_path):
    """The history_store singleton's in-memory data (including
    benchmark_runs) is shared across the whole test session - reset it per
    test so one test's recorded run can't leak into another's assertions."""
    monkeypatch.setattr(type(config), "data_file", property(lambda self: tmp_path / "test_data.json"))
    history_store.data = copy.deepcopy(DEFAULT_DATA)
    yield
    history_store.data = copy.deepcopy(DEFAULT_DATA)


@pytest.fixture
def event_loop_thread():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True, name="test-benchmark-loop")
    thread.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)


@pytest.fixture
def bridge(event_loop_thread, monkeypatch):
    b = WebBridge()
    b.set_event_loop(event_loop_thread)
    monkeypatch.setattr(b.hardware_service, "get_benchmark_storage", lambda rust_path: ("Test SSD", "NVMe"))
    monkeypatch.setattr(b.leaderboard_service, "submit_run", lambda run: True)
    yield b
    b.connect_engine.stop(explicit=True)


def _wait_until(predicate, timeout=15.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _make_fake_rust_dir(tmp_path) -> Path:
    """A fake Rust install with the real BenchmarkFiles assets copied in, so
    the port's file-preparation step (bind file, demo copy, cfg swap) runs
    against real files rather than stubs."""
    rust_dir = tmp_path / "Rust"
    (rust_dir / "cfg").mkdir(parents=True)
    (rust_dir / "cfg" / "keys.cfg").write_text("bind w forward\n", encoding="utf-8")
    (rust_dir / "RustClient.exe").write_text("", encoding="utf-8")
    return rust_dir


def _capture_broadcasts(bridge):
    events = []
    bridge.broadcast = lambda event_type, data=None: events.append((event_type, data or {}))
    return events


class _FakeProcess:
    """Minimal stand-in for process_monitor driven by a background thread
    that appends lines to the fake Rust log on a schedule, mirroring the
    real sequence: boot -> menu -> F5 -> demo spawn."""

    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.pids = set()

    def is_rust_running(self) -> bool:
        return bool(self.pids)

    def get_rust_pids(self) -> set:
        return set(self.pids)

    def force_kill_pid(self, pid: int) -> None:
        self.pids.discard(pid)

    def _append(self, line: str) -> None:
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def drive_full_success(self) -> None:
        def run():
            time.sleep(0.2)
            self.pids = {4242}
            time.sleep(2.2)
            self._append("[Bootstrap] DONE!")
            time.sleep(2.2)
            self._append("Demo is playing: RustTweaker_bm")
            time.sleep(2.2)
            self._append("[6.6s] Spawning World")
        threading.Thread(target=run, daemon=True).start()

    def drive_too_fast_to_be_real(self) -> None:
        def run():
            time.sleep(0.1)
            self.pids = {4242}
            time.sleep(0.1)
            self._append("[Bootstrap] DONE!")
            time.sleep(0.1)
            self._append("Demo is playing: RustTweaker_bm")
            time.sleep(0.1)
            self._append("[0.4s] Spawning World")
        threading.Thread(target=run, daemon=True).start()

    def drive_success_but_rust_wont_close(self) -> None:
        def run():
            time.sleep(0.2)
            self.pids = {4242, 9999}  # a second, unrelated Rust process
            time.sleep(2.2)
            self._append("[Bootstrap] DONE!")
            time.sleep(2.2)
            self._append("Demo is playing: RustTweaker_bm")
            time.sleep(2.2)
            self._append("[6.6s] Spawning World")
        threading.Thread(target=run, daemon=True).start()


@pytest.fixture
def fake_env(tmp_path, monkeypatch, bridge):
    """Wires a fake Rust install + fake log file + fake process list into
    the bridge, and points the benchmark's file-search at the real,
    read-only BenchmarkFiles assets so the copy step is genuine."""
    rust_dir = _make_fake_rust_dir(tmp_path)
    fake_log = tmp_path / "output_log.txt"
    fake_log.write_text("", encoding="utf-8")
    monkeypatch.setattr(type(config), "rust_log_path", property(lambda self: fake_log))
    history_store.set_rust_path(str(rust_dir))

    process = _FakeProcess(fake_log)
    monkeypatch.setattr("src.web.bridge.process_monitor.is_rust_running", process.is_rust_running)
    monkeypatch.setattr("src.web.bridge.process_monitor.get_rust_pids", process.get_rust_pids)
    monkeypatch.setattr("src.web.bridge.process_monitor.force_kill_pid", process.force_kill_pid)

    return rust_dir, process


def _wire_launch(monkeypatch, driver) -> None:
    """The benchmark's timing (time_to_menu, demo_load_time) is measured
    from the moment it "launches" Rust, so the fake game sequence must
    start exactly when the real os.startfile call would happen - not
    earlier, or the clock runs out before the watcher is even tailing."""
    monkeypatch.setattr("src.web.bridge.os.startfile", lambda url: driver())


def test_full_benchmark_run_records_a_real_measured_result(bridge, fake_env, monkeypatch):
    """End-to-end: cfg is backed up, swapped, and restored; a real timed run
    is recorded with the schema history_store.add_benchmark_run requires
    (the old fake stub's dict shape would have raised ValueError there)."""
    rust_dir, process = fake_env
    original_keys_cfg = (rust_dir / "cfg" / "keys.cfg").read_text(encoding="utf-8")
    events = _capture_broadcasts(bridge)

    _wire_launch(monkeypatch, process.drive_full_success)
    res = bridge.run_benchmark()
    assert res["success"] is True

    assert _wait_until(
        lambda: any(e[1].get("status") == "completed" for e in events if e[0] == "benchmark_status"),
        timeout=15.0,
    )

    runs = history_store.get_benchmark_runs()
    assert len(runs) == 1
    run = runs[0]
    assert run["time_to_menu"] >= 2.0
    assert run["demo_load_time"] >= 2.0
    assert run["total_time"] == pytest.approx(run["time_to_menu"] + run["demo_load_time"], abs=0.01)
    assert isinstance(run["id"], str) and run["id"]
    assert isinstance(run["configuration_key"], str) and run["configuration_key"]
    assert run["sync_state"] == "synced"  # leaderboard_service.submit_run was mocked to succeed

    # The player's actual keybinds must come back exactly as they were.
    assert (rust_dir / "cfg" / "keys.cfg").read_text(encoding="utf-8") == original_keys_cfg
    assert not list(rust_dir.glob(".rust_autoconnect_cfg_backup_*"))
    assert not list(rust_dir.glob(".rust_autoconnect_cfg_work_*"))
    assert not bridge._is_benchmarking


def test_suspiciously_fast_run_is_rejected_not_recorded(bridge, fake_env, monkeypatch):
    """A run finishing in well under 2s per phase is almost certainly a
    scripted/spoofed log rather than a real playthrough - must be rejected,
    not silently accepted onto the shared leaderboard."""
    rust_dir, process = fake_env
    events = _capture_broadcasts(bridge)

    _wire_launch(monkeypatch, process.drive_too_fast_to_be_real)
    res = bridge.run_benchmark()
    assert res["success"] is True

    assert _wait_until(lambda: any(e[1].get("status") == "rejected" for e in events if e[0] == "benchmark_status"))
    assert not history_store.get_benchmark_runs()
    # cfg must still be restored even on a rejected run.
    assert not list(rust_dir.glob(".rust_autoconnect_cfg_backup_*"))


def test_run_benchmark_refuses_to_start_a_second_concurrent_run(bridge, fake_env):
    rust_dir, process = fake_env
    bridge._is_benchmarking = True
    try:
        res = bridge.run_benchmark()
        assert res["success"] is False
    finally:
        bridge._is_benchmarking = False


def test_restore_deferred_when_rust_wont_close_then_recovers_later(bridge, fake_env, monkeypatch):
    """If force_kill_pid doesn't actually take Rust down (another Rust
    process happens to share the machine), the cfg swap must NOT be
    restored underneath a still-running game - it must wait and recover
    once Rust actually closes, exactly like the legacy GUI's behavior."""
    rust_dir, process = fake_env
    events = _capture_broadcasts(bridge)

    _wire_launch(monkeypatch, process.drive_success_but_rust_wont_close)
    res = bridge.run_benchmark()
    assert res["success"] is True

    assert _wait_until(lambda: any(e[1].get("status") == "restore_pending" for e in events if e[0] == "benchmark_status"))
    # The benchmark cfg must still be in place - restoring now would corrupt
    # the session of whatever Rust process is still running.
    assert (rust_dir / "cfg" / "keys.cfg").read_text(encoding="utf-8").count("RustTweaker_bm") >= 1
    assert bridge._pending_benchmark_restore is not None

    # Now the (unrelated) remaining Rust process closes.
    process.pids.clear()

    assert _wait_until(lambda: any(e[1].get("status") == "restore_done" for e in events if e[0] == "benchmark_status"), timeout=10.0)
    assert bridge._pending_benchmark_restore is None
    assert not list(rust_dir.glob(".rust_autoconnect_cfg_backup_*"))
