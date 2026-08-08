import customtkinter as ctk
import threading

class LeaderboardWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.i18n = parent.i18n
        self.offset = 0
        self.limit = 30
        self.current_data = []
        
        self.title(self.i18n.t("lb_title"))
        self.geometry("850x600")
        self.resizable(False, False)
        
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        
        # Search Frame
        self.search_frame = ctk.CTkFrame(self)
        self.search_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        
        self.search_entry = ctk.CTkEntry(self.search_frame, placeholder_text="Search Player / CPU / Disk...", width=300)
        self.search_entry.pack(side="left", padx=10, pady=10)
        
        self.sort_var = ctk.StringVar(value="Fastest")
        self.sort_menu = ctk.CTkOptionMenu(self.search_frame, values=["Fastest", "Slowest"], variable=self.sort_var, width=100)
        self.sort_menu.pack(side="left", padx=5, pady=10)
        
        self.search_btn = ctk.CTkButton(self.search_frame, text="Search", width=100, command=self._on_search)
        self.search_btn.pack(side="left", padx=10, pady=10)
        
        self.scroll = ctk.CTkScrollableFrame(self)
        self.scroll.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        
        self.bottom_frame = ctk.CTkFrame(self)
        self.bottom_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        
        self.load_more_btn = ctk.CTkButton(self.bottom_frame, text="Load More ⬇", command=self._load_more)
        self.load_more_btn.pack(pady=10)
        
        self.grab_set()
        
        self._load_data(is_new_search=True)
        
    def _on_search(self):
        self._load_data(is_new_search=True)
        
    def _load_more(self):
        self._load_data(is_new_search=False)
        
    def _load_data(self, is_new_search=True):
        if is_new_search:
            self.offset = 0
            self.current_data.clear()
            for widget in self.scroll.winfo_children():
                widget.destroy()
            self.lbl_status = ctk.CTkLabel(self.scroll, text=self.i18n.t("lb_load"))
            self.lbl_status.pack(pady=10)
            
        self.search_btn.configure(state="disabled")
        self.load_more_btn.configure(state="disabled")
        
        query = self.search_entry.get().strip()
        sort_val = "asc" if self.sort_var.get() == "Fastest" else "desc"
        threading.Thread(target=self._fetch_bg, args=(query, sort_val, is_new_search), daemon=True).start()
        
    def _fetch_bg(self, query, sort_val, is_new_search):
        from ..services.leaderboard_service import leaderboard_service
        data = leaderboard_service.fetch_leaderboard(limit=self.limit, offset=self.offset, search_query=query, sort_order=sort_val)
        self.after(0, lambda: self._render_data(data, is_new_search))
        
    def _render_data(self, data, is_new_search):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        self.search_btn.configure(state="normal")
        
        if is_new_search and hasattr(self, 'lbl_status'):
            self.lbl_status.destroy()
            
        if is_new_search and not data:
            for widget in self.scroll.winfo_children():
                widget.destroy()
            ctk.CTkLabel(self.scroll, text=self.i18n.t("lb_err_empty")).pack(pady=20)
            self.load_more_btn.configure(state="disabled", text="End of Results")
            return
            
        if not data or len(data) < self.limit:
            self.load_more_btn.configure(state="disabled", text="End of Results")
        else:
            self.load_more_btn.configure(state="normal", text="Load More ⬇")
            
        if not data:
            return
        
        for row in data:
            self.current_data.append(row)
            
        for widget in self.scroll.winfo_children():
            widget.destroy()
            
        header = ctk.CTkFrame(self.scroll)
        header.pack(fill="x", pady=2)
        ctk.CTkLabel(header, text=self.i18n.t("lb_rank"), width=50).pack(side="left", padx=5)
        ctk.CTkLabel(header, text=self.i18n.t("lb_time"), width=70).pack(side="left", padx=5)
        ctk.CTkLabel(header, text=self.i18n.t("lb_cpu"), width=250, anchor="w").pack(side="left", padx=5)
        ctk.CTkLabel(header, text=self.i18n.t("lb_disk"), width=250, anchor="w").pack(side="left", padx=5)
        
        # Aggregate data by CPU + Disk using full accumulated dataset
        groups = {}
        for row in self.current_data:
            cpu_txt = row.get('cpu', '')
            if '[' in cpu_txt: cpu_txt = cpu_txt.split('[')[0].strip()
            
            disk_txt = row.get('disk', '')
            if '[' in disk_txt: disk_txt = disk_txt.split('[')[0].strip()
            
            key = (cpu_txt, disk_txt)
            if key not in groups:
                groups[key] = []
            groups[key].append(row)
            
        # Sort groups by average time of top 10
        sorted_groups = []
        for key, rows in groups.items():
            rows.sort(key=lambda x: x.get('total_time', 999.0))
            top_10 = rows[:10]
            avg_time = sum(r.get('total_time', 0.0) for r in top_10) / len(top_10)
            sorted_groups.append((key, avg_time, top_10))
            
        sorted_groups.sort(key=lambda x: x[1], reverse=(self.sort_var.get() == "Slowest"))
            
        for i, (key, avg_time, rows) in enumerate(sorted_groups):
            rank = i + 1
            
            container = ctk.CTkFrame(self.scroll, fg_color="transparent")
            container.pack(fill="x", pady=2)
            
            # Group Header Frame
            f = ctk.CTkFrame(container)
            f.pack(fill="x")
            
            ctk.CTkLabel(f, text=f"#{rank}", width=50, font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)
            ctk.CTkLabel(f, text=f"{avg_time:.1f}s", width=70, text_color="#FADA5E", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)
            
            cpu_name = key[0][:40] + ("..." if len(key[0]) > 40 else "")
            disk_name = key[1][:40] + ("..." if len(key[1]) > 40 else "")
            
            ctk.CTkLabel(f, text=cpu_name, width=250, anchor="w", font=ctk.CTkFont(size=12)).pack(side="left", padx=5)
            ctk.CTkLabel(f, text=disk_name, width=250, anchor="w", font=ctk.CTkFont(size=12)).pack(side="left", padx=5)
            
            # Sub-frame for top 10 players (hidden by default)
            sub_f = ctk.CTkFrame(container, fg_color="transparent")
            
            for j, row in enumerate(rows):
                p_rank = j + 1
                p_time = row.get('total_time', 0.0)
                
                row_f = ctk.CTkFrame(sub_f, fg_color=("gray80", "gray15"))
                row_f.pack(fill="x", pady=1, padx=(60, 5))
                ctk.CTkLabel(row_f, text=f"#{p_rank}", width=30).pack(side="left", padx=5)
                ctk.CTkLabel(row_f, text=f"{p_time:.1f}s", width=60, text_color=("gray30", "gray70")).pack(side="left", padx=5)
                
            def make_toggle(frm, b):
                def _toggle():
                    if frm.winfo_ismapped():
                        frm.pack_forget()
                        b.configure(text="▼")
                    else:
                        frm.pack(fill="x", pady=(2, 0))
                        b.configure(text="▲")
                return _toggle
                
            btn = ctk.CTkButton(f, text="▼", width=30, height=24)
            btn.configure(command=make_toggle(sub_f, btn))
            btn.pack(side="right", padx=10)
            
        self.offset += self.limit
