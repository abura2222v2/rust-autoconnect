import customtkinter as ctk
import threading
import pystray
from PIL import Image, ImageDraw
from typing import Optional

from .tooltip import ToolTip
from ..core.i18n import i18n, I18nManager
from ..core.history_store import history_store, HistoryStore

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class MainWindow(ctk.CTk):
    def __init__(self, history_mgr: Optional[HistoryStore] = None, i18n_mgr: Optional[I18nManager] = None):
        super().__init__()
        
        self.history_store = history_mgr if history_mgr is not None else history_store
        self.i18n = i18n_mgr if i18n_mgr is not None else i18n

        self.lang = self.history_store.get_lang()
        self.i18n.set_lang(self.lang)

        self.title(self.t("title"))
        self.geometry("950x550")
        self.minsize(800, 450)

        self._search_timer = None
        self.is_auto_update_enabled = self.history_store.get_auto_update()
        self.auto_update = ctk.BooleanVar(value=self.is_auto_update_enabled)

        self.tray_icon = None
        self.protocol('WM_DELETE_WINDOW', self.shutdown)
        self.bind('<Unmap>', self.on_unmap)

        # Main Grid Layout: Sidebar (0) and Content (1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ==========================================
        # 1. SIDEBAR FRAME
        # ==========================================
        self.sidebar_frame = ctk.CTkFrame(self, width=160, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(4, weight=1)

        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="Rust AC", font=ctk.CTkFont(size=22, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 30))

        self.nav_home_btn = ctk.CTkButton(self.sidebar_frame, text=self.t("nav_home"), command=self.show_home_frame, fg_color="transparent", border_width=2, text_color=("gray10", "#DCE4EE"))
        self.nav_home_btn.grid(row=1, column=0, padx=10, pady=10, sticky="ew")

        self.nav_bench_btn = ctk.CTkButton(self.sidebar_frame, text=self.t("nav_bench"), command=self.show_bench_frame, fg_color="transparent", border_width=2, text_color=("gray10", "#DCE4EE"))
        self.nav_bench_btn.grid(row=2, column=0, padx=10, pady=10, sticky="ew")

        self.nav_settings_btn = ctk.CTkButton(self.sidebar_frame, text=self.t("nav_settings"), command=self.show_settings_frame, fg_color="transparent", border_width=2, text_color=("gray10", "#DCE4EE"))
        self.nav_settings_btn.grid(row=3, column=0, padx=10, pady=10, sticky="ew")

        self.rust_status_label = ctk.CTkLabel(self.sidebar_frame, text=self.t("rust_off"), font=ctk.CTkFont(weight="bold"), text_color="#C25A5A")
        self.rust_status_label.grid(row=5, column=0, padx=20, pady=(10, 20))

        # ==========================================
        # 2. CONTENT FRAMES (Overlapping Grid)
        # ==========================================
        self.home_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.bench_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.settings_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")

        # Place them all in the same grid cell
        for frame in (self.home_frame, self.bench_frame, self.settings_frame):
            frame.grid(row=0, column=1, sticky="nsew")

        # ==========================================
        # 2.1 HOME FRAME (History + Connection)
        # ==========================================
        self.home_frame.grid_columnconfigure(1, weight=1)
        self.home_frame.grid_rowconfigure(0, weight=1)

        # Left side of Home: History
        self.history_panel = ctk.CTkFrame(self.home_frame, width=260, corner_radius=0)
        self.history_panel.grid(row=0, column=0, sticky="nsew")
        self.history_panel.grid_rowconfigure(3, weight=1)

        self.history_label = ctk.CTkLabel(self.history_panel, text=self.t("history"), font=ctk.CTkFont(size=16, weight="bold"))
        self.history_label.grid(row=0, column=0, padx=20, pady=(20, 5))

        self.filter_var = ctk.StringVar(value="All Servers")
        self.filter_menu = ctk.CTkOptionMenu(self.history_panel, values=["All Servers", "Favorites"], variable=self.filter_var, command=lambda e: self.refresh_history_ui())
        self.filter_menu.grid(row=1, column=0, padx=20, pady=(0, 10), sticky="ew")

        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", self._on_search_changed)
        self.search_entry = ctk.CTkEntry(self.history_panel, placeholder_text="Search...", textvariable=self.search_var)
        self.search_entry.grid(row=2, column=0, padx=20, pady=(0, 10), sticky="ew")

        self.history_scroll = ctk.CTkScrollableFrame(self.history_panel)
        self.history_scroll.grid(row=3, column=0, sticky="nsew", padx=10, pady=(0, 10))

        # Right side of Home: Connection & Logs
        self.connection_panel = ctk.CTkFrame(self.home_frame, fg_color="transparent")
        self.connection_panel.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        self.connection_panel.grid_columnconfigure(0, weight=1)
        self.connection_panel.grid_rowconfigure(1, weight=1)

        self.input_frame = ctk.CTkFrame(self.connection_panel)
        self.input_frame.grid(row=0, column=0, pady=(0, 10), sticky="ew")
        self.input_frame.grid_columnconfigure(0, weight=1)

        self.ip_entry = ctk.CTkComboBox(
            self.input_frame,
            values=[f"{f.get('name', 'Unknown')} ({f.get('ip', 'Unknown')})" for f in self.history_store.get_favorites()]
        )
        self.ip_entry.set("")
        self.ip_entry.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        self.connect_btn = ctk.CTkButton(self.input_frame, text=self.t("start"), command=self._on_connect_btn_click, width=120)
        self.connect_btn.grid(row=0, column=1, padx=10, pady=10)

        self.log_frame = ctk.CTkFrame(self.connection_panel)
        self.log_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        self.log_frame.grid_columnconfigure(0, weight=1)
        self.log_frame.grid_rowconfigure(0, weight=1)

        self.log_textbox = ctk.CTkTextbox(self.log_frame, state="disabled", font=ctk.CTkFont(family="Consolas", size=13))
        self.log_textbox.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        
        self.bottom_frame = ctk.CTkFrame(self.connection_panel, fg_color="transparent")
        self.bottom_frame.grid(row=2, column=0, sticky="e")
        self.update_check = ctk.CTkCheckBox(self.bottom_frame, text="Auto-Update Rust", variable=self.auto_update, command=self.on_auto_update_change)
        self.update_check.pack(side="right")

        # ==========================================
        # 2.2 BENCHMARK FRAME
        # ==========================================
        self.bench_frame.grid_columnconfigure(0, weight=1)
        
        self.bench_title = ctk.CTkLabel(self.bench_frame, text=self.t("tab_bench"), font=ctk.CTkFont(size=20, weight="bold"))
        self.bench_title.pack(pady=(20,10))

        self.bench_btn = ctk.CTkButton(self.bench_frame, text=self.t("run_test"), command=self._on_run_test_click, fg_color="#3B8ED0", height=40)
        self.bench_btn.pack(pady=10)
        
        self.top_btn = ctk.CTkButton(self.bench_frame, text=self.t("lb_title"), command=self.open_leaderboard, fg_color="#FADA5E", text_color="black", height=40)
        self.top_btn.pack(pady=10)
        
        self.hardware_label = ctk.CTkLabel(self.bench_frame, text=self.t("lb_load"), justify="left", font=ctk.CTkFont(size=14))
        self.hardware_label.pack(pady=10)
        
        self.bench_log = ctk.CTkTextbox(self.bench_frame, state="disabled", font=ctk.CTkFont(family="Consolas", size=13))
        self.bench_log.pack(fill="both", expand=True, padx=40, pady=20)

        # ==========================================
        # 2.3 SETTINGS FRAME
        # ==========================================
        self.settings_frame.grid_columnconfigure(1, weight=1)
        
        self.settings_title = ctk.CTkLabel(self.settings_frame, text=self.t("settings_title"), font=ctk.CTkFont(size=20, weight="bold"))
        self.settings_title.grid(row=0, column=0, columnspan=2, padx=40, pady=(40, 20), sticky="w")

        # Language
        self.lang_label = ctk.CTkLabel(self.settings_frame, text=self.t("lang_lbl"), font=ctk.CTkFont(weight="bold"))
        self.lang_label.grid(row=1, column=0, padx=40, pady=(20, 10), sticky="w")
        
        self.lang_menu = ctk.CTkOptionMenu(
            self.settings_frame,
            values=list(I18nManager.LANG_MAP.values()),
            command=self.change_lang,
            width=200
        )
        self.lang_menu.grid(row=1, column=1, padx=40, pady=(20, 10), sticky="w")
        self.lang_menu.set(self.history_store.get_lang())

        # Tray Checkbox
        self.tray_var = ctk.BooleanVar(value=self.history_store.get_minimize_to_tray())
        self.tray_checkbox = ctk.CTkCheckBox(self.settings_frame, text=self.t("tray_lbl"), variable=self.tray_var, command=self._on_tray_change)
        self.tray_checkbox.grid(row=2, column=0, columnspan=2, padx=40, pady=20, sticky="w")
        self.tray_tooltip = ToolTip(self.tray_checkbox, self.t("tooltip_tray"))

        # Swarm Checkbox
        self.swarm_var = ctk.BooleanVar(value=self.history_store.get_swarm_enabled())
        self.swarm_checkbox = ctk.CTkCheckBox(self.settings_frame, text=self.t("swarm_lbl"), variable=self.swarm_var, command=self._on_swarm_change)
        self.swarm_checkbox.grid(row=3, column=0, columnspan=2, padx=40, pady=10, sticky="w")
        self.swarm_tooltip = ToolTip(self.swarm_checkbox, self.t("tooltip_swarm"))

        # Save User Config Button
        self.save_cfg_btn = ctk.CTkButton(self.settings_frame, text=self.t("save_cfg_btn"), command=self.save_user_config)
        self.save_cfg_btn.grid(row=4, column=0, columnspan=2, padx=40, pady=20, sticky="w")

        # Start by showing Home
        self.refresh_history_ui()
        self.show_home_frame()

    # --- NAVIGATION LOGIC ---
    def show_home_frame(self):
        self.home_frame.tkraise()
        self._highlight_nav(self.nav_home_btn)

    def show_bench_frame(self):
        self.bench_frame.tkraise()
        self._highlight_nav(self.nav_bench_btn)

    def show_settings_frame(self):
        self.settings_frame.tkraise()
        self._highlight_nav(self.nav_settings_btn)
        
    def _highlight_nav(self, active_btn):
        # Reset all
        self.nav_home_btn.configure(fg_color="transparent")
        self.nav_bench_btn.configure(fg_color="transparent")
        self.nav_settings_btn.configure(fg_color="transparent")
        # Highlight active
        active_btn.configure(fg_color=("gray75", "gray25"))

    # --- SETTINGS LOGIC ---
    def _on_tray_change(self):
        self.history_store.set_minimize_to_tray(self.tray_var.get())

    def save_user_config(self):
        pass

    def _on_swarm_change(self):
        from ..services.swarm_service import swarm_service
        is_checked = self.swarm_var.get()
        
        if is_checked:
            self.swarm_checkbox.configure(state="disabled")
            def test_and_connect():
                if swarm_service.test_connection():
                    self.history_store.set_swarm_enabled(True)
                    swarm_service.is_enabled = True
                    swarm_service.start()
                    self.after(0, lambda: self.swarm_checkbox.configure(state="normal"))
                else:
                    import tkinter.messagebox as messagebox
                    self.after(0, lambda: messagebox.showerror("Connection Error", "Failed to connect to Swarm servers."))
                    self.after(0, lambda: self.swarm_var.set(False))
                    self.after(0, lambda: self.swarm_checkbox.configure(state="normal"))
            import threading
            threading.Thread(target=test_and_connect, daemon=True).start()
        else:
            self.history_store.set_swarm_enabled(False)
            swarm_service.is_enabled = False
            swarm_service.stop()

    def change_lang(self, choice: str):
        code = choice.split(" ")[0]
        self.lang = code
        self.i18n.set_lang(code)
        self.history_store.set_lang(code)

        self.title(self.t("title"))
        self.history_label.configure(text=self.t("history"))
        self.nav_home_btn.configure(text=self.t("nav_home"))
        self.nav_bench_btn.configure(text=self.t("nav_bench"))
        self.nav_settings_btn.configure(text=self.t("nav_settings"))
        self.bench_title.configure(text=self.t("tab_bench"))
        self.bench_btn.configure(text=self.t("run_test"))
        self.top_btn.configure(text=self.t("lb_title"))
        self.settings_title.configure(text=self.t("settings_title"))
        self.lang_label.configure(text=self.t("lang_lbl"))
        self.tray_checkbox.configure(text=self.t("tray_lbl"))
        self.swarm_checkbox.configure(text=self.t("swarm_lbl"))
        if hasattr(self, 'save_cfg_btn'):
            self.save_cfg_btn.configure(text=self.t("save_cfg_btn"))
        
        if hasattr(self, 'tray_tooltip'):
            self.tray_tooltip.text = self.t("tooltip_tray")
        if hasattr(self, 'swarm_tooltip'):
            self.swarm_tooltip.text = self.t("tooltip_swarm")

        if "🟢" in self.rust_status_label.cget("text"):
            self.rust_status_label.configure(text=self.t("rust_on"))
        else:
            self.rust_status_label.configure(text=self.t("rust_off"))

        self.refresh_history_ui()

    # --- OTHER METHODS ---
    def t(self, key: str, **kwargs) -> str:
        return self.i18n.t(key, **kwargs)

    def _on_search_changed(self, *args):
        if self._search_timer is not None:
            self.after_cancel(self._search_timer)
        self._search_timer = self.after(300, self.refresh_history_ui)

    def on_auto_update_change(self):
        self.is_auto_update_enabled = self.auto_update.get()
        self.history_store.set_auto_update(self.is_auto_update_enabled)

    def _on_connect_btn_click(self):
        pass # Override in AppController

    def _on_run_test_click(self):
        pass # Override in AppController

    def open_leaderboard(self):
        from .leaderboard_window import LeaderboardWindow
        if not hasattr(self, 'lb_window') or not self.lb_window.winfo_exists():
            self.lb_window = LeaderboardWindow(self)
        else:
            self.lb_window.focus()

    def update_favorites_combobox(self):
        favorites = self.history_store.get_favorites()
        values = [f"{f.get('name', 'Unknown')} ({f.get('ip', 'Unknown')})" for f in favorites]
        self.ip_entry.configure(values=values)

    def refresh_history_ui(self):
        for widget in self.history_scroll.winfo_children():
            widget.destroy()

        show_favs_only = (self.filter_var.get() == "Favorites")
        search_query = self.search_var.get().lower().strip()

        history_items = self.history_store.get_history()
        history_items = sorted(history_items, key=lambda x: x.get("added_at", 0), reverse=True)
        favorites = self.history_store.get_favorites()

        for item in history_items:
            ip = item['ip']
            display_name = item.get('name', 'Rust Server')

            if search_query:
                if search_query not in ip.lower() and search_query not in display_name.lower():
                    continue

            is_fav = any(f.get("ip") == ip for f in favorites)
            is_armed = (self.history_store.get_armed_server() == ip)

            if show_favs_only and not is_fav:
                continue

            frame = ctk.CTkFrame(self.history_scroll, fg_color="transparent")
            frame.pack(fill="x", pady=2)

            short_name = display_name
            if len(short_name) > 30:
                short_name = short_name[:27] + "..."

            btn_text = f"{ip}\n({short_name})"
            btn = ctk.CTkButton(
                frame,
                text=btn_text,
                fg_color="#3B8ED0" if is_armed else "#2b2b2b",
                hover_color="#1F6AA5" if is_armed else "#3b3b3b",
                text_color=("gray80", "white"),
                command=lambda i=ip: self.select_history(i)
            )
            btn.pack(side="left", fill="x", expand=True, padx=(0, 5))
            btn.bind("<Double-Button-1>", lambda event, f=frame, b=btn, i=ip, n=display_name: self.start_inline_edit(f, b, i, n))

            btn_font = ctk.CTkFont(family="Arial", size=14)
            
            arm_text = "⚡"
            arm_color = "#3B8ED0" if is_armed else "#555555"
            arm_btn = ctk.CTkButton(
                frame,
                text=arm_text,
                width=28,
                height=28,
                font=btn_font,
                fg_color=arm_color,
                command=lambda i=ip: self.toggle_armed(i)
            )
            arm_btn.pack(side="left", padx=(0, 2))

            fav_text = "⭐" if is_fav else "☆"
            fav_color = "#FADA5E" if is_fav else "#555555" # Changed to yellow
            fav_btn = ctk.CTkButton(
                frame,
                text=fav_text,
                width=28,
                height=28,
                font=btn_font,
                fg_color=fav_color,
                text_color="black" if is_fav else "white",
                command=lambda i=ip, n=display_name: self.toggle_favorite(i, n)
            )
            fav_btn.pack(side="left", padx=(0, 2))

            del_btn = ctk.CTkButton(
                frame,
                text="X",
                width=28,
                height=28,
                font=btn_font,
                fg_color="#C25A5A",
                hover_color="#914141",
                command=lambda i=ip: self.remove_from_history(i)
            )
            del_btn.pack(side="right")
            
    def toggle_armed(self, ip_port: str):
        self.history_store.set_armed_server(ip_port)
        self.refresh_history_ui()
        # Ensure the armed server also gets selected in the combo box
        if self.history_store.get_armed_server() == ip_port:
            self.select_history(ip_port)

    def toggle_favorite(self, ip_port: str, name: str):
        self.history_store.toggle_favorite(ip_port, name)
        self.refresh_history_ui()
        self.update_favorites_combobox()

    def remove_from_history(self, ip_port: str):
        self.history_store.remove_from_history(ip_port)
        self.refresh_history_ui()

    def start_inline_edit(self, frame, btn, ip, current_name):
        btn.pack_forget()
        entry = ctk.CTkEntry(frame, font=ctk.CTkFont(family="Arial", size=14))
        entry.insert(0, current_name)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        entry.focus()

        saving = False

        def save_inline(event=None):
            nonlocal saving
            if saving:
                return
            saving = True
            try:
                entry.unbind("<FocusOut>")
                entry.unbind("<Return>")
                if hasattr(entry, "_entry"):
                    entry._entry.unbind("<FocusOut>")
                    entry._entry.unbind("<Return>")
            except Exception:
                pass
            new_name = entry.get().strip()
            if new_name:
                self.history_store.update_server_name(ip, new_name)
                self.update_favorites_combobox()
                
                current_text = self.ip_entry.get()
                if current_text.endswith(f"({ip})"):
                    self.ip_entry.set(f"{new_name} ({ip})")
                    
            self.refresh_history_ui()

        entry.bind("<Return>", save_inline)
        entry.bind("<FocusOut>", save_inline)
        if hasattr(entry, "_entry"):
            entry._entry.bind("<Return>", save_inline)
            entry._entry.bind("<FocusOut>", save_inline)
        return save_inline

    def select_history(self, ip_port: str):
        self.ip_entry.set(ip_port)

    def get_target_ip(self) -> str:
        target = self.ip_entry.get().strip()
        if "(" in target and ")" in target:
            target = target.split("(")[-1].replace(")", "").strip()
        return target

    def update_entry(self, text: str):
        state = self.ip_entry.cget("state")
        self.ip_entry.configure(state="normal")
        self.ip_entry.set(text)
        self.ip_entry.configure(state=state)

    def log(self, msg: str):
        import time
        from ..core.logger import app_logger
        app_logger.info(msg)
        ts = time.strftime("[%H:%M:%S]")
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", f"{ts} {msg}\n")
        lines = int(self.log_textbox.index('end-1c').split('.')[0])
        if lines > 500:
            self.log_textbox.delete('1.0', '2.0')
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def log_safe(self, msg: str):
        self.after(0, lambda: self.log(msg))

    def create_tray_image(self):
        image = Image.new('RGB', (64, 64), color=(59, 142, 208))
        d = ImageDraw.Draw(image)
        d.text((24, 24), "R", fill=(255, 255, 255))
        return image

    def on_unmap(self, event):
        if event.widget == self and self.state() == 'iconic':
            if self.history_store.get_minimize_to_tray():
                self.withdraw_window()

    def withdraw_window(self):
        self.withdraw()
        if not self.tray_icon:
            image = self.create_tray_image()
            menu = pystray.Menu(
                pystray.MenuItem("Show", self.show_window, default=True),
                pystray.MenuItem("Quit", self.quit_window)
            )
            self.tray_icon = pystray.Icon("RustAutoConnect", image, "Rust AutoConnect", menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def show_window(self, icon=None, item=None):
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
            self.tray_icon = None
        self.after(0, self.deiconify)

    def quit_window(self, icon=None, item=None):
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
            self.tray_icon = None
        self.after(0, self.shutdown)

    def shutdown(self):
        try:
            self.destroy()
        except Exception:
            pass
