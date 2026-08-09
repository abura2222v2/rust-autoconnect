"""Read-only UI for aggregated anonymous benchmark configurations."""

from __future__ import annotations

import threading

import customtkinter as ctk

from .main_window import COLORS


class LeaderboardWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.offset = 0
        self.limit = 30
        self.current_data = []
        self._load_generation = 0

        self.title("Global Benchmark")
        self.geometry("930x640")
        self.minsize(760, 480)
        self.configure(fg_color=COLORS["canvas"])
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        search_frame = ctk.CTkFrame(self, fg_color=COLORS["surface"], corner_radius=0)
        search_frame.grid(row=0, column=0, sticky="ew", padx=14, pady=14)
        search_frame.grid_columnconfigure(0, weight=1)
        self.search_entry = ctk.CTkEntry(search_frame, placeholder_text="Search CPU or storage", fg_color=COLORS["surface_alt"])
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=(12, 8), pady=10)
        self.sort_var = ctk.StringVar(value="Fastest")
        self.sort_menu = ctk.CTkOptionMenu(search_frame, values=["Fastest", "Slowest"], variable=self.sort_var, width=105)
        self.sort_menu.grid(row=0, column=1, padx=4, pady=10)
        self.search_btn = ctk.CTkButton(search_frame, text="Search", width=90, command=self._on_search)
        self.search_btn.grid(row=0, column=2, padx=(4, 12), pady=10)

        self.scroll = ctk.CTkScrollableFrame(self, fg_color=COLORS["surface"], corner_radius=0)
        self.scroll.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 8))
        self.bottom_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.bottom_frame.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 14))
        self.load_more_btn = ctk.CTkButton(self.bottom_frame, text="Load More", command=self._load_more)
        self.load_more_btn.pack()

        self.grab_set()
        if hasattr(parent, "dispatch_ui"):
            self._load_data(is_new_search=True)
        else:
            ctk.CTkLabel(self.scroll, text="Leaderboard preview is ready.").pack(pady=18)

    def _on_search(self):
        self._load_data(is_new_search=True)

    def _load_more(self):
        self._load_data(is_new_search=False)

    def _load_data(self, is_new_search=True):
        if is_new_search:
            self._load_generation += 1
            self.offset = 0
            self.current_data.clear()
            for widget in self.scroll.winfo_children():
                widget.destroy()
            ctk.CTkLabel(self.scroll, text="Loading anonymous configuration statistics...").pack(pady=18)
        self.search_btn.configure(state="disabled")
        self.load_more_btn.configure(state="disabled")
        generation = self._load_generation
        query = self.search_entry.get().strip()
        sort_order = "asc" if self.sort_var.get() == "Fastest" else "desc"
        threading.Thread(
            target=self._fetch_bg,
            args=(query, sort_order, is_new_search, generation),
            daemon=True,
            name="leaderboard-fetch",
        ).start()

    def _fetch_bg(self, query, sort_order, is_new_search, generation):
        from ..services.leaderboard_service import leaderboard_service

        data = leaderboard_service.fetch_configurations(self.limit, self.offset, query, sort_order)
        self._dispatch(self._render_data, data, is_new_search, generation, leaderboard_service.last_error)

    def _dispatch(self, callback, *args):
        if hasattr(self.parent, "dispatch_ui"):
            self.parent.dispatch_ui(callback, *args)
        # Standalone windows are used only by local UI tests and do not own the
        # controller queue needed for safe worker-thread callbacks.

    def _render_data(self, data, is_new_search, generation=None, error=None):
        if generation is None:
            generation = self._load_generation
        try:
            window_exists = self.winfo_exists()
        except Exception:
            return
        if generation != self._load_generation or not window_exists:
            return
        self.search_btn.configure(state="normal")
        if is_new_search:
            for widget in self.scroll.winfo_children():
                widget.destroy()
        if not data and is_new_search:
            message = "No public results yet." if not error else "Leaderboard is unavailable or not configured."
            ctk.CTkLabel(self.scroll, text=message, text_color=COLORS["muted"]).pack(pady=24)
            self.load_more_btn.configure(state="disabled")
            return

        normalized_data = []
        for index, row in enumerate(data):
            if "median_total_time" in row:
                normalized_data.append(row)
                continue
            # Keep the renderer compatible with the former flat result shape.
            normalized_data.append({
                "configuration_key": str(row.get("configuration_key", f"legacy-{index}")),
                "cpu": row.get("cpu", "Unknown"),
                "storage": row.get("storage", row.get("disk", "Unknown")),
                "median_total_time": row.get("total_time", 0.0),
                "installation_count": row.get("installation_count", 1),
                "run_count": row.get("run_count", 1),
            })
        self.current_data.extend(normalized_data)
        self._render_rows()
        self.offset += len(normalized_data)
        self.load_more_btn.configure(state="normal" if len(normalized_data) == self.limit else "disabled")

    def _render_rows(self):
        for widget in self.scroll.winfo_children():
            widget.destroy()
        header = ctk.CTkFrame(self.scroll, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(10, 4))
        for text, width in (("#", 42), ("MEDIAN", 84), ("CPU + STORAGE", 420), ("INSTALLS", 75), ("RUNS", 60)):
            ctk.CTkLabel(header, text=text, width=width, anchor="w", text_color=COLORS["muted"], font=ctk.CTkFont(size=10, weight="bold")).pack(side="left", padx=3)

        for index, row in enumerate(self.current_data, start=1):
            frame = ctk.CTkFrame(self.scroll, fg_color=COLORS["surface_alt"], corner_radius=4)
            frame.pack(fill="x", padx=10, pady=2)
            ctk.CTkLabel(frame, text=f"#{index}", width=42, anchor="w").pack(side="left", padx=6, pady=8)
            median = float(row.get("median_total_time", 0.0))
            ctk.CTkLabel(frame, text=f"{median:.1f}s", width=84, anchor="w", text_color=COLORS["accent"], font=ctk.CTkFont(weight="bold")).pack(side="left", padx=3)
            cpu = str(row.get("cpu", "Unknown"))
            storage = str(row.get("storage", "Unknown"))
            ctk.CTkLabel(frame, text=f"{cpu} | {storage}", width=420, anchor="w").pack(side="left", padx=3)
            ctk.CTkLabel(frame, text=str(row.get("installation_count", 0)), width=75).pack(side="left", padx=3)
            ctk.CTkLabel(frame, text=str(row.get("run_count", 0)), width=60).pack(side="left", padx=3)
            ctk.CTkButton(frame, text="Details", width=64, height=26, command=lambda item=row: self._load_detail(item)).pack(side="right", padx=8)

    def _load_detail(self, row):
        key = str(row.get("configuration_key", ""))
        if not key:
            return
        threading.Thread(target=self._fetch_detail_bg, args=(key,), daemon=True, name="leaderboard-detail").start()

    def _fetch_detail_bg(self, key):
        from ..services.leaderboard_service import leaderboard_service

        detail = leaderboard_service.fetch_configuration_detail(key)
        self._dispatch(self._show_detail, detail)

    def _show_detail(self, detail):
        if not detail or not self.winfo_exists():
            return
        popup = ctk.CTkToplevel(self)
        popup.title("Configuration details")
        popup.geometry("540x440")
        popup.configure(fg_color=COLORS["canvas"])
        summary = detail.get("summary", {})
        ctk.CTkLabel(
            popup,
            text=(f"Median: {float(summary.get('median_total_time', 0.0)):.1f}s\n"
                  f"Installations: {summary.get('installation_count', 0)}\n"
                  f"Runs: {summary.get('run_count', 0)}\n"
                  f"Range: {summary.get('min_total_time', '?')} - {summary.get('max_total_time', '?')}s"),
            justify="left",
            font=ctk.CTkFont(size=14),
        ).pack(anchor="w", padx=18, pady=18)
        scroll = ctk.CTkScrollableFrame(popup, fg_color=COLORS["surface"])
        scroll.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        for item in detail.get("installations", []):
            ctk.CTkLabel(
                scroll,
                text=f"Anonymous installation: {float(item.get('median_total_time', 0.0)):.1f}s | {item.get('run_count', 0)} runs",
                anchor="w",
            ).pack(fill="x", padx=10, pady=6)
