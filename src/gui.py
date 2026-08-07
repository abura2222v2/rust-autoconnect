"""
Dark Mode Tkinter GUI Module for Rust Autoconnect Utility.
Implements modern 3-panel elastic grid layout (HistoryPanel, ControlPanel, LogStatusPanel),
responsive minsize (800x500), dark theme styling, smart IP:Port paste, and thread-safe queue updates.
"""

from datetime import datetime
import queue
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from src.history import HistoryManager, format_server_entry

# Color Palette Constants (Dark Theme)
DARK_BG = "#1e1e1e"
PANEL_BG = "#252526"
WIDGET_BG = "#3c3c3c"
TEXT_FG = "#d4d4d4"
HEADER_FG = "#ffffff"
ACCENT_BLUE = "#007acc"
ACCENT_HOVER = "#1f8ad2"
STOP_RED = "#d13438"
STOP_HOVER = "#e81123"

# Log & Status Colors
LOG_COLORS = {
    "info": "#9cdcfe",
    "success": "#4ec9b0",
    "warning": "#dcdcaa",
    "error": "#f44747",
    "timestamp": "#808080",
    "idle": "#d4d4d4"
}


def validate_ip_port(ip_str: str, port_str: str) -> Tuple[bool, str, str, int]:
    """
    Validate IP address and Port strings.
    Returns (is_valid, error_message, clean_ip, clean_port).
    """
    clean_ip = ip_str.strip()
    if not clean_ip:
        return False, "Server IP address cannot be empty.", "", 0

    try:
        port_num = int(port_str.strip())
        if not (1 <= port_num <= 65535):
            return False, f"Port must be between 1 and 65535 (got {port_num}).", clean_ip, 0
    except (ValueError, TypeError):
        return False, f"Invalid port number: '{port_str}'.", clean_ip, 0

    return True, "", clean_ip, port_num


class HistoryPanel(tk.Frame):
    """Left Panel: Server History listbox and management controls."""

    def __init__(
        self,
        parent: tk.Widget,
        on_select_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_add_callback: Optional[Callable[[], None]] = None,
        on_remove_callback: Optional[Callable[[], None]] = None,
        on_clear_callback: Optional[Callable[[], None]] = None,
        **kwargs
    ):
        super().__init__(parent, bg=PANEL_BG, padx=10, pady=10, **kwargs)
        self.on_select_callback = on_select_callback
        self.on_add_callback = on_add_callback
        self.on_remove_callback = on_remove_callback
        self.on_clear_callback = on_clear_callback
        self.servers_data: List[Dict[str, Any]] = []

        self._build_ui()

    def _build_ui(self):
        # Header Label
        lbl_header = tk.Label(
            self,
            text="Server History",
            font=("Segoe UI", 11, "bold"),
            bg=PANEL_BG,
            fg=HEADER_FG,
            anchor="w"
        )
        lbl_header.pack(fill="x", pady=(0, 8))

        # Listbox Frame with Scrollbar
        list_frame = tk.Frame(self, bg=PANEL_BG)
        list_frame.pack(fill="both", expand=True)

        self.scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        self.listbox = tk.Listbox(
            list_frame,
            bg=WIDGET_BG,
            fg=TEXT_FG,
            selectbackground=ACCENT_BLUE,
            selectforeground="#ffffff",
            highlightthickness=1,
            highlightbackground="#555555",
            highlightcolor=ACCENT_BLUE,
            bd=0,
            font=("Consolas", 10),
            yscrollcommand=self.scrollbar.set
        )
        self.scrollbar.config(command=self.listbox.yview)

        self.listbox.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        # Event Bindings
        self.listbox.bind("<<ListboxSelect>>", self._on_listbox_select)
        self.listbox.bind("<Double-1>", self._on_listbox_select)

        # Buttons Frame
        btn_frame = tk.Frame(self, bg=PANEL_BG)
        btn_frame.pack(fill="x", pady=(8, 0))

        self.btn_add = ttk.Button(btn_frame, text="Add Server", command=self._on_add_click)
        self.btn_add.pack(side="left", fill="x", expand=True, padx=(0, 2))

        self.btn_remove = ttk.Button(btn_frame, text="Remove", command=self._on_remove_click)
        self.btn_remove.pack(side="left", fill="x", expand=True, padx=2)

        self.btn_clear = ttk.Button(btn_frame, text="Clear", command=self._on_clear_click)
        self.btn_clear.pack(side="left", fill="x", expand=True, padx=(2, 0))

    def update_history(self, servers: List[Dict[str, Any]]):
        """Update listbox items from history list."""
        self.servers_data = [dict(s) for s in servers]
        self.listbox.delete(0, tk.END)
        for s in self.servers_data:
            self.listbox.insert(tk.END, format_server_entry(s))

    def get_selected_server(self) -> Optional[Dict[str, Any]]:
        """Return the dictionary of the currently selected server, if any."""
        selection = self.listbox.curselection()
        if selection and 0 <= selection[0] < len(self.servers_data):
            return dict(self.servers_data[selection[0]])
        return None

    def _on_listbox_select(self, event=None):
        selected = self.get_selected_server()
        if selected and self.on_select_callback:
            self.on_select_callback(selected)

    def _on_add_click(self):
        if self.on_add_callback:
            self.on_add_callback()

    def _on_remove_click(self):
        if self.on_remove_callback:
            self.on_remove_callback()

    def _on_clear_click(self):
        if self.on_clear_callback:
            self.on_clear_callback()


