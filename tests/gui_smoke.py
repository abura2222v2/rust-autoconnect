"""Capture local GUI smoke-test screenshots without starting services."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / ".pytest_tmp" / "gui_smoke"


def capture(window, destination: Path) -> None:
    from PIL import ImageGrab

    window.deiconify()
    was_topmost = bool(window.attributes("-topmost"))
    window.attributes("-topmost", True)
    try:
        window.lift()
        window.focus_force()
        window.update_idletasks()
        window.update()
        time.sleep(0.4)

        x = window.winfo_rootx()
        y = window.winfo_rooty()
        width = window.winfo_width()
        height = window.winfo_height()
        ImageGrab.grab(bbox=(x, y, x + width, y + height)).save(destination)
    finally:
        window.attributes("-topmost", was_topmost)


def main() -> int:
    appdata_dir = PROJECT_ROOT / ".pytest_tmp" / "gui_smoke_appdata"
    os.environ["APPDATA"] = str(appdata_dir)
    sys.path.insert(0, str(PROJECT_ROOT))

    from src.core.config import config
    from src.core.history_store import HistoryStore
    from src.gui.main_window import MainWindow

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # This file belongs solely to the smoke-test fixture and makes every run
    # independent from the previous screenshot data.
    config.data_file.unlink(missing_ok=True)
    store = HistoryStore()
    store.add_to_history("54.37.244.21:28015", "Rustoria EU Long")
    store.add_to_history("104.129.3.45:28015", "Rustoria US Main")
    store.toggle_favorite("54.37.244.21:28015", "Rustoria EU Long")
    store.set_armed_server("54.37.244.21:28015")

    window = MainWindow(history_mgr=store)
    try:
        window.update_entry("client.connect 54.37.244.21:28015")
        window.set_connection_state("Idle", "2h ago")
        window.log("Rust AutoConnect starting")
        window.log("Service status: Online", color="#47A66B")
        window.log("Querying server info")
        window.log("Connection accepted", color="#47A66B")
        capture(window, OUTPUT_DIR / "connect.png")

        window.geometry("1280x728")
        window.update_idletasks()
        capture(window, OUTPUT_DIR / "connect_wide.png")

        drag_start = SimpleNamespace(x_root=100)
        window._start_home_resize(drag_start)
        window._resize_home_panels(SimpleNamespace(x_root=10_000))
        window.update_idletasks()
        window.update()
        # Regression capture while the pointer is still held: the visible sash
        # itself must follow the panel boundary, with no DPI-scaled overlay.
        capture(window, OUTPUT_DIR / "connect_history_dragging.png")
        window._finish_home_resize(drag_start)
        capture(window, OUTPUT_DIR / "connect_history_max.png")
        window._history_width = 0
        window._apply_home_split(window.home_content.winfo_width())
        capture(window, OUTPUT_DIR / "connect_history_min.png")
        window._reset_home_split(None)

        window.show_bench_frame()
        capture(window, OUTPUT_DIR / "benchmark.png")

        window.show_benchmark_view("Ranking")
        capture(window, OUTPUT_DIR / "benchmark_online_ranking.png")
        window.show_benchmark_view("Run log")

        window._bench_controls_width = 10_000
        window._apply_bench_split(window.bench_content.winfo_width())
        capture(window, OUTPUT_DIR / "benchmark_controls_max.png")
        bench_drag_start = SimpleNamespace(x_root=100)
        window._start_bench_resize(bench_drag_start)
        window._resize_bench_panels(SimpleNamespace(x_root=10_000))
        window.update_idletasks()
        window.update()
        capture(window, OUTPUT_DIR / "benchmark_dragging.png")
        window._finish_bench_resize(bench_drag_start)
        window._reset_bench_split(None)

        window.show_settings_frame()
        capture(window, OUTPUT_DIR / "settings.png")

        window._show_telegram_link_overlay("ABCD1234")
        capture(window, OUTPUT_DIR / "telegram_pairing_overlay.png")
        window._close_telegram_link_overlay()
    finally:
        window.destroy()

    print(f"GUI smoke screenshots written to {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
