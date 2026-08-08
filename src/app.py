import socket
import threading
import time
import webbrowser
import os
import customtkinter as ctk
from typing import Optional

from .core.config import config
from .core.i18n import i18n
from .core.history_store import history_store
from .core.a2s_client import a2s_client
from .services.log_watcher import LogWatcher
from .services.process_monitor import process_monitor
from .services import steam_service
from .gui.main_window import MainWindow

class AppController(MainWindow):
    """
    Main Application Controller acting as state machine and orchestrator
    connecting GUI, history_store, a2s_client, log_watcher, and process_monitor.
    """
    def __init__(self):
        super().__init__(history_mgr=history_store, i18n_mgr=i18n)

        self.is_polling = False
        self.is_reconnecting = False
        self.poll_thread = None
        self.log_watcher: Optional[LogWatcher] = None
        self.a2s_client = a2s_client
        self.process_monitor = process_monitor

        self.log(self.t("ready"))

        # Start background status and update monitoring loops
        threading.Thread(target=self.check_rust_status_loop, daemon=True).start()
        threading.Thread(target=self.check_rust_update_loop, daemon=True).start()

    def _on_connect_btn_click(self):
        self.start_process()

    def start_process(self):
        if self.is_polling:
            self.stop_polling()
            return

        target = self.get_target_ip()
        if not target or ":" not in target:
            self.log(self.t("err_format"))
            return

        self.ip_entry.configure(state="disabled")
        self.connect_btn.configure(text=self.t("stop"), fg_color="#C25A5A", hover_color="#914141")
        self.is_polling = True
        self.is_reconnecting = False

        threading.Thread(target=self.run_logic, args=(target,), daemon=True).start()

    def stop_polling(self):
        self.is_polling = False
        if self.log_watcher:
            self.log_watcher.stop()
            self.log_watcher = None

        self.connect_btn.configure(
            text=self.t("start"), fg_color=['#3B8ED0', '#1F6AA5'], hover_color=['#36719F', '#144870']
        )
        self.ip_entry.configure(state="normal")
        self.log(self.t("poll_stop"))

    def stop_polling_safe(self):
        self.after(0, self.stop_polling)

    def run_logic(self, target: str):
        """
        BUG-01 Fix: Wrap reconnect polling logic in try...finally block
        to guarantee self.is_reconnecting = False is ALWAYS executed.
        """
        try:
            try:
                host, port_str = target.split(":", 1)
                port = int(port_str)
            except ValueError:
                self.log_safe(self.t("err_port"))
                self.stop_polling_safe()
                return

            # 1. Resolve DNS
            real_ip = host
            try:
                self.log_safe(self.t("dns_resolve", host=host))
                real_ip = socket.gethostbyname(host)
                if real_ip != host:
                    self.log_safe(self.t("dns_ok", ip=real_ip))
            except socket.gaierror:
                self.log_safe(self.t("dns_err", host=host))

            state = "WAITING_ONLINE"
            self.log_safe(self.t("ping_test", ip=real_ip, port=port))

            is_alive, name, max_players, _ = self.a2s_client.check_server_alive(real_ip, port)
            server_name = name if name else host

            target_str = f"{real_ip}:{port}"
            self.after(0, lambda: self.history_store.add_to_history(target_str, server_name))
            self.after(0, self.refresh_history_ui)

            self.log_safe(self.t("start_poll", ip=real_ip, port=port))

            if not self.is_polling:
                return

            success_count = 0
            while self.is_polling:
                is_alive, name, max_players, _ = self.a2s_client.check_server_alive(real_ip, port)
                if name:
                    server_name = name

                if state == "WAITING_ONLINE":
                    if is_alive:
                        if max_players > 0:
                            success_count += 1
                            self.log_safe(self.t("poll_ans", name=server_name))
                        else:
                            success_count = 0
                            self.log_safe(self.t("wait_ready"))
                    else:
                        success_count = 0
                        self.log_safe(self.t("poll_err", sec=config.POLL_INTERVAL))

                    if success_count >= 2:
                        self.log_safe(self.t("stable"))
                        target_str = f"{real_ip}:{port}"
                        self.after(0, lambda: self.history_store.add_to_history(target_str, server_name))
                        self.after(0, self.refresh_history_ui)

                        self.launch_game(target_str)
                        self.start_log_monitor(target_str)
                        break

                current_interval = config.POLL_INTERVAL
                for _ in range(int(current_interval * 10)):
                    if not self.is_polling:
                        break
                    time.sleep(0.1)

        finally:
            self.is_reconnecting = False

    def start_log_monitor(self, target_str: str):
        self.log_safe(self.t("log_mon"))
        if self.log_watcher:
            self.log_watcher.stop()
            self.log_watcher = None

        self.log_watcher = LogWatcher(
            on_disconnect=lambda reason: self._on_log_disconnect(target_str, reason),
            on_error=lambda err: self.log_safe(f"[!] Log watcher error: {err}")
        )
        self.log_watcher.start()

    def _on_log_disconnect(self, target_str: str, reason: str):
        if not self.is_polling:
            return
        self.log_safe(self.t("log_err"))
        time.sleep(2.0)
        if self.is_polling:
            self.start_process_force(target_str)

    def start_process_force(self, target: str):
        if self.is_reconnecting:
            return
        self.is_reconnecting = True
        threading.Thread(target=self.run_logic, args=(target,), daemon=True).start()

    def launch_game(self, target: str):
        url = f"steam://run/{config.STEAM_APP_ID}//+connect {target}"
        self.log_safe(self.t("launch", url=url))
        try:
            if os.name == 'nt':
                os.startfile(url)
            else:
                webbrowser.open(url)
            self.log_safe(self.t("launch_ok"))
        except Exception as e:
            self.log_safe(self.t("launch_err", err=e))

    def save_only(self):
        target = self.get_target_ip()
        if not target or ":" not in target:
            self.log(self.t("err_format"))
            return
        threading.Thread(target=self.run_save_logic, args=(target,), daemon=True).start()

    def run_save_logic(self, target: str):
        try:
            host, port_str = target.split(":", 1)
            port = int(port_str)
        except ValueError:
            self.log_safe(self.t("err_port"))
            return

        real_ip = host
        try:
            real_ip = socket.gethostbyname(host)
            self.after(0, lambda: self.update_entry(f"{real_ip}:{port}"))
        except socket.gaierror:
            pass

        server_name = host
        is_alive, name, max_players, _ = self.a2s_client.check_server_alive(real_ip, port)
        if is_alive and name:
            server_name = name

        target_str = f"{real_ip}:{port}"
        self.after(0, lambda: self.history_store.add_to_history(target_str, server_name))
        self.after(0, self.refresh_history_ui)
        self.log_safe(self.t("save_ip"))

    def save_favorite_dialog(self):
        target = self.get_target_ip()
        if not target:
            return

        dialog = ctk.CTkInputDialog(text="Enter a name for this favorite server:", title="Save Favorite")
        name = dialog.get_input()
        if name:
            self.history_store.toggle_favorite(target, name)
            self.update_favorites_combobox()
            self.ip_entry.set(f"{name} ({target})")
            self.log_safe(f"[*] Saved to favorites: {name}")

    def select_history(self, ip_port: str):
        if self.is_polling:
            return
        self.ip_entry.set(ip_port)

    def check_rust_status_loop(self):
        while True:
            try:
                running = self.process_monitor.is_rust_running()
                if running:
                    self.after(0, lambda: self.rust_status_label.configure(text=self.t("rust_on"), text_color="#50C878"))
                else:
                    self.after(0, lambda: self.rust_status_label.configure(text=self.t("rust_off"), text_color="#C25A5A"))
            except Exception:
                pass
            time.sleep(3.0)

    def check_rust_update_loop(self):
        while True:
            if not self.history_store.get_auto_update():
                time.sleep(60.0)
                continue

            force_wipe = steam_service.is_force_wipe_window()
            interval = 25.0 if force_wipe else 1800.0

            rust_running = self.process_monitor.is_rust_running()
            if not force_wipe and rust_running:
                time.sleep(interval)
                continue

            try:
                latest_buildid = steam_service.fetch_latest_buildid()
                local_buildid = steam_service.get_local_buildid()

                if local_buildid and latest_buildid and str(local_buildid) != str(latest_buildid):
                    self.after(0, lambda: self.update_ready_label.pack(side="left", padx=10))

                    if force_wipe and self.process_monitor.is_rust_running():
                        self.log_safe("[!] ОБНАРУЖЕН ФОРС-ВАЙП АПДЕЙТ! Закрываем игру для обновления...")
                        self.is_polling = False
                        self.process_monitor.force_kill_rust()
                    else:
                        self.log_safe("[!] Обновление найдено. Ждем скачивания...")

                    while True:
                        time.sleep(20.0)
                        try:
                            new_local = steam_service.get_local_buildid()
                            if new_local and str(new_local) == str(latest_buildid):
                                self.log_safe("[+] Обновление установлено! Запускаем Rust...")
                                self.after(0, self.update_ready_label.pack_forget)
                                webbrowser.open("steam://run/252490")
                                time.sleep(120.0)
                                break
                        except Exception:
                            pass
                else:
                    self.after(0, self.update_ready_label.pack_forget)
            except Exception:
                pass

            time.sleep(interval)

    def shutdown(self):
        """
        BUG-04 Fix: Graceful shutdown stopping log watcher and polling loops.
        """
        self.is_polling = False
        if self.log_watcher:
            self.log_watcher.stop()
            self.log_watcher = None
        super().shutdown()
