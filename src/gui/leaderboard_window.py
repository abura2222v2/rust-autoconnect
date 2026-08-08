import customtkinter as ctk
import threading

class LeaderboardWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.i18n = parent.i18n
        
        self.title(self.i18n.t("lb_title"))
        self.geometry("600x400")
        self.resizable(False, False)
        
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        
        self.lbl_status = ctk.CTkLabel(self, text=self.i18n.t("lb_load"))
        self.lbl_status.grid(row=0, column=0, pady=10)
        
        self.scroll = ctk.CTkScrollableFrame(self)
        self.scroll.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        
        self.grab_set()
        threading.Thread(target=self._load_data, daemon=True).start()
        
    def _load_data(self):
        from ..services.leaderboard_service import leaderboard_service
        data = leaderboard_service.fetch_top_30()
        self.after(0, lambda: self._render_data(data))
        
    def _render_data(self, data):
        self.lbl_status.destroy()
        if not data:
            ctk.CTkLabel(self.scroll, text=self.i18n.t("lb_err_empty")).pack(pady=20)
            return
            
        header = ctk.CTkFrame(self.scroll)
        header.pack(fill="x", pady=2)
        ctk.CTkLabel(header, text=self.i18n.t("lb_rank"), width=50).pack(side="left", padx=5)
        ctk.CTkLabel(header, text=self.i18n.t("lb_player"), width=150, anchor="w").pack(side="left", padx=5)
        ctk.CTkLabel(header, text=self.i18n.t("lb_time"), width=80).pack(side="left", padx=5)
        ctk.CTkLabel(header, text=self.i18n.t("lb_cpu"), width=180, anchor="w").pack(side="left", padx=5)
        
        for idx, row in enumerate(data):
            f = ctk.CTkFrame(self.scroll)
            f.pack(fill="x", pady=2)
            ctk.CTkLabel(f, text=f"#{idx+1}", width=50).pack(side="left", padx=5)
            ctk.CTkLabel(f, text=row.get('player_name', ''), width=150, anchor="w").pack(side="left", padx=5)
            ctk.CTkLabel(f, text=f"{row.get('time_seconds', 0.0):.1f}s", width=80, text_color="#50C878").pack(side="left", padx=5)
            ctk.CTkLabel(f, text=row.get('cpu_model', '')[:25], width=180, anchor="w", font=ctk.CTkFont(size=11)).pack(side="left", padx=5)