class ControlPanel(tk.Frame):
    """Center Panel: Server IP/Port inputs, Smart Paste, Connect Toggle & Status Indicator."""

    def __init__(
        self,
        parent: tk.Widget,
        on_connect_toggle_callback: Optional[Callable[[], None]] = None,
        **kwargs
    ):
        super().__init__(parent, bg=PANEL_BG, padx=15, pady=10, **kwargs)
        self.on_connect_toggle_callback = on_connect_toggle_callback
        self.is_connecting = False

        self.ip_var = tk.StringVar()
        self.port_var = tk.StringVar(value="28015")
        self.name_var = tk.StringVar()

        # Bind smart paste / IP trace
        self.ip_var.trace_add("write", self._on_ip_change)

        self._build_ui()

    def _build_ui(self):
        # Header Label
        lbl_header = tk.Label(
            self,
            text="Connection Control",
            font=("Segoe UI", 11, "bold"),
            bg=PANEL_BG,
            fg=HEADER_FG,
            anchor="w"
        )
        lbl_header.pack(fill="x", pady=(0, 15))

        # Inputs Container Frame
        form_frame = tk.Frame(self, bg=PANEL_BG)
        form_frame.pack(fill="x", pady=(0, 15))

        # IP Entry
        lbl_ip = tk.Label(form_frame, text="Server IP / Hostname:", font=("Segoe UI", 9), bg=PANEL_BG, fg=TEXT_FG, anchor="w")
        lbl_ip.pack(fill="x", pady=(0, 2))
        self.entry_ip = ttk.Entry(form_frame, textvariable=self.ip_var, font=("Consolas", 10))
        self.entry_ip.pack(fill="x", pady=(0, 10))

        # Port Entry
        lbl_port = tk.Label(form_frame, text="Port:", font=("Segoe UI", 9), bg=PANEL_BG, fg=TEXT_FG, anchor="w")
        lbl_port.pack(fill="x", pady=(0, 2))
        self.entry_port = ttk.Entry(form_frame, textvariable=self.port_var, font=("Consolas", 10))
        self.entry_port.pack(fill="x", pady=(0, 10))

        # Server Name Entry (Optional)
        lbl_name = tk.Label(form_frame, text="Server Name (Optional):", font=("Segoe UI", 9), bg=PANEL_BG, fg=TEXT_FG, anchor="w")
        lbl_name.pack(fill="x", pady=(0, 2))
        self.entry_name = ttk.Entry(form_frame, textvariable=self.name_var, font=("Consolas", 10))
        self.entry_name.pack(fill="x", pady=(0, 15))

        # Connect / Stop Action Button
        self.btn_connect = ttk.Button(
            form_frame,
            text="Connect",
            style="Accent.TButton",
            command=self._on_btn_click
        )
        self.btn_connect.pack(fill="x", ipady=5)

        # Status Indicator Frame
        status_frame = tk.Frame(self, bg=PANEL_BG)
        status_frame.pack(fill="x", pady=(20, 0))

        lbl_status_title = tk.Label(status_frame, text="Status:", font=("Segoe UI", 9, "bold"), bg=PANEL_BG, fg=TEXT_FG, anchor="w")
        lbl_status_title.pack(fill="x", pady=(0, 2))

        self.lbl_status = tk.Label(
            status_frame,
            text="Idle",
            font=("Segoe UI", 10, "bold"),
            bg=PANEL_BG,
            fg=LOG_COLORS["idle"],
            anchor="w",
            wraplength=220
        )
        self.lbl_status.pack(fill="x")

    def _on_ip_change(self, *args):
        """Smart IP:Port paste handler. Auto-splits pasted 'IP:Port' strings."""
        raw = self.ip_var.get()
        if ":" in raw:
            parts = raw.rsplit(":", 1)
            if len(parts) == 2 and parts[1].strip().isdigit():
                clean_ip = parts[0].strip()
                clean_port = parts[1].strip()
                self.ip_var.set(clean_ip)
                self.port_var.set(clean_port)

    def _on_btn_click(self):
        if self.on_connect_toggle_callback:
            self.on_connect_toggle_callback()

    def set_inputs(self, ip: str, port: Union[int, str], name: str = ""):
        """Populate IP, Port, and Name entry fields."""
        self.ip_var.set(str(ip))
        self.port_var.set(str(port))
        self.name_var.set(str(name))

    def get_inputs(self) -> Tuple[str, str, str]:
        """Return (ip, port, name) values from entry fields."""
        return self.ip_var.get(), self.port_var.get(), self.name_var.get()

    def set_connecting_state(self, is_connecting: bool):
        """Toggle Connect/Stop button state and styling."""
        self.is_connecting = is_connecting
        if is_connecting:
            self.btn_connect.config(text="Stop", style="Stop.TButton")
        else:
            self.btn_connect.config(text="Connect", style="Accent.TButton")

    def update_status(self, status: str, level: str = "info"):
        """Update status indicator text and fg color."""
        color = LOG_COLORS.get(level.lower(), LOG_COLORS["info"])
        self.lbl_status.config(text=status, fg=color)


