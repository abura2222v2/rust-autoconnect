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

        self._state_lock = threading.Lock()
        self._poll_stop_event = threading.Event()
        self._shutdown_event = threading.Event()
        self._is_polling = False
        self._is_reconnecting = False
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
        self.swarm_service.on_presence_update = self._on_swarm_presence
        if self.swarm_service.is_enabled:
            self.swarm_service.start()
            
        self._start_global_log_watcher()

    @property
    def is_polling(self) -> bool:
        with self._state_lock:
            return self._is_polling

    @is_polling.setter
    def is_polling(self, val: bool):
        with self._state_lock:
            self._is_polling = val

    @property
    def is_reconnecting(self) -> bool:
        with self._state_lock:
            return self._is_reconnecting

    @is_reconnecting.setter
    def is_reconnecting(self, val: bool):
        with self._state_lock:
            self._is_reconnecting = val

    def _start_global_log_watcher(self):
        def handle_disconnect(reason):
            armed = self.history_store.get_armed_server()
            # If we are already polling, the normal logic handles it. 
            # But if not polling, we trigger the armed reconnect.
            if armed and not self.is_polling and not self.is_reconnecting:
                self.log_safe(f"[⚡] Сработал авто-реконнект для вооруженного сервера: {armed}!")
                self.start_process_force(armed)
            
            # Restart the watcher after a delay so it keeps listening for future disconnects
            if not getattr(self, '_is_shutting_down', False):
                self.after(5000, self._start_global_log_watcher)

        self.global_log_watcher = LogWatcher(
            on_disconnect=handle_disconnect,
            on_error=lambda e: None,
            on_event=None,
            seek_end=True
        )
        self.global_log_watcher.start()

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
        self._poll_stop_event.clear()
        self.is_polling = True
        self.is_reconnecting = False
        
        # Reset UI log spam flags
        self._ui_logged_ans = False
        self._ui_logged_wait = False
        self._ui_logged_err = False
        
        self.swarm_service.join_room(target_str)

        threading.Thread(target=self.run_logic, args=(target_str,), daemon=True).start()

    def stop_polling(self):
        self.is_polling = False
        self._poll_stop_event.set()
        if self.log_watcher:
            self.log_watcher.stop()
            self.log_watcher = None
            
        self.swarm_service.leave_room()

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

            def check_manual_join(event):
                if not getattr(self, 'is_polling', False): return
                if "Client connected" in event or "Spawning" in event:
                    self.log_safe("[!] Обнаружено ручное подключение к серверу! Авто-коннект остановлен.")
                    self.stop_polling_safe()
                    
            from .services.log_watcher import LogWatcher
            manual_join_watcher = LogWatcher(
                on_disconnect=lambda r: None,
                on_error=lambda e: None,
                on_event=check_manual_join,
                seek_end=True
            )
            manual_join_watcher.start()

            try:
                success_count = 0
                while self.is_polling:
                    is_alive, name, max_players, _ = self.a2s_client.check_server_alive(real_ip, port)
                    if name:
                        server_name = name

                    if state == "WAITING_ONLINE":
                        if is_alive:
                            if max_players > 0:
                                success_count += 1
                                from .core.logger import app_logger
                                app_logger.info(self.t("poll_ans", name=server_name))
                                # Only log to UI once
                                if not getattr(self, '_ui_logged_ans', False):
                                    self.log_safe(self.t("poll_ans", name=server_name))
                                    self._ui_logged_ans = True
                            else:
                                success_count = 0
                                from .core.logger import app_logger
                                app_logger.info(self.t("wait_ready"))
                                if not getattr(self, '_ui_logged_wait', False):
                                    self.log_safe(self.t("wait_ready"))
                                    self._ui_logged_wait = True
                        else:
                            success_count = 0
                            from .core.logger import app_logger
                            app_logger.info(self.t("poll_err", sec=config.POLL_INTERVAL))
                            if not getattr(self, '_ui_logged_err', False):
                                self.log_safe(self.t("poll_err", sec=config.POLL_INTERVAL))
                                self._ui_logged_err = True

                        if success_count >= 2:
                            self.log_safe(self.t("stable"))
                            target_str = f"{real_ip}:{port}"
                            self.after(0, lambda: self.history_store.add_to_history(target_str, server_name))
                            self.after(0, self.refresh_history_ui)

                            self.launch_game(target_str)
                            break

                    current_interval = config.POLL_INTERVAL
                    for _ in range(int(current_interval * 10)):
                        if not self.is_polling or self._shutdown_event.is_set():
                            break
                        if self._poll_stop_event.wait(0.1):
                            break
            finally:
                manual_join_watcher.stop()

        finally:
            self.is_reconnecting = False

    def _on_run_test_click(self):
        if getattr(self, 'is_benchmarking', False):
            self.is_benchmarking = False
            self.bench_btn.configure(state="disabled", text="Stopping...")
            return
        self.run_benchmark()

    def log_safe(self, msg: str):
        self.after(0, lambda: self.log(msg))

    def _on_swarm_event(self, ip_port: str):
        if not getattr(self, 'is_polling', False):
            return
            
        target = self.get_target_ip()
        if target == ip_port:
            self.log_safe("[🚀] Swarm Connect: Другой игрок зашел на сервер! Моментальное подключение...")
            self.is_polling = False # Stop a2s polling loop
            self.launch_game(target)
            self.start_log_monitor(target)
            
    def _on_swarm_presence(self, count: int):
        if count > 0:
            self.after(0, lambda: self.log(f"[🔥] Swarm: {count} чел. ждут этот сервер вместе с вами", color="#2ECC71"))
        
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
            msg = self.t("bench_warn_running")
            if messagebox.askyesno(self.t("close_rust_title"), msg):
                self.process_monitor.force_kill_rust()
                self.log_safe("[*] Closed Rust.")
            else:
                self.log_safe("[!] Benchmark aborted.")
                self.bench_btn.configure(state="normal")
                return
        else:
            import tkinter.messagebox as messagebox
            msg = self.t("bench_warn_f5")
            if not messagebox.askokcancel(self.t("bench_instr_title"), msg):
                self.log_safe("[!] Benchmark aborted.")
                self.bench_btn.configure(state="normal")
                return
                
        if getattr(self, 'is_benchmarking', False):
            return
            
        from .core.history_store import history_store
        import tkinter.filedialog as filedialog
        
        # Determine rust path inside run_benchmark (main thread) so filedialog is safe
        rust_path = history_store.get_rust_path()
        if not rust_path or not os.path.exists(rust_path):
            self.log_safe("[*] Auto-detecting Rust installation path...")
            from .services import steam_service
            rust_path = steam_service.find_rust_install_path()
            if rust_path:
                self.log_safe(f"[+] Found Rust at: {rust_path}")
                history_store.set_rust_path(rust_path)
            else:
                self.log_safe("[!] Could not auto-detect Rust. Please select manually...")
                rust_path = filedialog.askdirectory(title="Select your Rust game folder (where RustClient.exe is)")
                if not rust_path:
                    self.log_safe("[!] Benchmark aborted. Rust path not provided.")
                    self.bench_btn.configure(state="normal", text=self.t("run_test"), fg_color="#3B8ED0")
                    return
                history_store.set_rust_path(rust_path)
                
        self.is_benchmarking = True
        self.bench_btn.configure(text=self.t("stop_bench"), fg_color="#E74C3C")
        self.bench_log.configure(state="normal")
        self.bench_log.delete("0.0", "end")
        self.bench_log.configure(state="disabled")
        
        threading.Thread(target=self.run_benchmark_logic, args=(rust_path,), daemon=True).start()

    def save_user_config(self):
        from .core.history_store import history_store
        rust_path = history_store.get_rust_path()
        if not rust_path or not os.path.exists(rust_path):
            import tkinter.messagebox as messagebox
            messagebox.showerror("Error", "Rust path not found. Please run a benchmark or connect first to discover the path.")
            return
            
        import shutil
        import time
        import tkinter.messagebox as messagebox
        
        cfg_path = os.path.join(rust_path, "cfg")
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        user_cfg_path = os.path.join(rust_path, f"cfg_user_backup_{timestamp}")
        
        if not os.path.exists(cfg_path):
            messagebox.showerror("Error", "No 'cfg' folder found in Rust directory.")
            return
            
        try:
            shutil.copytree(cfg_path, user_cfg_path)
            messagebox.showinfo("Success", f"Your personal Rust config has been saved to:\n{user_cfg_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save user config:\n{e}")

    def run_benchmark_logic(self, rust_path):
        # Stop existing watchers to release log file locks
        if getattr(self, 'log_watcher', None):
            self.log_watcher.stop()
        if getattr(self, 'global_log_watcher', None):
            self.global_log_watcher.stop()
            
        try:
            self._run_benchmark_logic_internal(rust_path)
        finally:
            if not getattr(self, '_is_shutting_down', False):
                self.after(2000, self._start_global_log_watcher)

    def _run_benchmark_logic_internal(self, rust_path):
        from .core.history_store import history_store
        from .core.config import config
        
        # Wait until Rust is fully closed
        while self.process_monitor.is_rust_running():
            time.sleep(1.0)
            
        if not os.path.exists(os.path.join(rust_path, "RustClient.exe")):
            self.log_bench("[!] Invalid Rust folder. RustClient.exe not found.")
            history_store.set_rust_path("") # reset
            self.is_benchmarking = False
            self.after(0, lambda: self.bench_btn.configure(state="normal", text=self.t("run_test"), fg_color="#3B8ED0"))
            return
            
        # Try to find BenchmarkFiles next to exe, or fallback to current dir
        base_dir = os.path.dirname(os.path.abspath(__file__))
        bm_source = os.path.abspath(os.path.join(base_dir, "..", "..", "BenchmarkFiles"))
        if not os.path.exists(bm_source):
            bm_source = os.path.abspath(os.path.join(base_dir, "..", "BenchmarkFiles"))
            if not os.path.exists(bm_source):
                # Auto-create the directory structure to prevent crashing
                self.log_bench(f"[*] BenchmarkFiles folder missing. Creating it at {bm_source}...")
                os.makedirs(os.path.join(bm_source, "cfg"), exist_ok=True)
                os.makedirs(os.path.join(bm_source, "demos"), exist_ok=True)
                
                # We don't abort anymore, we just let it copy empty folders 
                # (unless the user adds the actual demo file later)
                self.log_bench(f"[!] Please place your actual RustTweaker_bm.dem in the 'demos' folder.")
        self.log_bench("[*] Backing up your CFG and copying Benchmark files...")
        
        cfg_path = os.path.join(rust_path, "cfg")
        cfg_backup_path = os.path.join(rust_path, "cfg_backup_auto")
        
        try:
            # Backup CFG
            if os.path.exists(cfg_path):
                if os.path.exists(cfg_backup_path):
                    shutil.rmtree(cfg_backup_path, ignore_errors=True)
                shutil.copytree(cfg_path, cfg_backup_path)
                
            shutil.copytree(os.path.join(bm_source, "cfg"), cfg_path, dirs_exist_ok=True)
            
            target_demo = os.path.join(rust_path, "demos", "RustTweaker_bm.dem")
            if not os.path.exists(target_demo):
                shutil.copytree(os.path.join(bm_source, "demos"), os.path.join(rust_path, "demos"), dirs_exist_ok=True)
                
            # Append F5 bind to keys.cfg for manual start
            keys_cfg = os.path.join(cfg_path, "keys.cfg")
            with open(keys_cfg, "a") as f:
                f.write('\nbind f5 "demo.play RustTweaker_bm"\n')
        except Exception as e:
            self.log_bench(f"[!] Failed to prepare benchmark files: {e}")
            self.is_benchmarking = False
            self.after(0, lambda: self.bench_btn.configure(state="normal", text=self.t("run_test"), fg_color="#3B8ED0"))
            return
            
        self.log_bench("[*] Starting Local Benchmark: Launching Rust Demo...")
        time.sleep(1.0)
        
        start_time = time.time()
        
        # Delete old logs to ensure we read from the beginning of the new one
        from pathlib import Path
        for log_name in ["output_log.txt", "Player.log"]:
            log_path = Path(rust_path) / log_name
            attempts = 0
            while log_path.exists() and attempts < 10:
                try:
                    os.remove(log_path)
                    self.log_bench(f"[*] Cleared old game log {log_name}.")
                    break
                except Exception as e:
                    attempts += 1
                    if attempts == 1:
                        self.log_bench(f"[*] Waiting for {log_name} to be released by previous game instance...")
                    time.sleep(1.0)
            if log_path.exists():
                self.log_bench(f"[!] Critical error: Could not delete old log {log_name} after 10 seconds. Aborting benchmark. Please close Rust manually and try again.")
                self.is_benchmarking = False
                self.after(0, lambda: self.bench_btn.configure(state="normal", fg_color="#E74C3C", text="Failed"))
                return
                
        config_appdata = os.path.join(os.environ.get('USERPROFILE', ''), "AppData", "LocalLow", "Facepunch Studios LTD", "Rust", "Player.log")
        attempts = 0
        while os.path.exists(config_appdata) and attempts < 10:
            try:
                os.remove(config_appdata)
                self.log_bench("[*] Cleared old game log Player.log (AppData).")
                break
            except:
                attempts += 1
                if attempts == 1:
                    self.log_bench("[*] Waiting for Player.log (AppData) to be released by previous game instance...")
                time.sleep(1.0)
        
        if os.path.exists(config_appdata):
            self.log_bench("[!] Critical error: Could not delete Player.log (AppData) after 10 seconds. Aborting benchmark. Please close Rust manually and try again.")
            self.is_benchmarking = False
            self.after(0, lambda: self.bench_btn.configure(state="normal", fg_color="#E74C3C", text="Failed"))
            return
            
        url = f"steam://run/{config.STEAM_APP_ID}//-windowed -popupwindow"
        if os.name == 'nt':
            os.startfile(url)
        else:
            import webbrowser
            webbrowser.open(url)
            
        spawn_reached = False
        menu_reached = False
        protocol_mismatch = False
        detected_client_protocol = None
        
        time_to_menu = 0.0
        demo_start_time = 0.0
        
        def bench_event(event):
            nonlocal spawn_reached, menu_reached, protocol_mismatch, detected_client_protocol
            nonlocal time_to_menu, demo_start_time
            # Log the game output to file only, keep UI clean
            from .core.logger import app_logger
            app_logger.debug(f"[GAME] {event}")
            
            if "Spawning" in event or "LocalPlayer" in event or "Client connected" in event:
                spawn_reached = True
            elif "[Bootstrap] DONE!" in event:
                time_to_menu = time.time() - start_time
                menu_reached = True
            elif "Demo is" in event or "Index created" in event:
                if demo_start_time == 0.0:
                    demo_start_time = time.time()
                    self.log_bench(self.t("f5_pressed_log"))
            elif "Protocol mismatch" in event or "Demo protocol" in event:
                protocol_mismatch = True
                # Parse: "Demo protocol 2530 does not match client protocol 2544"
                import re
                match = re.search(r'client protocol (\d+)', event)
                if match:
                    detected_client_protocol = match.group(1)

        from .services.log_watcher import LogWatcher        
        bench_watcher = LogWatcher(
            on_disconnect=lambda reason: self.log_bench(f"Disconnected: {reason}"),
            on_error=lambda err: self.log_bench(f"Error: {err}"),
            on_event=bench_event,
            seek_end=False,
            target_log_path=None
        )
        
        try:
            bench_watcher.start()
            has_started = False
            menu_msg_shown = False
            while not spawn_reached and self.is_benchmarking:
                time.sleep(0.2)
                is_running = self.process_monitor.is_rust_running()
                
                if is_running:
                    if not has_started:
                        self.log_bench("[*] Rust game process detected. Waiting for map load...")
                        has_started = True
                        
                    if menu_reached and not menu_msg_shown:
                        self.log_bench(f"[!] GAME READY! (Menu loaded in {round(time_to_menu, 1)}s)")
                        self.log_bench(self.t("f5_prompt_log"))
                        menu_msg_shown = True
                    
                    elapsed = int(time.time() - start_time)
                    if elapsed > 0 and elapsed % 5 == 0 and elapsed != getattr(self, '_last_wait_log', 0):
                        self.log_bench(f"[*] Waiting... ({elapsed}s elapsed)")
                        self._last_wait_log = elapsed
                        
                if has_started and not is_running:
                    self.log_bench("[!] Rust process closed. Benchmark stopped.")
                    self.is_benchmarking = False
                    break
                if protocol_mismatch and detected_client_protocol:
                    self.log_bench(f"[!] Protocol mismatch detected. Patching demo to protocol {detected_client_protocol}...")
                    self.is_benchmarking = False
                    break
                if time.time() - start_time > 600:
                    self.log_bench("[!] Timeout: Demo took too long to load.")
                    self.is_benchmarking = False
                    break
        finally:
            bench_watcher.stop()
            
            if self.process_monitor.is_rust_running():
                self.log_bench("[*] Closing Rust...")
                self.process_monitor.force_kill_rust()
                while self.process_monitor.is_rust_running():
                    time.sleep(0.5)
                    
            self.log_bench("[*] Restoring original CFG backup...")
            try:
                if os.path.exists(cfg_backup_path):
                    if os.path.exists(cfg_path):
                        shutil.rmtree(cfg_path, ignore_errors=True)
                    shutil.copytree(cfg_backup_path, cfg_path, dirs_exist_ok=True)
                    shutil.rmtree(cfg_backup_path, ignore_errors=True)
            except Exception as e:
                self.log_bench(f"[!] Failed to restore CFG backup: {e}")
            
            self.is_benchmarking = False
            
            if protocol_mismatch and detected_client_protocol:
                self._auto_patch_demo(os.path.join(rust_path, "demos", "RustTweaker_bm.dem"), int(detected_client_protocol))
                self.log_bench("[*] Demo patched! Restarting benchmark...")
                # Start again
                self.after(2000, self.run_benchmark)
            elif spawn_reached and menu_reached:
                demo_load_time = time.time() - demo_start_time if demo_start_time > 0.0 else 0.0
                total_time = time_to_menu + demo_load_time
                
                # Validation: Prevent spoofing by requiring minimum realistic times
                if time_to_menu < 2.0 or demo_load_time < 2.0:
                    self.log_bench("[!] Benchmark rejected: Times are unrealistically fast. Anti-cheat triggered.")
                    self.is_benchmarking = False
                    self.after(0, lambda: self.bench_btn.configure(state="normal", fg_color="#E74C3C", text="Rejected"))
                    self.after(3000, lambda: self.bench_btn.configure(state="normal", fg_color="#3B8ED0", text=self.t("run_test"), text_color=["gray10", "#DCE4EE"]))
                    return
                    
                self.log_bench(f"[🏆] Time to Menu: {round(time_to_menu, 1)}s")
                self.log_bench(f"[🏆] Map Load Time: {round(demo_load_time, 1)}s")
                self.log_bench(f"[🏆] Total Benchmark Score: {round(total_time, 1)}s")
                
                self.log_bench("[*] Benchmark complete! Game is closed.")
                
                if total_time < 90:
                    self.after(0, lambda: self.bench_btn.configure(state="normal", fg_color="#50C878", text="Excellent"))
                elif total_time < 180:
                    self.after(0, lambda: self.bench_btn.configure(state="normal", fg_color="#FADA5E", text="Good", text_color="black"))
                else:
                    self.after(0, lambda: self.bench_btn.configure(state="normal", fg_color="#E74C3C", text="Slow"))
                
                self.after(3000, lambda: self.bench_btn.configure(state="normal", fg_color="#3B8ED0", text=self.t("run_test"), text_color=["gray10", "#DCE4EE"]))
                self.after(0, lambda: self._prompt_leaderboard(total_time))
            else:
                self.after(0, lambda: self.bench_btn.configure(state="normal", fg_color="#3B8ED0", text=self.t("run_test")))

    def _prompt_leaderboard(self, total_time: float):
        from .core.history_store import history_store
        client_id = history_store.get_client_id()
        
        hw_cpu = self.hardware_service.get_cpu_info()
        hw_disk = self.hardware_service.get_disk_info()
        hw_cpu_id = self.hardware_service.get_cpu_id()
        hw_disk_serial = self.hardware_service.get_disk_serial()
        
        self.log_bench("[*] Submitting hardware benchmark score to Global Top...")
        threading.Thread(target=self._submit_score_bg, args=(client_id, hw_cpu, hw_disk, total_time, hw_cpu_id, hw_disk_serial), daemon=True).start()

    def _auto_patch_demo(self, demo_path: str, new_protocol: int):
        # Rust demo header: 8 bytes id, 4 bytes protocol, 4 bytes save version
        try:
            with open(demo_path, "rb+") as f:
                f.seek(8) # Skip identifier
                f.write(new_protocol.to_bytes(4, byteorder='little'))
        except Exception as e:
            self.log_bench(f"[!] Failed to patch demo: {e}")

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
        import time
        from .core.logger import app_logger
        app_logger.info(f"[BENCHMARK] {msg}")
        ts = time.strftime("[%H:%M:%S]")
        self.bench_log.configure(state="normal")
        self.bench_log.insert("end", f"{ts} {msg}\n")
        self.bench_log.see("end")
        self.bench_log.configure(state="disabled")

    def _on_log_error(self, err: str):
        self.log_safe(f"[x] Log Error: {err}")

    def start_log_monitor(self, target_str: str):
        self.log_safe(self.t("log_mon"))
        if self.log_watcher:
            self.log_watcher.stop()
            self.log_watcher = None

        self.connection_start_time = time.time()
        self.is_connected = False
        
        def handle_event(event):
            from .core.logger import app_logger
            app_logger.info(f"[*] Game log: {event}")
            # Do NOT spam the UI with every game log line
            if not getattr(self, 'is_connected', False) and ("Client connected" in event or "Spawning" in event):
                self.is_connected = True
                conn_time = round(time.time() - getattr(self, 'connection_start_time', time.time()), 1)
                self.log_safe(f"[⏱️] Server Connection Time: {conn_time} seconds!")

        self.log_watcher = LogWatcher(
            on_disconnect=lambda reason: self._on_log_disconnect(target_str, reason),
            on_error=self._on_log_error,
            on_event=handle_event
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
        self.log_safe(self.t("launch", url=target))
        try:
            url = f"steam://run/{config.STEAM_APP_ID}//+connect {target}"
            if os.name == 'nt':
                os.startfile(url)
            else:
                import webbrowser
                webbrowser.open(url)
            self.log_safe(self.t("launch_ok"))
            self.start_log_monitor(target)
            
            if self.swarm_service.is_enabled:
                threading.Thread(target=self.swarm_service.broadcast_success, args=(target,), daemon=True).start()
        except Exception as e:
            self.log_safe(self.t("launch_err", err=str(e)))

    def save_only(self):
        target = self.get_target_ip()
        if not target or ":" not in target:
            self.log_safe(self.t("err_format"))
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
        self.is_rust_was_running = False
        while True:
            is_running = self.process_monitor.is_rust_running()
            if is_running:
                self.after(0, lambda: self.rust_status_label.configure(text=self.t("rust_on"), text_color="#2ECC71"))
                self.is_rust_was_running = True
            else:
                self.after(0, lambda: self.rust_status_label.configure(text=self.t("rust_off"), text_color="#E74C3C"))
                if getattr(self, 'is_rust_was_running', False):
                    self.is_rust_was_running = False
                    self.after(0, self.stop_polling)
            
            # Use event wait instead of raw sleep for graceful shutdown
            if getattr(self, '_shutdown_event', threading.Event()).wait(2.0):
                break

    def check_rust_update_loop(self):
        while True:
            if not self.history_store.get_auto_update():
                if getattr(self, '_shutdown_event', threading.Event()).wait(60.0):
                    break
                continue

            force_wipe = steam_service.is_force_wipe_window()
            interval = 25.0 if force_wipe else 1800.0

            rust_running = self.process_monitor.is_rust_running()
            if not force_wipe and rust_running:
                if getattr(self, '_shutdown_event', threading.Event()).wait(interval):
                    break
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
                        def ask_update():
                            import tkinter.messagebox as messagebox
                            msg = f"A new Rust update is available! Current: {local_buildid}, Latest: {latest_buildid}\nDo you want to run the game to apply it?"
                            if messagebox.askyesno("Rust Update", msg):
                                self.launch_game("127.0.0.1:28015")
                        self.after(0, ask_update)

                    while True:
                        if getattr(self, '_shutdown_event', threading.Event()).wait(20.0):
                            break
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

            if getattr(self, '_shutdown_event', threading.Event()).wait(interval):
                break

    def shutdown(self):
        """
        BUG-04 Fix: Graceful shutdown stopping log watcher and polling loops.
        """
        self.is_polling = False
        self._is_shutting_down = True
        self._shutdown_event.set()
        
        if self.log_watcher:
            self.log_watcher.stop()
            self.log_watcher = None
            
        if hasattr(self, 'global_log_watcher') and self.global_log_watcher:
            self.global_log_watcher.stop()
            self.global_log_watcher = None
            
        super().shutdown()
