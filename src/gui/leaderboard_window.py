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
        self.geometry("750x500")
        self.resizable(False, False)
        
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        
        # Search Frame
        self.search_frame = ctk.CTkFrame(self)
        self.search_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        
        self.search_entry = ctk.CTkEntry(self.search_frame, placeholder_text="Search Player / CPU / Disk...", width=300)
        self.search_entry.pack(side="left", padx=10, pady=10)
        
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
        threading.Thread(target=self._fetch_bg, args=(query, is_new_search), daemon=True).start()
        
    def _fetch_bg(self, query, is_new_search):
        from ..services.leaderboard_service import leaderboard_service
        data = leaderboard_service.fetch_leaderboard(limit=self.limit, offset=self.offset, search_query=query)
        self.after(0, lambda: self._render_data(data, is_new_search))
        
    def _render_data(self, data, is_new_search):
        self.search_btn.configure(state="normal")
        self.load_more_btn.configure(state="normal")
        
        if is_new_search and hasattr(self, 'lbl_status'):
            self.lbl_status.destroy()
            
        if is_new_search and not data:
            ctk.CTkLabel(self.scroll, text=self.i18n.t("lb_err_empty")).pack(pady=20)
            return
            
        if is_new_search:
            header = ctk.CTkFrame(self.scroll)
            header.pack(fill="x", pady=2)
            ctk.CTkLabel(header, text=self.i18n.t("lb_rank"), width=50).pack(side="left", padx=5)
            ctk.CTkLabel(header, text=self.i18n.t("lb_player"), width=130, anchor="w").pack(side="left", padx=5)
            ctk.CTkLabel(header, text=self.i18n.t("lb_time"), width=70).pack(side="left", padx=5)
            ctk.CTkLabel(header, text=self.i18n.t("lb_cpu"), width=180, anchor="w").pack(side="left", padx=5)
            ctk.CTkLabel(header, text="Disk", width=180, anchor="w").pack(side="left", padx=5)
        
        if not data:
            self.load_more_btn.configure(state="disabled", text="End of Results")
            return
            
        self.load_more_btn.configure(text="Load More ⬇")
            
        for row in data:
            self.current_data.append(row)
            idx = len(self.current_data)
            
            f = ctk.CTkFrame(self.scroll)
            f.pack(fill="x", pady=2)
            ctk.CTkLabel(f, text=f"#{idx}", width=50).pack(side="left", padx=5)
            ctk.CTkLabel(f, text=row.get('player_name', ''), width=130, anchor="w").pack(side="left", padx=5)
            ctk.CTkLabel(f, text=f"{row.get('time_seconds', 0.0):.1f}s", width=70, text_color="#50C878").pack(side="left", padx=5)
            
            cpu_txt = row.get('cpu_model', '')
            if '[' in cpu_txt: cpu_txt = cpu_txt.split('[')[0].strip() # Hide hardware ID in UI
            ctk.CTkLabel(f, text=cpu_txt[:25], width=180, anchor="w", font=ctk.CTkFont(size=11)).pack(side="left", padx=5)
            
            disk_txt = row.get('disk_model', '')
            if '[' in disk_txt: disk_txt = disk_txt.split('[')[0].strip() # Hide hardware ID in UI
            ctk.CTkLabel(f, text=disk_txt[:25], width=180, anchor="w", font=ctk.CTkFont(size=11)).pack(side="left", padx=5)
            
        self.offset += self.limit
