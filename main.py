import customtkinter as ctk
import a2s
import threading
import time
import json
import os
import webbrowser
import socket
import subprocess
import glob
import winreg
import urllib.request
import re
from datetime import datetime, timedelta, timezone
import psutil
import pystray
from PIL import Image, ImageDraw
# --- Translations ---
LANGUAGES = {
    "RU": {
        "title": "Rust AutoConnect",
        "history": "История серверов",
        "placeholder": "IP:PORT или Домен:PORT",
        "start": "Запуск",
        "stop": "Остановить",
        "ready": "[i] Готово. Введите адрес и нажмите Запуск.",
        "err_format": "[!] Ошибка: Введите корректный адрес (IP:PORT или Домен:PORT).",
        "err_port": "[!] Ошибка: Порт должен быть числом.",
        "dns_resolve": "[*] Резолвинг домена {host}...",
        "dns_ok": "[✓] Домен разрешен в IP: {ip}",
        "dns_err": "[x] Ошибка DNS: Не удалось найти IP для {host}",
        "ping_test": "[-] Умный поиск порта для {ip}:{port}...",
        "server_found": "[✓] Сервер найден! Имя: {name}",
        "server_alive": "[✓] Сервер ответил (нестандартный пакет, но жив!).",
        "server_timeout": "[x] Сервер пока не отвечает (возможно, оффлайн).",
        "start_poll": "\n[*] Начинаем мониторинг сервера: {ip}:{port}",
        "poll_stop": "[*] Мониторинг остановлен.",
        "poll_ping": "[-] Опрос {ip}:{port}...",
        "poll_ans": "[+] Ответил: {name}",
        "poll_err": "[x] Нет ответа. Повтор через {sec} сек...",
        "stable": "[✓] Сервер стабилен. Инициируем подключение...",
        "launch": "[>] Выполняется команда: {url}",
        "launch_ok": "[✓] Успешно отправлено в Steam!",
        "launch_err": "[!] Ошибка запуска Steam: {err}",
        "del": "Удалить",
        "rust_on": "Rust: Запущен 🟢",
        "rust_off": "Rust: Закрыт 🔴",
        "save_ip": "[*] Сервер добавлен в историю.",
        "wait_wipe": "Ждать вайпа/рестарта",
        "log_mon": "[*] Читаю логи Rust. При дисконнекте зайду снова мгновенно!",
        "log_err": "[!] В логе замечен Disconnect! Переподключаюсь...",
        "wait_mode": "[*] Режим ожидания. Сервер ОНЛАЙН. Ждем, пока он выключится...",
        "wait_down": "[*] Сервер выключился! Ждем запуска и слотов...",
        "wait_ready": "[+] Сервер запущен, но слоты 0/0. Ждем прогрузки карты..."
    },
    "EN": {
        "title": "Rust AutoConnect",
        "history": "Server History",
        "placeholder": "IP:PORT or Domain:PORT",
        "start": "Start",
        "stop": "Stop",
        "ready": "[i] Ready. Enter server address and click Start.",
        "err_format": "[!] Error: Enter a valid address (IP:PORT or Domain:PORT).",
        "err_port": "[!] Error: Port must be a number.",
        "dns_resolve": "[*] Resolving domain {host}...",
        "dns_ok": "[✓] Domain resolved to IP: {ip}",
        "dns_err": "[x] DNS Error: Could not find IP for {host}",
        "ping_test": "[-] Smart port search for {ip}:{port}...",
        "server_found": "[✓] Server found! Name: {name}",
        "server_alive": "[✓] Server responded (non-standard packet, but alive!).",
        "server_timeout": "[x] Server not responding yet (maybe offline).",
        "start_poll": "\n[*] Starting server monitor: {ip}:{port}",
        "poll_stop": "[*] Monitoring stopped.",
        "poll_ping": "[-] Polling {ip}:{port}...",
        "poll_ans": "[+] Responded: {name}",
        "poll_err": "[x] No response. Retrying in {sec} sec...",
        "stable": "[✓] Server stable. Initiating connection...",
        "launch": "[>] Executing command: {url}",
        "launch_ok": "[✓] Successfully sent to Steam!",
        "launch_err": "[!] Steam launch error: {err}",
        "del": "Del",
        "rust_on": "Rust: Running 🟢",
        "rust_off": "Rust: Closed 🔴",
        "save_ip": "[*] Server added to history.",
        "wait_wipe": "Wait for wipe/restart",
        "log_mon": "[*] Reading Rust logs. Will instantly reconnect on disconnect!",
        "log_err": "[!] Disconnect detected in log! Reconnecting...",
        "wait_mode": "[*] Wait mode. Server is ONLINE. Waiting for it to go offline...",
        "wait_down": "[*] Server went offline! Waiting for startup and slots...",
        "wait_ready": "[+] Server is up, but slots are 0/0. Waiting for map to load..."
    },
    "ES": {
        "title": "Rust AutoConnect",
        "history": "Historial",
        "placeholder": "IP:PORT o Dominio:PORT",
        "start": "Iniciar",
        "stop": "Detener",
        "ready": "[i] Listo. Ingrese dirección y haga clic en Iniciar.",
        "err_format": "[!] Error: Dirección inválida.",
        "err_port": "[!] Error: El puerto debe ser un número.",
        "dns_resolve": "[*] Resolviendo {host}...",
        "dns_ok": "[✓] IP resuelta: {ip}",
        "dns_err": "[x] Error DNS: No se encontró IP.",
        "ping_test": "[-] Búsqueda inteligente de puerto {ip}:{port}...",
        "server_found": "[✓] Servidor: {name}",
        "server_alive": "[✓] El servidor respondió (vivo).",
        "server_timeout": "[x] Sin respuesta (quizás apagado).",
        "start_poll": "\n[*] Monitoreando: {ip}:{port}",
        "poll_stop": "[*] Monitoreo detenido.",
        "poll_ping": "[-] Consultando {ip}:{port}...",
        "poll_ans": "[+] Respuesta: {name}",
        "poll_err": "[x] Sin respuesta. Reintento en {sec}s...",
        "stable": "[✓] Servidor estable. Conectando...",
        "launch": "[>] Ejecutando: {url}",
        "launch_ok": "[✓] ¡Enviado a Steam!",
        "launch_err": "[!] Error Steam: {err}",
        "del": "X",
        "rust_on": "Rust: Abierto 🟢",
        "rust_off": "Rust: Cerrado 🔴",
        "save_ip": "[*] Servidor añadido al historial.",
        "wait_wipe": "Esperar wipe/reinicio",
        "log_mon": "[*] Leyendo logs de Rust. ¡Reconectará al instante si te desconectas!",
        "log_err": "[!] ¡Desconexión detectada! Reconectando...",
        "wait_mode": "[*] Modo de espera. El servidor está EN LÍNEA. Esperando a que se apague...",
        "wait_down": "[*] ¡El servidor se apagó! Esperando inicio y slots...",
        "wait_ready": "[+] Servidor encendido, pero slots 0/0. Esperando mapa..."
    },
    "FR": {
        "title": "Rust AutoConnect",
        "history": "Historique",
        "placeholder": "IP:PORT ou Domaine:PORT",
        "start": "Démarrer",
        "stop": "Arrêter",
        "ready": "[i] Prêt. Entrez l'adresse et cliquez sur Démarrer.",
        "err_format": "[!] Erreur: Adresse invalide.",
        "err_port": "[!] Erreur: Le port doit être un nombre.",
        "dns_resolve": "[*] Résolution de {host}...",
        "dns_ok": "[✓] IP résolue: {ip}",
        "dns_err": "[x] Erreur DNS.",
        "ping_test": "[-] Recherche intelligente de port {ip}:{port}...",
        "server_found": "[✓] Serveur: {name}",
        "server_alive": "[✓] Le serveur a répondu.",
        "server_timeout": "[x] Pas de réponse (hors ligne ?).",
        "start_poll": "\n[*] Surveillance: {ip}:{port}",
        "poll_stop": "[*] Surveillance arrêtée.",
        "poll_ping": "[-] Sondage {ip}:{port}...",
        "poll_ans": "[+] Réponse: {name}",
        "poll_err": "[x] Pas de réponse. Réessai dans {sec}s...",
        "stable": "[✓] Serveur stable. Connexion...",
        "launch": "[>] Exécution: {url}",
        "launch_ok": "[✓] Envoyé à Steam !",
        "launch_err": "[!] Erreur Steam: {err}",
        "del": "X",
        "rust_on": "Rust: Ouvert 🟢",
        "rust_off": "Rust: Fermé 🔴",
        "save_ip": "[*] Serveur ajouté à l'historique.",
        "wait_wipe": "Attendre wipe/redémarrage",
        "log_mon": "[*] Lecture des logs Rust. Reconnexion instantanée en cas de déconnexion !",
        "log_err": "[!] Déconnexion détectée ! Reconnexion...",
        "wait_mode": "[*] Mode attente. Serveur EN LIGNE. En attente de son arrêt...",
        "wait_down": "[*] Le serveur s'est arrêté ! En attente du démarrage et des slots...",
        "wait_ready": "[+] Serveur en ligne, mais slots 0/0. En attente de la carte..."
    },
    "DE": {
        "title": "Rust AutoConnect",
        "history": "Verlauf",
        "placeholder": "IP:PORT oder Domain:PORT",
        "start": "Starten",
        "stop": "Stoppen",
        "ready": "[i] Bereit. Adresse eingeben und Starten klicken.",
        "err_format": "[!] Fehler: Ungültige Adresse.",
        "err_port": "[!] Fehler: Port muss eine Zahl sein.",
        "dns_resolve": "[*] Auflösen von {host}...",
        "dns_ok": "[✓] IP gefunden: {ip}",
        "dns_err": "[x] DNS Fehler.",
        "ping_test": "[-] Intelligente Portsuche für {ip}:{port}...",
        "server_found": "[✓] Server: {name}",
        "server_alive": "[✓] Server antwortet (am Leben).",
        "server_timeout": "[x] Keine Antwort (vielleicht offline).",
        "start_poll": "\n[*] Überwachung: {ip}:{port}",
        "poll_stop": "[*] Überwachung gestoppt.",
        "poll_ping": "[-] Abfrage {ip}:{port}...",
        "poll_ans": "[+] Antwort: {name}",
        "poll_err": "[x] Keine Antwort. Neustart in {sec}s...",
        "stable": "[✓] Server stabil. Verbinde...",
        "launch": "[>] Führe aus: {url}",
        "launch_ok": "[✓] An Steam gesendet!",
        "launch_err": "[!] Steam Fehler: {err}",
        "del": "X",
        "rust_on": "Rust: Offen 🟢",
        "rust_off": "Rust: Geschlossen 🔴",
        "save_ip": "[*] Server zum Verlauf hinzugefügt.",
        "wait_wipe": "Auf Wipe/Neustart warten",
        "log_mon": "[*] Lese Rust-Logs. Bei Verbindungsabbruch sofortige Neuverbindung!",
        "log_err": "[!] Verbindungsabbruch erkannt! Verbinde neu...",
        "wait_mode": "[*] Wartemodus. Server ist ONLINE. Warte darauf, dass er offline geht...",
        "wait_down": "[*] Server ist offline gegangen! Warte auf Start und Slots...",
        "wait_ready": "[+] Server läuft, aber Slots 0/0. Warte auf Karte..."
    },
    "ZH": {
        "title": "Rust 自动连接",
        "history": "服务器历史",
        "placeholder": "IP:端口 或 域名:端口",
        "start": "启动",
        "stop": "停止",
        "ready": "[i] 准备就绪。输入地址并点击启动。",
        "err_format": "[!] 错误: 地址格式无效。",
        "err_port": "[!] 错误: 端口必须是数字。",
        "dns_resolve": "[*] 正在解析 {host}...",
        "dns_ok": "[✓] IP 解析成功: {ip}",
        "dns_err": "[x] DNS 错误: 找不到 IP。",
        "ping_test": "[-] 智能端口搜索 {ip}:{port}...",
        "server_found": "[✓] 找到服务器: {name}",
        "server_alive": "[✓] 服务器已响应 (存活)。",
        "server_timeout": "[x] 服务器未响应 (可能离线)。",
        "start_poll": "\n[*] 开始监控: {ip}:{port}",
        "poll_stop": "[*] 监控已停止。",
        "poll_ping": "[-] 轮询 {ip}:{port}...",
        "poll_ans": "[+] 响应: {name}",
        "poll_err": "[x] 无响应。{sec} 秒后重试...",
        "stable": "[✓] 服务器稳定。正在连接...",
        "launch": "[>] 执行命令: {url}",
        "launch_ok": "[✓] 已成功发送至 Steam!",
        "launch_err": "[!] Steam 启动错误: {err}",
        "del": "删",
        "rust_on": "Rust: 运行中 🟢",
        "rust_off": "Rust: 已关闭 🔴",
        "save_ip": "[*] 服务器已添加到历史记录。",
        "wait_wipe": "等待删档/重启",
        "log_mon": "[*] 正在读取 Rust 日志。断开时将立即重连！",
        "log_err": "[!] 检测到断开连接！正在重连...",
        "wait_mode": "[*] 等待模式。服务器在线。等待其离线...",
        "wait_down": "[*] 服务器已离线！等待启动和槽位...",
        "wait_ready": "[+] 服务器已启动，但槽位为 0/0。等待地图加载..."
    }
}