class LogStatusPanel(tk.Frame):
    """Right Panel: Scrollable real-time activity log widget with level tags and max line guard."""

    def __init__(self, parent: tk.Widget, max_lines: int = 1000, **kwargs):
        super().__init__(parent, bg=PANEL_BG, padx=10, pady=10, **kwargs)
        self.max_lines = max_lines
        self._build_ui()

    def _build_ui(self):
        # Header Label & Clear Button Container
        top_frame = tk.Frame(self, bg=PANEL_BG)
        top_frame.pack(fill="x", pady=(0, 8))

        lbl_header = tk.Label(
            top_frame,
            text="Activity Log",
            font=("Segoe UI", 11, "bold"),
            bg=PANEL_BG,
            fg=HEADER_FG,
            anchor="w"
        )
        lbl_header.pack(side="left", fill="x", expand=True)

        btn_clear_log = ttk.Button(top_frame, text="Clear Log", width=10, command=self.clear_log)
        btn_clear_log.pack(side="right")

        # Scrollable Text Widget Container
        text_frame = tk.Frame(self, bg=PANEL_BG)
        text_frame.pack(fill="both", expand=True)

        self.scrollbar = ttk.Scrollbar(text_frame, orient="vertical")
        self.text_widget = tk.Text(
            text_frame,
            bg=DARK_BG,
            fg=TEXT_FG,
            insertbackground=TEXT_FG,
            selectbackground=ACCENT_BLUE,
            selectforeground="#ffffff",
            highlightthickness=1,
            highlightbackground="#555555",
            bd=0,
            font=("Consolas", 9),
            wrap="word",
            state="disabled",
            yscrollcommand=self.scrollbar.set
        )
        self.scrollbar.config(command=self.text_widget.yview)

        self.text_widget.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        # Configure Log Level Color Tags
        for tag_name, color_hex in LOG_COLORS.items():
            self.text_widget.tag_configure(tag_name, foreground=color_hex)

    def append_log(self, message: str, level: str = "info"):
        """Append timestamped log entry with specified level tag. Enforces max_lines buffer limit."""
        timestamp_str = datetime.now().strftime("[%H:%M:%S] ")
        level_clean = level.lower() if level.lower() in LOG_COLORS else "info"

        self.text_widget.config(state="normal")

        # Append timestamp
        self.text_widget.insert(tk.END, timestamp_str, "timestamp")
        # Append message
        self.text_widget.insert(tk.END, f"{message}\n", level_clean)

        # Enforce max_lines limit
        line_count = int(self.text_widget.index("end-1c").split(".")[0])
        if line_count > self.max_lines:
            excess = line_count - self.max_lines
            self.text_widget.delete("1.0", f"{excess + 1}.0")

        self.text_widget.see(tk.END)
        self.text_widget.config(state="disabled")

    def clear_log(self):
        """Clear all content from the log text widget."""
        self.text_widget.config(state="normal")
        self.text_widget.delete("1.0", tk.END)
        self.text_widget.config(state="disabled")


