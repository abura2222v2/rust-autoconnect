import socket
import threading
import time
import webbrowser
import os
import re
import shutil
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

        from .services.hardware_service import hardware_service
        self.hardware_service = hardware_service
        
        self.log_safe(self.t("ready"))
        
        # Start background status and update monitoring loops
        threading.Thread(target=self.check_rust_status_loop, daemon=True).start()
        threading.Thread(target=self.check_rust_update_loop, daemon=True).start()
        threading.Thread(target=self._load_hardware, daemon=True).start()
        
        # Init Swarm Service
        from .services.swarm_service import swarm_service
        self.swarm_service = swarm_service
        self.swarm_service.is_enabled = self.history_store.get_swarm_enabled()
        self.swarm_service.on_swarm_event = self._on_swarm_event
        if self.swarm_service.is_enabled:
            self.swarm_service.start()

    def _on_connect_btn_click(self):
        self.start_process(self.get_target_ip())

    def start_process(self, target_str: str):
        if self.is_polling:
            self.stop_polling()
            return

        if not re.match(r'^[a-zA-Z0-9.-]+:\d+$', target_str):
            self.log_safe("[!] Security Error: Invalid address format. Must be IP:PORT.")
            self.stop_polling()
            return

        self.ip_entry.configure(state="disabled")
        self.connect_btn.configure(text=self.t("stop"), fg_color="#C25A5A", hover_color="#914141")
        self.is_polling = True
        self.is_reconnecting = False

        threading.Thread(target=self.run_logic, args=(target_str,), daemon=True).start()

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

    def _on_run_test_click(self):
        self.run_benchmark()

    def log_safe(self, msg: str):
        self.after(0, lambda: self.log(msg))

    def _on_swarm_event(self, ip_port: str):
        if not self.is_polling:
            return
            
        target = self.get_target_ip()
        if target == ip_port:
            self.log_safe("[🚀] Swarm Connect: Another player joined the server! Instant connect...")
            self.is_polling = False # Stop a2s polling loop
            self.start_process_force(target)
        
    def _load_hardware(self):
        hw_cpu = self.hardware_service.get_cpu_info()
        hw_ram = self.hardware_service.get_ram_info()
        hw_disk = self.hardware_service.get_disk_info()
        self.after(0, lambda: self.hardware_label.configure(text=f"CPU: {hw_cpu}\nRAM: {hw_ram}\nDisk: {hw_disk}"))

    def run_benchmark(self):
        if not hasattr(self, 'bench_btn'):
            return
            
        if self.process_monitor.is_rust_running():
            import tkinter.messagebox as messagebox
            if messagebox.askyesno("Close Rust?", "Rust is running. We must close it before copying benchmark files. Close it now?"):
                self.process_monitor.force_kill_rust()
                self.log_bench("[*] Closed Rust.")
            else:
                self.log_bench("[!] Benchmark aborted.")
                self.after(0, lambda: self.bench_btn.configure(state="normal"))
                return
        self.bench_btn.configure(state="disabled")
        self.bench_log.configure(state="normal")
        self.bench_log.delete("0.0", "end")
        self.bench_log.configure(state="disabled")
        threading.Thread(target=self.run_benchmark_logic, daemon=True).start()

    def run_benchmark_logic(self):
        from .core.history_store import history_store
        
        # Wait until Rust is fully closed
        while self.process_monitor.is_rust_running():
            time.sleep(1.0)
            
        rust_path = history_store.get_rust_path()
        if not rust_path or not os.path.exists(rust_path):
            self.log_bench("[*] Please select your Rust game folder...")
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            rust_path = filedialog.askdirectory(title="Select your Rust game folder (where RustClient.exe is)")
            if not rust_path:
                self.log_bench("[!] Benchmark aborted. Rust path not provided.")
                self.after(0, lambda: self.bench_btn.configure(state="normal"))
                return
            history_store.set_rust_path(rust_path)
            
        if not os.path.exists(os.path.join(rust_path, "RustClient.exe")):
            self.log_bench("[!] Invalid Rust folder. RustClient.exe not found.")
            history_store.set_rust_path("") # reset
            self.after(0, lambda: self.bench_btn.configure(state="normal"))
            return
            
        # Try to find BenchmarkFiles next to exe, or fallback to current dir
        base_dir = os.path.dirname(os.path.abspath(__file__))
        bm_source = os.path.abspath(os.path.join(base_dir, "..", "..", "BenchmarkFiles"))
        if not os.path.exists(bm_source):
            bm_source = os.path.abspath(os.path.join(base_dir, "..", "BenchmarkFiles"))
            if not os.path.exists(bm_source):
                self.log_bench(f"[!] Benchmark files not found in {bm_source}. Please place 'BenchmarkFiles' folder next to the executable.")
                self.after(0, lambda: self.bench_btn.configure(state="normal"))
                return
            
        self.log_bench("[*] Backing up your CFG and copying Benchmark files...")
        
        cfg_path = os.path.join(rust_path, "cfg")
        cfg_backup_path = os.path.join(rust_path, "cfg_backup_auto")
        
        try:
            # Backup
            if os.path.exists(cfg_path):
                if os.path.exists(cfg_backup_path):
                    shutil.rmtree(cfg_backup_path)
                shutil.copytree(cfg_path, cfg_backup_path)
                
            shutil.copytree(os.path.join(bm_source, "cfg"), cfg_path, dirs_exist_ok=True)
            shutil.copytree(os.path.join(bm_source, "demos"), os.path.join(rust_path, "demos"), dirs_exist_ok=True)
        except Exception as e:
            self.log_bench(f"[!] Failed to prepare benchmark files: {e}")
            self.after(0, lambda: self.bench_btn.configure(state="normal"))
            return
            
        self.after(0, lambda: self.bench_btn.configure(fg_color="orange", text="Running..."))
        self.log_bench("[*] Starting Local Benchmark: Launching Rust Demo...")
        time.sleep(1.0)
        
        start_time = time.time()
        url = f"steam://run/{config.STEAM_APP_ID}//-windowed -popupwindow +demo.play RustTweaker_bm"
        import webbrowser
        if os.name == 'nt':
            os.startfile(url)
        else:
            webbrowser.open(url)
            
        spawn_reached = False
        def bench_event(event):
            nonlocal spawn_reached
            if "Spawning" in event or "LocalPlayer" in event or "Client connected" in event:
                spawn_reached = True

        from .services.log_watcher import LogWatcher
        bench_watcher = LogWatcher(
            on_disconnect=lambda r: None, 
            on_error=lambda e: None,
            on_event=bench_event
        )
        
        try:
            bench_watcher.start()
            while not spawn_reached:
                time.sleep(1.0)
                if time.time() - start_time > 600:
                    self.log_bench("[!] Timeout: Demo took too long to load.")
                    return
        finally:
            bench_watcher.stop()
            self.after(0, lambda: self.bench_btn.configure(fg_color="#3B8ED0", text=self.t("run_test")))
            self.log_bench("[*] Restoring original CFG backup...")
            try:
                if os.path.exists(cfg_backup_path):
                    shutil.rmtree(cfg_path, ignore_errors=True)
                    os.rename(cfg_backup_path, cfg_path)
            except Exception as e:
                self.log_bench(f"[!] Failed to restore CFG backup: {e}")
            
        total_time = time.time() - start_time
        self.log_bench(f"[🏆] Total Benchmark Time: {round(total_time, 1)} seconds.")
        
        if total_time < 90:
            self.after(0, lambda: self.bench_btn.configure(fg_color="#50C878", text="Excellent"))
        elif total_time < 180:
            self.after(0, lambda: self.bench_btn.configure(fg_color="#FADA5E", text="Good", text_color="black"))
        else:
            self.after(0, lambda: self.bench_btn.configure(fg_color="#C25A5A", text="Slow"))
            
        self.after(0, lambda: self._prompt_leaderboard(total_time))
        
    def _prompt_leaderboard(self, total_time: float):
        import customtkinter as ctk
        dialog = ctk.CTkInputDialog(text=f"Your time: {round(total_time, 1)}s!\nEnter nickname for Global Leaderboard:", title="Submit Score")
        ans = dialog.get_input()
        if ans:
            from .services.leaderboard_service import leaderboard_service
            hw_cpu = self.hardware_service.get_cpu_info()
            hw_disk = self.hardware_service.get_disk_info()
            hw_cpu_id = self.hardware_service.get_cpu_id()
            hw_disk_serial = self.hardware_service.get_disk_serial()
            # Run blocking HTTP request in background to prevent UI freeze (Architect review fix)
            threading.Thread(target=self._submit_score_bg, args=(ans, hw_cpu, hw_disk, total_time, hw_cpu_id, hw_disk_serial), daemon=True).start()

    def _submit_score_bg(self, ans, hw_cpu, hw_disk, total_time, cpu_id, disk_serial):
        from .services.leaderboard_service import leaderboard_service
        success = leaderboard_service.submit_score(ans, hw_cpu, hw_disk, total_time, cpu_id, disk_serial)
        if success:
            self.log_bench("[+] Score successfully submitted to Leaderboard!")
        else:
            self.log_bench("[!] Failed to submit score.")

    def log_bench(self, msg: str):
        self.after(0, lambda: self._log_bench_ui(msg))
        
    def _log_bench_ui(self, msg: str):
        if not hasattr(self, 'bench_log'):
            return
        self.bench_log.configure(state="normal")
        self.bench_log.insert("end", msg + "\n")
        self.bench_log.see("end")
        self.bench_log.configure(state="disabled")

    def _on_log_error(self, err: str):
        self.log_safe(f"[x] Log Error: {err}")

    def start_log_monitor(self, target_str: str):
        self.log_safe(self.t("log_mon"))
        if self.log_watcher:
            self.log_watcher.stop()
            self.log_watcher = None

        self.log_watcher = LogWatcher(
            on_disconnect=lambda reason: self._on_log_disconnect(target_str, reason),
            on_error=self._on_log_error,
            on_event=lambda event: self.log_safe(f"[*] Game log: {event}")
        )
        self.log_watcher.start()

    def _on_log_disconnect(self, target_str: str, reason: str):
        if not self.is_polling:
            return
            
        self.log_safe(self.t("log_err") + f" Reason: {reason}")
        
        current_watcher = self.log_watcher
        time.sleep(2.0)
        
        if not self.is_polling or self.log_watcher is not current_watcher:
            return
            
        self.start_process_force(target_str)

    def start_process_force(self, target: str):
        if self.is_reconnecting:
            return
        self.is_reconnecting = True
        threading.Thread(target=self.run_logic, args=(target,), daemon=True).start()

    def launch_game(self, target: str):
        self.log(self.t("launch", url=target))
        try:
            url = f"steam://run/{config.STEAM_APP_ID}//+connect {target}"
            if os.name == 'nt':
                os.startfile(url)
            else:
                import webbrowser
                webbrowser.open(url)
            self.log(self.t("launch_ok"))
            self.start_log_monitor(target)
            
            if self.swarm_service.is_enabled:
                threading.Thread(target=self.swarm_service.broadcast_success, args=(target,), daemon=True).start()
        except Exception as e:
            self.log(self.t("launch_err", err=str(e)))

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
                        self.log_safe("[!] FORCE-WIPE UPDATE DETECTED! Closing game for update...")
                        self.is_polling = False
                        self.process_monitor.force_kill_rust()
                    else:
                        self.log_safe("[!] Update found. Waiting for download...")

                    while True:
                        time.sleep(20.0)
                        try:
                            new_local = steam_service.get_local_buildid()
                            if new_local and str(new_local) == str(latest_buildid):
                                self.log_safe("[+] Update installed! Starting Rust...")
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
