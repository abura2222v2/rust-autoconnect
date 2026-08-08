import customtkinter as ctk
import threading
import time
import os
from PIL import Image, ImageDraw
import pystray
from typing import Optional, Callable

from ..core.i18n import i18n, I18nManager
from ..core.history_store import history_store, HistoryStore

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class MainWindow(ctk.CTk):
    """
    CustomTkinter Main Window UI logic extracted from monolithic main.py.
    Provides left history panel, right connection/log panel, and system tray integration.
    """
    def __init__(self, history_mgr: Optional[HistoryStore] = None, i18n_mgr: Optional[I18nManager] = None):
        super().__init__()
        
        self.history_store = history_mgr if history_mgr is not None else history_store
        self.i18n = i18n_mgr if i18n_mgr is not None else i18n

        self.lang = self.history_store.get_lang()
        self.i18n.set_lang(self.lang)

        self.title(self.t("title"))
        self.geometry("800x480")
        self.minsize(700, 400)

        self._search_timer = None # UI Stutter Fix: Debounce handle for search bar
        self.is_auto_update_enabled = self.history_store.get_auto_update()
        self.auto_update = ctk.BooleanVar(value=self.is_auto_update_enabled)

        self.tray_icon = None
        self.protocol('WM_DELETE_WINDOW', self.withdraw_window)

        # Grid layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Left Panel (History)
        self.left_panel = ctk.CTkFrame(self, width=240, corner_radius=0)
        self.left_panel.grid(row=0, column=0, sticky="nsew")
        self.left_panel.grid_rowconfigure(3, weight=1)

        self.history_label = ctk.CTkLabel(
            self.left_panel, text=self.t("history"), font=ctk.CTkFont(size=16, weight="bold")
        )
        self.history_label.grid(row=0, column=0, padx=20, pady=(20, 5))

        self.filter_var = ctk.StringVar(value="All Servers")
        self.filter_menu = ctk.CTkOptionMenu(
            self.left_panel,
            values=["All Servers", "Favorites"],
            variable=self.filter_var,
            command=lambda e: self.refresh_history_ui()
        )
        self.filter_menu.grid(row=1, column=0, padx=20, pady=(0, 10), sticky="ew")

        # Smart Search with UI Stutter Fix (Debounced via after())
        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", self._on_search_changed)
        self.search_entry = ctk.CTkEntry(self.left_panel, placeholder_text="Поиск...", textvariable=self.search_var)
        self.search_entry.grid(row=2, column=0, padx=20, pady=(0, 10), sticky="ew")

        self.history_scroll = ctk.CTkScrollableFrame(self.left_panel)
        self.history_scroll.grid(row=3, column=0, sticky="nsew", padx=10, pady=0)

        # Bottom Frame of Left Panel (Language + Status)
        self.left_bottom_frame = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        self.left_bottom_frame.grid(row=4, column=0, sticky="ew", padx=10, pady=10)
        self.left_bottom_frame.grid_columnconfigure(1, weight=1)

        # Language Selector
        self.lang_menu = ctk.CTkOptionMenu(
            self.left_bottom_frame,
            values=list(I18nManager.LANG_MAP.values()),
            command=self.change_lang,
            width=80
        )
        self.lang_menu.grid(row=0, column=0, sticky="w")
        self.lang_menu.set(self.lang)

        # Rust Running Status Label
        self.rust_status_label = ctk.CTkLabel(
            self.left_bottom_frame, text=self.t("rust_off"), font=ctk.CTkFont(weight="bold"), text_color="#C25A5A"
        )
        self.rust_status_label.grid(row=0, column=1, sticky="e")

        # Right Panel
        self.right_panel = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.right_panel.grid(row=0, column=1, sticky="nsew")
        self.right_panel.grid_columnconfigure(0, weight=1)
        self.right_panel.grid_rowconfigure(1, weight=1)

        # Input Frame
        self.input_frame = ctk.CTkFrame(self.right_panel)
        self.input_frame.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="ew")
        self.input_frame.grid_columnconfigure(0, weight=1)

        self.ip_entry = ctk.CTkComboBox(
            self.input_frame,
            values=[f"{f.get('name', 'Unknown')} ({f.get('ip', 'Unknown')})" for f in self.history_store.get_favorites()]
        )
        self.ip_entry.set("")
        self.ip_entry.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        # Start button
        self.connect_btn = ctk.CTkButton(
            self.input_frame, text=self.t("start"), command=self._on_connect_btn_click, width=120
        )
        self.connect_btn.grid(row=0, column=1, padx=10, pady=10)

        # Bottom frame for Auto-Update
        self.bottom_frame = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        self.bottom_frame.grid(row=3, column=0, sticky="e", padx=20, pady=(0, 10))

        self.update_ready_label = ctk.CTkLabel(
            self.bottom_frame, text="Update Ready!", text_color="#50C878", font=ctk.CTkFont(weight="bold")
        )
        self.update_ready_label.pack(side="left", padx=10)
        self.update_ready_label.pack_forget()

        self.update_check = ctk.CTkCheckBox(
            self.bottom_frame, text="Auto-Update Rust", variable=self.auto_update, command=self.on_auto_update_change
        )
        self.update_check.pack(side="right", padx=10)

        # Log Frame
        self.log_frame = ctk.CTkFrame(self.right_panel)
        self.log_frame.grid(row=1, column=0, rowspan=2, padx=20, pady=(0, 10), sticky="nsew")
        self.log_frame.grid_columnconfigure(0, weight=1)
        self.log_frame.grid_rowconfigure(0, weight=1)

        self.log_textbox = ctk.CTkTextbox(self.log_frame, state="disabled", font=ctk.CTkFont(family="Consolas", size=13))
        self.log_textbox.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        self.refresh_history_ui()

    def t(self, key: str, **kwargs) -> str:
        """Localization helper."""
        return self.i18n.t(key, **kwargs)

    def _on_search_changed(self, *args):
        """UI Stutter Fix: Debounce search bar input by 300ms using after()."""
        if self._search_timer is not None:
            self.after_cancel(self._search_timer)
        self._search_timer = self.after(300, self.refresh_history_ui)

    def on_auto_update_change(self):
        self.is_auto_update_enabled = self.auto_update.get()
        self.history_store.set_auto_update(self.is_auto_update_enabled)

    def _on_connect_btn_click(self):
        # Override in AppController
        pass

    def change_lang(self, choice: str):
        code = choice.split(" ")[0]
        self.lang = code
        self.i18n.set_lang(code)
        self.history_store.set_lang(code)

        self.title(self.t("title"))
        self.history_label.configure(text=self.t("history"))

        if "🟢" in self.rust_status_label.cget("text"):
            self.rust_status_label.configure(text=self.t("rust_on"))
        else:
            self.rust_status_label.configure(text=self.t("rust_off"))

        self.lang_menu.set(code)
        self.refresh_history_ui()

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
                fg_color="#2b2b2b",
                hover_color="#3b3b3b",
                text_color=("gray80", "white"),
                command=lambda i=ip: self.select_history(i)
            )
            btn.pack(side="left", fill="x", expand=True, padx=(0, 5))

            # Double click to edit name
            btn.bind("<Double-Button-1>", lambda event, f=frame, b=btn, i=ip, n=display_name: self.start_inline_edit(f, b, i, n))

            btn_font = ctk.CTkFont(family="Arial", size=14)

            fav_text = "⭐" if is_fav else "☆"
            fav_color = "#3B8ED0" if is_fav else "#555555"
            fav_btn = ctk.CTkButton(
                frame,
                text=fav_text,
                width=28,
                height=28,
                font=btn_font,
                fg_color=fav_color,
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

    def toggle_favorite(self, ip_port: str, name: str):
        self.history_store.toggle_favorite(ip_port, name)
        self.refresh_history_ui()
        self.update_favorites_combobox()

    def remove_from_history(self, ip_port: str):
        self.history_store.remove_from_history(ip_port)
        self.refresh_history_ui()

    def start_inline_edit(self, frame, btn, ip, current_name):
        """
        BUG-09 Fix: Unbind <FocusOut> and <Return> handlers before saving
        and use a guard flag to prevent double invocation Tcl errors during UI refresh.
        """
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
            self.refresh_history_ui()

        entry.bind("<Return>", save_inline)
        entry.bind("<FocusOut>", save_inline)
        if hasattr(entry, "_entry"):
            entry._entry.bind("<Return>", save_inline)
            entry._entry.bind("<FocusOut>", save_inline)
        return save_inline

    def select_history(self, ip_port: str):
        # Override check in AppController
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
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", msg + "\n")
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def log_safe(self, msg: str):
        self.after(0, lambda: self.log(msg))

    def create_tray_image(self):
        image = Image.new('RGB', (64, 64), color=(59, 142, 208))
        d = ImageDraw.Draw(image)
        d.text((24, 24), "R", fill=(255, 255, 255))
        return image

    def withdraw_window(self):
        self.withdraw()
        if not self.tray_icon:
            image = self.create_tray_image()
            menu = pystray.Menu(
                pystray.MenuItem("Показать / Show", self.show_window, default=True),
                pystray.MenuItem("Выход / Quit", self.quit_window)
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
        """
        BUG-04 Fix: Replace abrupt os._exit(0) with graceful shutdown on main Tkinter thread.
        """
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
            self.tray_icon = None
        self.after(0, self.shutdown)

    def shutdown(self):
        """Gracefully destroy main window."""
        try:
            self.destroy()
        except Exception:
            pass