class MainWindow:
    """
    Main Dark Mode Window Component.
    Exposes thread-safe queue processing, panel composition, styling setup,
    and callback hooks (on_connect_click, on_stop_click, on_history_select).
    """

    def __init__(
        self,
        root: Optional[tk.Tk] = None,
        history_manager: Optional[HistoryManager] = None,
        on_connect_click: Optional[Callable[[str, int], None]] = None,
        on_stop_click: Optional[Callable[[], None]] = None,
        on_history_select: Optional[Callable[[str, int], None]] = None,
    ):
        self.owns_root = root is None
        self.root = root if root is not None else tk.Tk()

        self.history_manager = history_manager if history_manager is not None else HistoryManager()
        self.on_connect_click = on_connect_click
        self.on_stop_click = on_stop_click
        self.on_history_select = on_history_select

        self.msg_queue: queue.Queue = queue.Queue()

        self._configure_root_window()
        self._setup_styles()
        self._build_layout()
        self._load_initial_history()

        # Start periodic thread-safe queue poller (50ms interval)
        self._queue_poll_job = self.root.after(50, self._process_queue)

    def _configure_root_window(self):
        self.root.title("Rust Autoconnect Utility")
        self.root.geometry("850x550")
        self.root.wm_minsize(800, 500)
        self.root.configure(bg=DARK_BG)

    def _setup_styles(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass

        # Global Defaults
        style.configure(".", background=DARK_BG, foreground=TEXT_FG, fieldbackground=WIDGET_BG)
        style.configure("TFrame", background=DARK_BG)

        # Labels
        style.configure("TLabel", background=PANEL_BG, foreground=TEXT_FG)
        style.configure("Header.TLabel", background=PANEL_BG, foreground=HEADER_FG, font=("Segoe UI", 11, "bold"))

        # Entry Fields
        style.configure("TEntry", fieldbackground=WIDGET_BG, foreground=TEXT_FG, insertcolor=TEXT_FG)
        style.map("TEntry", fieldbackground=[("focus", WIDGET_BG)], foreground=[("focus", TEXT_FG)])

        # Buttons
        style.configure("TButton", background=WIDGET_BG, foreground=TEXT_FG, borderwidth=1, focuscolor="none", padding=4)
        style.map(
            "TButton",
            background=[("active", ACCENT_BLUE), ("pressed", ACCENT_HOVER)],
            foreground=[("active", "#ffffff")]
        )

        # Accent Button (Connect)
        style.configure("Accent.TButton", background=ACCENT_BLUE, foreground="#ffffff", borderwidth=1, font=("Segoe UI", 9, "bold"))
        style.map(
            "Accent.TButton",
            background=[("active", ACCENT_HOVER), ("pressed", "#005999")],
            foreground=[("active", "#ffffff")]
        )

        # Stop Button
        style.configure("Stop.TButton", background=STOP_RED, foreground="#ffffff", borderwidth=1, font=("Segoe UI", 9, "bold"))
        style.map(
            "Stop.TButton",
            background=[("active", STOP_HOVER), ("pressed", "#a80000")],
            foreground=[("active", "#ffffff")]
        )

        # Scrollbar
        style.configure("TScrollbar", background=WIDGET_BG, troughcolor=PANEL_BG, borderwidth=0, arrowcolor=TEXT_FG)

    def _build_layout(self):
        # Configure Grid Elastic Weights for 3-Panel Layout
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=2, minsize=220)  # Left: HistoryPanel
        self.root.grid_columnconfigure(1, weight=3, minsize=250)  # Center: ControlPanel
        self.root.grid_columnconfigure(2, weight=4, minsize=320)  # Right: LogStatusPanel

        # Instantiate Panels
        self.history_panel = HistoryPanel(
            self.root,
            on_select_callback=self._on_history_panel_select,
            on_add_callback=self._on_history_panel_add,
            on_remove_callback=self._on_history_panel_remove,
            on_clear_callback=self._on_history_panel_clear
        )
        self.history_panel.grid(row=0, column=0, sticky="nsew", padx=(10, 5), pady=10)

        self.control_panel = ControlPanel(
            self.root,
            on_connect_toggle_callback=self._on_connect_toggle
        )
        self.control_panel.grid(row=0, column=1, sticky="nsew", padx=5, pady=10)

        self.log_panel = LogStatusPanel(
            self.root,
            max_lines=1000
        )
        self.log_panel.grid(row=0, column=2, sticky="nsew", padx=(5, 10), pady=10)

    def _load_initial_history(self):
        history = self.history_manager.get_history()
        self.history_panel.update_history(history)
        if history:
            # Auto-populate control panel with top history item
            top_server = history[0]
            self.control_panel.set_inputs(top_server["ip"], top_server["port"], top_server.get("name", ""))

    # --- Callbacks for HistoryPanel ---
    def _on_history_panel_select(self, server: Dict[str, Any]):
        ip = server.get("ip", "")
        port = server.get("port", 28015)
        name = server.get("name", "")
        self.control_panel.set_inputs(ip, port, name)
        if self.on_history_select:
            self.on_history_select(ip, port)

    def _on_history_panel_add(self):
        raw_ip, raw_port, raw_name = self.control_panel.get_inputs()
        is_valid, err_msg, clean_ip, port_num = validate_ip_port(raw_ip, raw_port)
        if not is_valid:
            self.append_log(f"Cannot add server: {err_msg}", level="warning")
            self.update_status(f"Error: {err_msg}", level="warning")
            return

        added = self.history_manager.add_server(clean_ip, port_num, raw_name)
        self.history_panel.update_history(self.history_manager.get_history())
        display_str = format_server_entry(added)
        self.append_log(f"Added server {display_str} to history.", level="success")
        self.update_status("Server added to history.", level="success")

    def _on_history_panel_remove(self):
        selected = self.history_panel.get_selected_server()
        if not selected:
            self.append_log("No server selected in history list to remove.", level="warning")
            return

        ip = selected["ip"]
        port = selected["port"]
        removed = self.history_manager.remove_server(ip, port)
        if removed:
            self.history_panel.update_history(self.history_manager.get_history())
            self.append_log(f"Removed server [{ip}:{port}] from history.", level="info")
            self.update_status("Server removed.", level="info")

    def _on_history_panel_clear(self):
        self.history_manager.clear_history()
        self.history_panel.update_history([])
        self.append_log("Cleared all server history.", level="info")
        self.update_status("History cleared.", level="info")

    # --- Callbacks for ControlPanel ---
    def _on_connect_toggle(self):
        if self.control_panel.is_connecting:
            # Currently active -> Stop requested
            if self.on_stop_click:
                self.on_stop_click()
            else:
                self.set_connecting_state(False)
                self.update_status("Stopped", level="info")
                self.append_log("Polling stopped by user.", level="info")
        else:
            # Currently idle -> Connect requested
            raw_ip, raw_port, raw_name = self.control_panel.get_inputs()
            is_valid, err_msg, clean_ip, port_num = validate_ip_port(raw_ip, raw_port)

            if not is_valid:
                self.append_log(f"Connection failed: {err_msg}", level="error")
                self.update_status(f"Error: {err_msg}", level="error")
                return

            # Auto-save/update in history on connect
            self.history_manager.add_server(clean_ip, port_num, raw_name)
            self.history_panel.update_history(self.history_manager.get_history())

            if self.on_connect_click:
                self.on_connect_click(clean_ip, port_num)
            else:
                self.set_connecting_state(True)
                self.update_status("Polling server...", level="info")
                self.append_log(f"Starting connection check for [{clean_ip}:{port_num}]...", level="info")

    # --- Thread-Safe Public API ---
    def append_log_threadsafe(self, message: str, level: str = "info"):
        """Post a log entry to the queue from any thread."""
        self.msg_queue.put(("log", (message, level), {}))

    def update_status_threadsafe(self, status: str, level: str = "info"):
        """Post a status update to the queue from any thread."""
        self.msg_queue.put(("status", (status, level), {}))

    def update_history_threadsafe(self, servers: List[Dict[str, Any]]):
        """Post a history list update to the queue from any thread."""
        self.msg_queue.put(("history", (servers,), {}))

    def set_connecting_state_threadsafe(self, is_connecting: bool):
        """Post a connection state update to the queue from any thread."""
        self.msg_queue.put(("connecting_state", (is_connecting,), {}))

    # --- Direct Main-Thread Public API ---
    def append_log(self, message: str, level: str = "info"):
        """Append log message on main thread."""
        self.log_panel.append_log(message, level)

    def update_status(self, status: str, level: str = "info"):
        """Update status label on main thread."""
        self.control_panel.update_status(status, level)

    def update_history(self, servers: List[Dict[str, Any]]):
        """Update history listbox on main thread."""
        self.history_panel.update_history(servers)

    def set_connecting_state(self, is_connecting: bool):
        """Update connect/stop toggle state on main thread."""
        self.control_panel.set_connecting_state(is_connecting)

    # --- Queue Processor ---
    def _process_queue(self):
        """Periodically executed on main thread via root.after(50, ...)."""
        try:
            while not self.msg_queue.empty():
                action, args, kwargs = self.msg_queue.get_nowait()
                if action == "log":
                    self.append_log(*args, **kwargs)
                elif action == "status":
                    self.update_status(*args, **kwargs)
                elif action == "history":
                    self.update_history(*args, **kwargs)
                elif action == "connecting_state":
                    self.set_connecting_state(*args, **kwargs)
        except queue.Empty:
            pass
        finally:
            self._queue_poll_job = self.root.after(50, self._process_queue)

    def run(self):
        """Start the Tkinter event loop."""
        self.root.mainloop()

    def destroy(self):
        """Clean up timers and destroy window."""
        if hasattr(self, "_queue_poll_job") and self._queue_poll_job:
            try:
                self.root.after_cancel(self._queue_poll_job)
            except Exception:
                pass
        self.root.destroy()
