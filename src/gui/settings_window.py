import customtkinter as ctk
from typing import Optional
from ..core.history_store import HistoryStore
from ..core.i18n import I18nManager

class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, master, history_store: HistoryStore, i18n_mgr: I18nManager, change_lang_callback):
        super().__init__(master)
        
        self.history_store = history_store
        self.i18n = i18n_mgr
        self.change_lang_callback = change_lang_callback
        
        self.title(self.i18n.t("settings_title"))
        self.geometry("450x350")
        self.resizable(False, False)
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        
        # Language Label & OptionMenu
        self.lang_label = ctk.CTkLabel(self, text=self.i18n.t("lang_lbl"), font=ctk.CTkFont(weight="bold"))
        self.lang_label.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")
        
        self.lang_menu = ctk.CTkOptionMenu(
            self,
            values=list(I18nManager.LANG_MAP.values()),
            command=self._on_lang_change,
            width=150
        )
        self.lang_menu.grid(row=0, column=1, padx=20, pady=(20, 10), sticky="e")
        self.lang_menu.set(self.history_store.get_lang())
        
        # Minimize to Tray Checkbox
        self.tray_var = ctk.BooleanVar(value=self.history_store.get_minimize_to_tray())
        self.tray_checkbox = ctk.CTkCheckBox(
            self, text=self.i18n.t("tray_lbl"), 
            variable=self.tray_var, 
            command=self._on_tray_change
        )
        self.tray_checkbox.grid(row=1, column=0, columnspan=2, padx=20, pady=(20, 10), sticky="w")
        
        # Swarm Connect Checkbox
        self.swarm_var = ctk.BooleanVar(value=self.history_store.get_swarm_enabled())
        self.swarm_checkbox = ctk.CTkCheckBox(
            self, text=self.i18n.t("swarm_lbl"), 
            variable=self.swarm_var, 
            command=self._on_swarm_change
        )
        self.swarm_checkbox.grid(row=2, column=0, columnspan=2, padx=20, pady=(10, 10), sticky="w")
        
        # Benchmark Safety Checkbox
        self.bench_copy_var = ctk.BooleanVar(value=self.history_store.get_allow_benchmark_copy())
        self.bench_copy_checkbox = ctk.CTkCheckBox(
            self, text=self.i18n.t("bench_copy_lbl"), 
            variable=self.bench_copy_var, 
            command=self._on_bench_copy_change,
            fg_color="#C25A5A",
            text_color="#C25A5A"
        )
        self.bench_copy_checkbox.grid(row=3, column=0, columnspan=2, padx=20, pady=(10, 10), sticky="w")
        
        # Close Button
        self.close_btn = ctk.CTkButton(self, text=self.i18n.t("close_btn"), command=self.destroy, width=100)
        self.close_btn.grid(row=4, column=0, columnspan=2, pady=30)
        
        # Update title based on language
        self.title(self.i18n.t("title") + " - " + self.i18n.t("settings_title"))
        
        self.grab_set() # Make it modal
        
    def _on_lang_change(self, choice: str):
        self.change_lang_callback(choice)
        self.title(self.i18n.t("title") + " - " + self.i18n.t("settings_title"))
        
    def _on_tray_change(self):
        self.history_store.set_minimize_to_tray(self.tray_var.get())

    def _on_swarm_change(self):
        self.history_store.set_swarm_enabled(self.swarm_var.get())
        # Apply to swarm service instantly
        from .services.swarm_service import swarm_service
        swarm_service.is_enabled = self.swarm_var.get()
        if swarm_service.is_enabled:
            swarm_service.start()
        else:
            swarm_service.stop()
            
    def _on_bench_copy_change(self):
        self.history_store.set_allow_benchmark_copy(self.bench_copy_var.get())