LANG_MAP = {
    "RU": "RU - Русский",
    "EN": "EN - English",
    "ES": "ES - Español",
    "FR": "FR - Français",
    "DE": "DE - Deutsch",
    "ZH": "ZH - 中文"
}

import shutil

# Settings
appdata_dir = os.path.join(os.environ.get("APPDATA", ""), "RustAutoConnect")
DATA_FILE = os.path.join(appdata_dir, "data.json")
POLL_INTERVAL = 3.0 # seconds

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.data = self.load_data()
        self.lang = self.data.get("lang", "RU")
        self.history = self.data.get("history", [])
        self.favorites = self.data.get("favorites", [])

        self.title(self.t("title"))
        self.geometry("800x480")
        self.minsize(700, 400)
        
        self.is_polling = False
        self.poll_thread = None
        self.is_auto_update_enabled = self.data.get("auto_update", True)
        self.auto_update = ctk.BooleanVar(value=self.is_auto_update_enabled)
        self.is_reconnecting = False
        
        self.tray_icon = None
        self.protocol('WM_DELETE_WINDOW', self.withdraw_window)

        # Grid layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Left Panel (History)
        self.left_panel = ctk.CTkFrame(self, width=240, corner_radius=0)
        self.left_panel.grid(row=0, column=0, sticky="nsew")
        self.left_panel.grid_rowconfigure(3, weight=1)

        self.history_label = ctk.CTkLabel(self.left_panel, text=self.t("history"), font=ctk.CTkFont(size=16, weight="bold"))
        self.history_label.grid(row=0, column=0, padx=20, pady=(20, 5))

        self.filter_var = ctk.StringVar(value="All Servers")
        self.filter_menu = ctk.CTkOptionMenu(self.left_panel, values=["All Servers", "Favorites"], variable=self.filter_var, command=lambda e: self.refresh_history_ui())
        self.filter_menu.grid(row=1, column=0, padx=20, pady=(0, 10), sticky="ew")

        # Smart Search
        self.search_var = ctk.StringVar()
        self.search_var.trace("w", lambda *args: self.refresh_history_ui())
        self.search_entry = ctk.CTkEntry(self.left_panel, placeholder_text="Поиск...", textvariable=self.search_var)
        self.search_entry.grid(row=2, column=0, padx=20, pady=(0, 10), sticky="ew")

        self.history_scroll = ctk.CTkScrollableFrame(self.left_panel)
        self.history_scroll.grid(row=3, column=0, sticky="nsew", padx=10, pady=0)

        # Bottom Frame of Left Panel (Language + Status)
        self.left_bottom_frame = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        self.left_bottom_frame.grid(row=4, column=0, sticky="ew", padx=10, pady=10)
        self.left_bottom_frame.grid_columnconfigure(1, weight=1)

        # Language Selector
        self.lang_menu = ctk.CTkOptionMenu(self.left_bottom_frame, values=list(LANG_MAP.values()), 
                                           command=self.change_lang, width=80)
        self.lang_menu.grid(row=0, column=0, sticky="w")
        self.lang_menu.set(self.lang) # Show short code on init

        # Rust Running Status Label
        self.rust_status_label = ctk.CTkLabel(self.left_bottom_frame, text=self.t("rust_off"), font=ctk.CTkFont(weight="bold"), text_color="#C25A5A")
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

        self.ip_entry = ctk.CTkComboBox(self.input_frame, values=[f"{f.get('name', 'Unknown')} ({f.get('ip', 'Unknown')})" for f in self.favorites])
        self.ip_entry.set("") # Empty by default
        self.ip_entry.grid(row=0, column=0, padx=10, pady=10, sticky="ew")

        # Start button
        self.connect_btn = ctk.CTkButton(self.input_frame, text=self.t("start"), command=self.start_process, width=120)
        self.connect_btn.grid(row=0, column=1, padx=10, pady=10)

        # Bottom frame for Auto-Update (at the very bottom of right panel)
        self.bottom_frame = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        self.bottom_frame.grid(row=3, column=0, sticky="e", padx=20, pady=(0, 10))
        
        self.update_ready_label = ctk.CTkLabel(self.bottom_frame, text="Update Ready!", text_color="#50C878", font=ctk.CTkFont(weight="bold"))
        self.update_ready_label.pack(side="left", padx=10)
        self.update_ready_label.pack_forget() # Hide by default

        self.update_check = ctk.CTkCheckBox(self.bottom_frame, text="Auto-Update Rust", variable=self.auto_update, command=self.on_auto_update_change)
        self.update_check.pack(side="right", padx=10)

        # Log Frame (Now taking row 1 and row 2 space)
        self.log_frame = ctk.CTkFrame(self.right_panel)
        self.log_frame.grid(row=1, column=0, rowspan=2, padx=20, pady=(0, 10), sticky="nsew")
        self.log_frame.grid_columnconfigure(0, weight=1)
        self.log_frame.grid_rowconfigure(0, weight=1)

        self.log_textbox = ctk.CTkTextbox(self.log_frame, state="disabled", font=ctk.CTkFont(family="Consolas", size=13))
        self.log_textbox.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        self.refresh_history_ui()
        self.log(self.t("ready"))

        # Start Rust process checker and update checker
        threading.Thread(target=self.check_rust_status_loop, daemon=True).start()
        threading.Thread(target=self.check_rust_update, daemon=True).start()

    def on_auto_update_change(self):
        self.is_auto_update_enabled = self.auto_update.get()
        self.save_data()

    def check_rust_status_loop(self):
        while True:
            try:
                running = any(p.name() == 'RustClient.exe' for p in psutil.process_iter(['name']))
                if running:
                    self.after(0, lambda: self.rust_status_label.configure(text=self.t("rust_on"), text_color="#50C878"))
                else:
                    self.after(0, lambda: self.rust_status_label.configure(text=self.t("rust_off"), text_color="#C25A5A"))
            except Exception:
                pass
            time.sleep(3.0)

    def is_rust_running(self):
        try:
            return any(p.name() == 'RustClient.exe' for p in psutil.process_iter(['name']))
        except Exception:
            pass
        return False

    def is_force_wipe_window(self):
        # Force wipe is first Thursday of the month, ~18:00 UTC.
        # We consider the "window" to be from Thursday 12:00 UTC to Friday 12:00 UTC.
        now = datetime.now(timezone.utc)
        # Find first Thursday of current month
        first_day = now.replace(day=1)
        # weekday(): 0=Mon, 3=Thu
        days_to_thursday = (3 - first_day.weekday() + 7) % 7
        first_thursday = first_day + timedelta(days=days_to_thursday)
        # Window start: 12:00 UTC
        window_start = first_thursday.replace(hour=12, minute=0, second=0, microsecond=0)
        window_end = window_start + timedelta(days=1)
        return window_start <= now <= window_end

    def check_rust_update(self):
        while True:
            if not self.is_auto_update_enabled:
                time.sleep(60.0)
                continue
                
            force_wipe = self.is_force_wipe_window()
            interval = 25.0 if force_wipe else 1800.0 # 25 sec on force wipe, 30 min normal
            
            # If not force wipe and Rust is running, do not spam API or do updates
            rust_running = self.is_rust_running()
            if not force_wipe and rust_running:
                time.sleep(interval)
                continue
                
            try:
                # 1. Fetch latest buildid from SteamCMD API
                req = urllib.request.Request("https://api.steamcmd.net/v1/info/252490", headers={'User-Agent': 'Mozilla/5.0'})
                res = urllib.request.urlopen(req, timeout=5.0)
                data = json.loads(res.read())
                latest_buildid = data['data']['252490']['depots']['branches']['public']['buildid']
                
                # 2. Find local appmanifest_252490.acf
                local_buildid = None
                steam_path = r"C:\Program Files (x86)\Steam"
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                        steam_path, _ = winreg.QueryValueEx(key, "SteamPath")
                except Exception:
                    pass
                    
                manifest_path = os.path.join(steam_path, "steamapps", "appmanifest_252490.acf")
                
                # If not in main steamapps, check libraryfolders.vdf
                if not os.path.exists(manifest_path):
                    lib_folders = os.path.join(steam_path, "steamapps", "libraryfolders.vdf")
                    if os.path.exists(lib_folders):
                        with open(lib_folders, "r", encoding="utf-8", errors="ignore") as f:
                            for line in f:
                                match = re.search(r'"path"\s+"([^"]+)"', line)
                                if match:
                                    p = match.group(1).replace("\\\\", "\\")
                                    test_path = os.path.join(p, "steamapps", "appmanifest_252490.acf")
                                    if os.path.exists(test_path):
                                        manifest_path = test_path
                                        break
                                        
                if os.path.exists(manifest_path):
                    with open(manifest_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                        match = re.search(r'"buildid"\s+"(\d+)"', content)
                        if match:
                            local_buildid = match.group(1)
                
                # 3. Compare
                if local_buildid and latest_buildid and str(local_buildid) != str(latest_buildid):
                    self.after(0, lambda: self.update_ready_label.pack(side="left", padx=10))
                    
                    if force_wipe and self.is_rust_running():
                        self.log_safe("[!] ОБНАРУЖЕН ФОРС-ВАЙП АПДЕЙТ! Закрываем игру для обновления...")
                        # Отключаем поллинг, чтобы монитор логов не начал реконнектиться
                        self.is_polling = False
                        try:
                            subprocess.run('taskkill /F /IM RustClient.exe', shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
                        except: pass
                    else:
                        self.log_safe("[!] Обновление найдено. Ждем скачивания...")

                    # Ждем, пока Steam докачает обнову
                    while True:
                        time.sleep(20.0)
                        try:
                            new_local = None
                            if os.path.exists(manifest_path):
                                with open(manifest_path, "r", encoding="utf-8", errors="ignore") as f:
                                    match2 = re.search(r'"buildid"\s+"(\d+)"', f.read())
                                    if match2:
                                        new_local = match2.group(1)
                                        
                            if new_local and str(new_local) == str(latest_buildid):
                                self.log_safe("[+] Обновление установлено! Запускаем Rust...")
                                self.after(0, self.update_ready_label.pack_forget)
                                webbrowser.open("steam://run/252490")
                                # Небольшая пауза, чтобы не дублировать
                                time.sleep(120.0)
                                break
                        except Exception:
                            pass
                else:
                    self.after(0, self.update_ready_label.pack_forget)
                    
            except Exception:
                pass
                
            time.sleep(interval)

    def t(self, key):
        return LANGUAGES[self.lang].get(key, key)

    def change_lang(self, choice):
        code = choice.split(" ")[0]
        self.lang = code
        self.data["lang"] = self.lang
        self.save_data()
        
        self.title(self.t("title"))
        self.history_label.configure(text=self.t("history"))
        if not self.is_polling:
            self.connect_btn.configure(text=self.t("start"))
        else:
            self.connect_btn.configure(text=self.t("stop"))
        
        if "🟢" in self.rust_status_label.cget("text"):
            self.rust_status_label.configure(text=self.t("rust_on"))
        else:
            self.rust_status_label.configure(text=self.t("rust_off"))
            
        self.lang_menu.set(code)
        self.refresh_history_ui()

    def load_data(self):
        data = {"lang": "RU", "history": []}
        
        # Ensure AppData directory exists
        os.makedirs(appdata_dir, exist_ok=True)
        
        # Migration from old versions (if data.json exists in current folder, move it to AppData)
        old_data_file = "data.json"
        if os.path.exists(old_data_file) and not os.path.exists(DATA_FILE):
            try:
                shutil.copy2(old_data_file, DATA_FILE)
            except Exception:
                pass
                
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass
        elif os.path.exists("history.json"):
            try:
                with open("history.json", "r", encoding="utf-8") as f:
                    data["history"] = json.load(f)
            except Exception:
                pass
        return data

    def save_data(self):
        self.data["history"] = self.history
        self.data["favorites"] = self.favorites
        self.data["auto_update"] = self.auto_update.get()
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=4)

    def add_to_history(self, ip_port, name):
        self.history = [h for h in self.history if h["ip"] != ip_port]
        self.history.insert(0, {"ip": ip_port, "name": name, "added_at": int(time.time())})
        self.history = sorted(self.history, key=lambda x: x.get("added_at", 0), reverse=True)
        self.history = self.history[:20]
        self.save_data()
        self.refresh_history_ui()

    def remove_from_history(self, ip_port):
        self.history = [h for h in self.history if h["ip"] != ip_port]
        self.save_data()
        self.refresh_history_ui()

    def refresh_history_ui(self):
        for widget in self.history_scroll.winfo_children():
            widget.destroy()
            
        show_favs_only = (self.filter_var.get() == "Favorites")
        search_query = self.search_var.get().lower().strip()
        
        # Sort history by timestamp descending
        self.history = sorted(self.history, key=lambda x: x.get("added_at", 0), reverse=True)
        for item in self.history:
            ip = item['ip']
            display_name = item.get('name', 'Rust Server')
            
            if search_query:
                if search_query not in ip.lower() and search_query not in display_name.lower():
                    continue

            is_fav = any(f["ip"] == ip for f in self.favorites)
            
            if show_favs_only and not is_fav:
                continue

            frame = ctk.CTkFrame(self.history_scroll, fg_color="transparent")
            frame.pack(fill="x", pady=2)
            
            short_name = display_name
            if len(short_name) > 18:
                short_name = short_name[:15] + "..."
            
            btn_text = f"{ip}\n({short_name})"
            btn = ctk.CTkButton(frame, text=btn_text, fg_color="#2b2b2b", 
                                hover_color="#3b3b3b", text_color=("gray80", "white"),
                                command=lambda i=ip: self.select_history(i))
            btn.pack(side="left", fill="x", expand=True, padx=(0, 5))
            
            btn_font = ctk.CTkFont(family="Arial", size=14)
            
            fav_text = "⭐" if is_fav else "☆"
            fav_color = "#3B8ED0" if is_fav else "#555555"
            fav_btn = ctk.CTkButton(frame, text=fav_text, width=28, height=28, font=btn_font, fg_color=fav_color,
                                    command=lambda i=ip, n=display_name: self.toggle_favorite(i, n))
            fav_btn.pack(side="left", padx=(0, 2))

            edit_btn = ctk.CTkButton(frame, text="✎", width=28, height=28, font=btn_font, fg_color="#3B8ED0", hover_color="#36719F",
                                    command=lambda i=ip, n=display_name: self.edit_history_name(i, n))
            edit_btn.pack(side="left", padx=(0, 2))

            del_btn = ctk.CTkButton(frame, text="X", width=28, height=28, font=btn_font, fg_color="#C25A5A", hover_color="#914141",
                                    command=lambda i=ip: self.remove_from_history(i))
            del_btn.pack(side="right")

    def toggle_favorite(self, ip_port, name):
        is_fav = any(f["ip"] == ip_port for f in self.favorites)
        if is_fav:
            self.favorites = [f for f in self.favorites if f["ip"] != ip_port]
        else:
            self.favorites.append({"name": name, "ip": ip_port})
        self.save_data()
        self.refresh_history_ui()
        # Update combo box values
        self.ip_entry.configure(values=[f"{f['name']} ({f['ip']})" for f in self.favorites])

    def edit_history_name(self, ip_port, current_name):
        dialog = ctk.CTkInputDialog(text="Enter new name for server:", title="Edit Name")
        new_name = dialog.get_input()
        if new_name:
            for h in self.history:
                if h["ip"] == ip_port:
                    h["name"] = new_name
            for f in self.favorites:
                if f["ip"] == ip_port:
                    f["name"] = new_name
            self.save_data()
            self.refresh_history_ui()
            self.ip_entry.configure(values=[f"{f['name']} ({f['ip']})" for f in self.favorites])

    def select_history(self, ip_port):
        if self.is_polling:
            return
        self.ip_entry.set(ip_port)

    def log(self, msg):
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", msg + "\n")
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def log_safe(self, msg):
        self.after(0, self.log, msg)

    def save_favorite_dialog(self):
        target = self.ip_entry.get().strip()
        if not target: return
        
        # If it's already a formatted string "Name (IP:PORT)", extract IP
        if "(" in target and ")" in target:
            target = target.split("(")[-1].replace(")", "").strip()
            
        dialog = ctk.CTkInputDialog(text="Enter a name for this favorite server:", title="Save Favorite")
        name = dialog.get_input()
        if name:
            self.favorites = [f for f in self.favorites if f["ip"] != target]
            self.favorites.append({"name": name, "ip": target})
            self.save_data()
            
            # Update combobox
            self.ip_entry.configure(values=[f"{f['name']} ({f['ip']})" for f in self.favorites])
            self.ip_entry.set(f"{name} ({target})")
            self.log_safe(f"[*] Saved to favorites: {name}")

    def get_target_ip(self):
        target = self.ip_entry.get().strip()
        # If it's selected from combobox, it looks like "Name (IP:PORT)"
        if "(" in target and ")" in target:
            target = target.split("(")[-1].replace(")", "").strip()
        return target

    def save_only(self):
        target = self.get_target_ip()
        if not target or ":" not in target:
            self.log(self.t("err_format"))
            return
        threading.Thread(target=self.run_save_logic, args=(target,), daemon=True).start()

    def run_save_logic(self, target):
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
        is_alive, name, max_players = self.check_server_alive(real_ip, port)
        if is_alive and name:
            server_name = name
            
        target_str = f"{real_ip}:{port}"
        self.after(0, self.add_to_history, target_str, server_name)
        self.log_safe(self.t("save_ip"))

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
        self.connect_btn.configure(text=self.t("start"), fg_color=['#3B8ED0', '#1F6AA5'], hover_color=['#36719F', '#144870'])
        self.ip_entry.configure(state="normal")
        self.log(self.t("poll_stop"))

    def stop_polling_safe(self):
        self.after(0, self.stop_polling)

    def check_server_alive(self, ip, base_port):
        """ Умный поиск Query порта, возвращает (is_alive, name, max_players) """
        offsets = [0, 15, 3, 1, 123]
        for offset in offsets:
            try:
                info = a2s.info((ip, base_port + offset), timeout=0.6)
                return True, info.server_name, info.max_players
            except a2s.exceptions.BrokenMessageError:
                return True, None, 1 # If BrokenMessage, we assume it's alive and ready
            except Exception:
                continue
        return False, None, 0

    def run_logic(self, target):
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
            self.log_safe(self.t("dns_resolve").format(host=host))
            real_ip = socket.gethostbyname(host)
            if real_ip != host:
                self.log_safe(self.t("dns_ok").format(ip=real_ip))
        except socket.gaierror:
            self.log_safe(self.t("dns_err").format(host=host))

        # 2. State Machine for Wipe / Connect
        # В Варианте 1 мы больше не ждем, пока сервер выключится. Сразу ждем его онлайна (если он уже онлайн - зайдет).
        state = "WAITING_ONLINE"
        
        self.log_safe(self.t("ping_test").format(ip=real_ip, port=port))
        
        # Initial check
        is_alive, name, max_players = self.check_server_alive(real_ip, port)
        server_name = name if name else host
        
        target_str = f"{real_ip}:{port}"
        self.after(0, self.add_to_history, target_str, server_name)
        
        self.log_safe(self.t("start_poll").format(ip=real_ip, port=port))

        if not self.is_polling: return

        success_count = 0
        while self.is_polling:
            is_alive, name, max_players = self.check_server_alive(real_ip, port)
            if name: server_name = name
            
            if state == "WAITING_ONLINE":
                if is_alive:
                    if max_players > 0:
                        success_count += 1
                        self.log_safe(self.t("poll_ans").format(name=server_name))
                    else:
                        success_count = 0
                        self.log_safe(self.t("wait_ready"))
                else:
                    success_count = 0
                    self.log_safe(self.t("poll_err").format(sec=POLL_INTERVAL))
                
                if success_count >= 2:
                    self.log_safe(self.t("stable"))
                    
                    target_str = f"{real_ip}:{port}"
                    self.after(0, self.add_to_history, target_str, server_name)
                    
                    self.launch_game(target_str)
                    
                    # Reset the reconnecting flag once we successfully connect
                    self.is_reconnecting = False
                    
                    # Instead of stopping, we transition to Log Monitoring mode
                    self.start_log_monitor(target_str)
                    break

            current_interval = POLL_INTERVAL
            for _ in range(int(current_interval * 10)):
                if not self.is_polling:
                    break
                time.sleep(0.1)

    def start_log_monitor(self, target_str):
        self.log_safe(self.t("log_mon"))
        threading.Thread(target=self.monitor_rust_logs, args=(target_str,), daemon=True).start()

    def monitor_rust_logs(self, target_str):
        log_path = os.path.join(os.environ.get("USERPROFILE", ""), "AppData", "LocalLow", "Facepunch Studios LTD", "Rust", "Player.log")
        
        while self.is_polling:
            if os.path.exists(log_path):
                break
            time.sleep(1.0)
            
        if not self.is_polling or not os.path.exists(log_path):
            return

        disconnect_keywords = ["Disconnected", "Connection Attempt Failed", "Rejected", "Kicked", "User Cancelled", "Server Closed"]

        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(0, 2)
                buffer = ""
                
                while self.is_polling:
                    try:
                        current_size = os.path.getsize(log_path)
                    except Exception:
                        time.sleep(0.5)
                        continue

                    where = f.tell()
                    
                    if current_size == where:
                        if not self.is_rust_running():
                            self.log_safe("[!] Обнаружен краш или закрытие игры! Переподключаюсь...")
                            time.sleep(2.0)
                            if self.is_polling:
                                self.start_process_force(target_str)
                                return
                        time.sleep(0.5)
                        continue
                    elif current_size < where:
                        f.seek(0, 2)
                        buffer = ""
                        continue
                        
                    line = f.readline()
                    if not line:
                        time.sleep(0.1)
                        continue
                        
                    buffer += line
                    if not buffer.endswith("\n"):
                        continue
                        
                    line_to_check = buffer
                    buffer = ""
                    
                    if any(k in line_to_check for k in disconnect_keywords):
                        self.log_safe(self.t("log_err"))
                        time.sleep(2.0)
                        if self.is_polling:
                            self.start_process_force(target_str)
                            return
        except Exception:
            pass

    def start_process_force(self, target):
        if getattr(self, 'is_reconnecting', False):
            return
        self.is_reconnecting = True
        threading.Thread(target=self.run_logic, args=(target,), daemon=True).start()

    def update_entry(self, text):
        state = self.ip_entry.cget("state")
        self.ip_entry.configure(state="normal")
        self.ip_entry.set(text)
        self.ip_entry.configure(state=state)

    def launch_game(self, target):
        url = f"steam://run/252490//+connect {target}"
        self.log_safe(self.t("launch").format(url=url))
        try:
            if os.name == 'nt':
                os.startfile(url)
            else:
                webbrowser.open(url)
            self.log_safe(self.t("launch_ok"))
        except Exception as e:
            self.log_safe(self.t("launch_err").format(err=e))

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

    def show_window(self, icon, item):
        self.tray_icon.stop()
        self.tray_icon = None
        self.after(0, self.deiconify)

    def quit_window(self, icon, item):
        self.tray_icon.stop()
        self.after(0, self.destroy)
        os._exit(0)

if __name__ == "__main__":
    app = App()
    app.mainloop()
