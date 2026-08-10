import customtkinter as ctk
import queue
import threading
import pystray
import time
from PIL import Image, ImageDraw
from typing import Optional

from .tooltip import ToolTip
from ..core.i18n import i18n, I18nManager
from ..core.history_store import history_store, HistoryStore
from ..services.telegram_service import telegram_service

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

COLORS = {
    "canvas": "#151515",
    "sidebar": "#1A1A1A",
    "surface": "#1C1C1C",
    "surface_alt": "#232323",
    "border": "#303030",
    "text": "#E8E8E8",
    "muted": "#9D9D9D",
    "accent": "#E94B16",
    "accent_hover": "#C83B0E",
    "danger": "#DE5148",
    "success": "#55C95D",
}

MAX_WORKSPACE_WIDTH = 920
HOME_HISTORY_DEFAULT_WIDTH = 430
HOME_HISTORY_MIN_WIDTH = 320
HOME_LOG_MIN_WIDTH = 440
BENCH_CONTROLS_DEFAULT_WIDTH = 270
BENCH_CONTROLS_MIN_WIDTH = 220
BENCH_LOG_MIN_WIDTH = 360
SPLITTER_WIDTH = 6


def _draw_icon(kind: str, color: str, size: int = 32) -> Image.Image:
    """Create small local UI icons without adding an icon-pack dependency."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    stroke = max(2, size // 11)
    inset = max(3, size // 6)

    if kind.startswith("star"):
        points = [(size // 2, inset), (size * 58 // 100, size * 40 // 100), (size - inset, size * 42 // 100), (size * 65 // 100, size * 58 // 100), (size * 73 // 100, size - inset), (size // 2, size * 70 // 100), (size * 27 // 100, size - inset), (size * 35 // 100, size * 58 // 100), (inset, size * 42 // 100), (size * 42 // 100, size * 40 // 100)]
        if kind == "star_filled":
            draw.polygon(points, fill=color)
        else:
            draw.line(points + [points[0]], fill=color, width=stroke, joint="curve")
    elif kind == "shield":
        points = [(size // 2, inset), (size - inset, size * 28 // 100), (size * 78 // 100, size * 68 // 100), (size // 2, size - inset), (size * 22 // 100, size * 68 // 100), (inset, size * 28 // 100)]
        draw.line(points + [points[0]], fill=color, width=stroke, joint="curve")
        if color == COLORS["accent"]:
            draw.line([(size * 34 // 100, size * 52 // 100), (size * 45 // 100, size * 63 // 100), (size * 67 // 100, size * 40 // 100)], fill=color, width=stroke, joint="curve")
    elif kind == "play":
        draw.polygon([(size * 38 // 100, size * 27 // 100), (size * 72 // 100, size // 2), (size * 38 // 100, size * 73 // 100)], fill=color)
    elif kind == "nav_connect":
        draw.line((size // 2, inset, size // 2, size * 42 // 100), fill=color, width=stroke)
        draw.line((size * 35 // 100, inset, size * 65 // 100, inset), fill=color, width=stroke)
        draw.arc((size * 24 // 100, size * 30 // 100, size * 76 // 100, size * 84 // 100), 10, 170, fill=color, width=stroke)
        draw.line((size * 36 // 100, size * 68 // 100, size * 64 // 100, size * 68 // 100), fill=color, width=stroke)
    elif kind == "nav_bench":
        draw.arc((inset, inset, size - inset, size - inset), 200, 340, fill=color, width=stroke)
        draw.line((size // 2, size // 2, size * 66 // 100, size * 36 // 100), fill=color, width=stroke)
        draw.ellipse((size * 45 // 100, size * 45 // 100, size * 55 // 100, size * 55 // 100), fill=color)
    elif kind == "nav_settings":
        draw.ellipse((size * 25 // 100, size * 25 // 100, size * 75 // 100, size * 75 // 100), outline=color, width=stroke)
        draw.ellipse((size * 42 // 100, size * 42 // 100, size * 58 // 100, size * 58 // 100), outline=color, width=stroke)
        for x1, y1, x2, y2 in ((50, 8, 50, 25), (50, 75, 50, 92), (8, 50, 25, 50), (75, 50, 92, 50)):
            draw.line((size * x1 // 100, size * y1 // 100, size * x2 // 100, size * y2 // 100), fill=color, width=stroke)
    elif kind == "brand":
        draw.rounded_rectangle((1, 1, size - 2, size - 2), radius=max(3, size // 9), fill=COLORS["accent"])
        node = max(3, size // 7)
        draw.line((size * 30 // 100, size * 35 // 100, size * 70 // 100, size * 35 // 100), fill=COLORS["canvas"], width=stroke + 1)
        draw.line((size * 35 // 100, size * 35 // 100, size * 64 // 100, size * 68 // 100), fill=COLORS["canvas"], width=stroke + 1)
        draw.rectangle((size * 22 // 100, size * 25 // 100, size * 22 // 100 + node, size * 25 // 100 + node), fill=COLORS["canvas"])
        draw.rectangle((size * 68 // 100, size * 25 // 100, size * 68 // 100 + node, size * 25 // 100 + node), fill=COLORS["canvas"])
        draw.rectangle((size * 62 // 100, size * 64 // 100, size * 62 // 100 + node, size * 64 // 100 + node), fill=COLORS["canvas"])

    return image


class MainWindow(ctk.CTk):
    def __init__(self, history_mgr: Optional[HistoryStore] = None, i18n_mgr: Optional[I18nManager] = None):
        super().__init__()
        
        self.history_store = history_mgr if history_mgr is not None else history_store
        self.i18n = i18n_mgr if i18n_mgr is not None else i18n

        self.lang = self.history_store.get_lang()
        self.i18n.set_lang(self.lang)

        self.title(self.t("title"))
        # Windows applies the active DPI scale to Tk dimensions. These values
        # render as the 1280x900 Command Center reference at 125% scaling.
        self.geometry("1024x728")
        self.minsize(900, 646)
        self.configure(fg_color=COLORS["canvas"])

        self._search_timer = None
        self._ui_callback_queue: queue.Queue[tuple] = queue.Queue()
        self._ui_dispatch_closing = False
        self._ui_dispatch_after_id = self.after(25, self._drain_ui_callbacks)
        self.is_auto_update_enabled = self.history_store.get_auto_update()
        self.auto_update = ctk.BooleanVar(value=self.is_auto_update_enabled)
        self.auto_scroll = ctk.BooleanVar(value=True)
        self.rust_playtime_started_at: Optional[float] = None
        self.last_connected_var = ctk.StringVar(value=self.t("not_connected"))
        self.session_status_var = ctk.StringVar(value=self.t("idle"))
        self.playtime_var = ctk.StringVar(value="00:00:00")
        self._history_width = self.history_store.get_home_splitter_width()
        self._bench_controls_width = self.history_store.get_bench_splitter_width()
        self._applied_history_width = None
        self._applied_bench_controls_width = None
        self._last_home_workspace_width = None
        self._last_bench_workspace_width = None
        self._home_drag_origin_x = None
        self._home_drag_origin_width = None
        self._bench_drag_origin_x = None
        self._bench_drag_origin_width = None
        self._pending_home_width = None
        self._pending_bench_width = None

        self._nav_marker_after_id = None
        self._status_pulse_after_id = None
        self._icon_images = {
            "brand": ctk.CTkImage(light_image=_draw_icon("brand", COLORS["accent"], 48), dark_image=_draw_icon("brand", COLORS["accent"], 48), size=(38, 38)),
            "favorite": ctk.CTkImage(light_image=_draw_icon("star_filled", COLORS["accent"]), dark_image=_draw_icon("star_filled", COLORS["accent"]), size=(18, 18)),
            "favorite_off": ctk.CTkImage(light_image=_draw_icon("star_outline", COLORS["muted"]), dark_image=_draw_icon("star_outline", COLORS["muted"]), size=(18, 18)),
            "armed": ctk.CTkImage(light_image=_draw_icon("shield", COLORS["accent"]), dark_image=_draw_icon("shield", COLORS["accent"]), size=(18, 18)),
            "disarmed": ctk.CTkImage(light_image=_draw_icon("shield", COLORS["muted"]), dark_image=_draw_icon("shield", COLORS["muted"]), size=(18, 18)),
            "connect": ctk.CTkImage(light_image=_draw_icon("play", COLORS["text"]), dark_image=_draw_icon("play", COLORS["text"]), size=(16, 16)),
        }
        for icon_name in ("nav_connect", "nav_bench", "nav_settings"):
            self._icon_images[f"{icon_name}_muted"] = ctk.CTkImage(
                light_image=_draw_icon(icon_name, COLORS["muted"]),
                dark_image=_draw_icon(icon_name, COLORS["muted"]),
                size=(20, 20),
            )
            self._icon_images[f"{icon_name}_active"] = ctk.CTkImage(
                light_image=_draw_icon(icon_name, COLORS["accent"]),
                dark_image=_draw_icon(icon_name, COLORS["accent"]),
                size=(20, 20),
            )

        self.tray_icon = None
        self.protocol('WM_DELETE_WINDOW', self._on_close_requested)
        self.bind('<Unmap>', self.on_unmap)

        # Main grid layout: top bar, sidebar, and workspace.
        self.grid_columnconfigure(0, minsize=190)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, minsize=48)

        self.topbar = ctk.CTkFrame(self, height=64, corner_radius=0, fg_color="#171717", border_width=1, border_color=COLORS["border"])
        self.topbar.grid(row=0, column=0, columnspan=2, sticky="new")
        self.topbar.grid_propagate(False)
        self.topbar.grid_columnconfigure(1, weight=1)
        self.brand_mark = ctk.CTkLabel(self.topbar, text="", image=self._icon_images["brand"], width=38, height=38)
        self.brand_mark.grid(row=0, column=0, padx=(20, 10), pady=12)
        self.brand_text = ctk.CTkFrame(self.topbar, fg_color="transparent")
        self.brand_text.grid(row=0, column=1, sticky="w")
        self.topbar_title = ctk.CTkLabel(self.brand_text, text="Rust AutoConnect", font=ctk.CTkFont(size=16, weight="bold"), text_color=COLORS["text"])
        self.topbar_title.pack(anchor="w", pady=(0, 1))
        self.topbar_subtitle = ctk.CTkLabel(self.brand_text, text=self.t("command_center"), font=ctk.CTkFont(size=12), text_color=COLORS["muted"])
        self.topbar_subtitle.pack(anchor="w")

        # ==========================================
        # 1. SIDEBAR FRAME
        # ==========================================
        self.sidebar_frame = ctk.CTkFrame(self, width=190, corner_radius=0, fg_color=COLORS["sidebar"], border_width=1, border_color=COLORS["border"])
        self.sidebar_frame.grid(row=1, column=0, sticky="nsew")
        self.sidebar_frame.grid_propagate(False)
        self.sidebar_frame.grid_columnconfigure(0, weight=1)
        self.sidebar_frame.grid_rowconfigure(4, weight=1)

        self.nav_home_btn = self._nav_button(self.t("nav_home"), self.show_home_frame, "nav_connect")
        self.nav_home_btn.grid(row=0, column=0, padx=4, pady=(10, 0), sticky="ew")

        self.nav_bench_btn = self._nav_button(self.t("nav_bench"), self.show_bench_frame, "nav_bench")
        self.nav_bench_btn.grid(row=1, column=0, padx=4, pady=0, sticky="ew")

        self.nav_settings_btn = self._nav_button(self.t("nav_settings"), self.show_settings_frame, "nav_settings")
        self.nav_settings_btn.grid(row=2, column=0, padx=4, pady=0, sticky="ew")
        self._nav_rows = {
            self.nav_home_btn: 0,
            self.nav_bench_btn: 1,
            self.nav_settings_btn: 2,
        }
        self._nav_marker_padding = {
            self.nav_home_btn: (10, 0),
            self.nav_bench_btn: 0,
            self.nav_settings_btn: 0,
        }
        self._nav_icon_names = {
            self.nav_home_btn: "nav_connect",
            self.nav_bench_btn: "nav_bench",
            self.nav_settings_btn: "nav_settings",
        }
        self.nav_active_marker = ctk.CTkFrame(
            self.sidebar_frame,
            width=3,
            height=44,
            corner_radius=0,
            fg_color=COLORS["accent"],
        )
        self.nav_active_marker.grid(row=0, column=0, padx=(3, 0), pady=(10, 0), sticky="w")

        self.sidebar_footer = ctk.CTkFrame(self, height=48, corner_radius=0, fg_color="#171717", border_width=1, border_color=COLORS["border"])
        self.sidebar_footer.grid(row=2, column=0, sticky="nsew")
        self.sidebar_footer.grid_propagate(False)
        self.system_status_frame = ctk.CTkFrame(self.sidebar_footer, fg_color="transparent")
        self.system_status_frame.pack(fill="x", padx=14, pady=12)
        self.system_status_frame.grid_columnconfigure(4, weight=1)
        self.version_label = ctk.CTkLabel(self.system_status_frame, text=self.t("version_fmt", version="v1.3.0"), font=ctk.CTkFont(size=10), text_color=COLORS["muted"])
        self.version_label.grid(row=0, column=0, sticky="w")
        self.status_separator = ctk.CTkLabel(self.system_status_frame, text="|", font=ctk.CTkFont(size=10), text_color=COLORS["border"])
        self.status_separator.grid(row=0, column=1, padx=6)
        self.version_state_label = ctk.CTkLabel(self.system_status_frame, text=self.t("checking"), font=ctk.CTkFont(size=10, weight="bold"), text_color=COLORS["muted"])
        self.version_state_label.grid(row=0, column=2, sticky="w")
        self.rust_status_separator = ctk.CTkLabel(self.system_status_frame, text="|", font=ctk.CTkFont(size=10), text_color=COLORS["border"])
        self.rust_status_separator.grid(row=0, column=3, padx=6)
        self.rust_status_label = ctk.CTkLabel(self.system_status_frame, text="Rust", font=ctk.CTkFont(size=10, weight="bold"), text_color=COLORS["danger"])
        self.rust_status_label.grid(row=0, column=4, sticky="w")
        self.rust_status_tooltip = ToolTip(self.rust_status_label, self.t("rust_not_running"))

        self.footer = ctk.CTkFrame(self, height=48, corner_radius=0, fg_color="#171717", border_width=1, border_color=COLORS["border"])
        self.footer.grid(row=2, column=1, sticky="sew")
        self.footer.grid_propagate(False)
        self.footer.grid_columnconfigure(0, weight=1)
        self.footer_armed_label = ctk.CTkLabel(self.footer, text=self.t("reconnect_disarmed"), font=ctk.CTkFont(size=12, weight="bold"), text_color=COLORS["muted"])
        self.footer_armed_label.grid(row=0, column=1, padx=(12, 14), pady=10)
        self.disarm_btn = ctk.CTkButton(self.footer, text=self.t("disarm"), width=82, height=30, command=self.disarm_server, fg_color=COLORS["surface_alt"], hover_color="#303030", border_width=1, border_color=COLORS["border"])
        self.disarm_btn.grid(row=0, column=2, padx=(0, 18), pady=8)

        # ==========================================
        # 2. CONTENT FRAMES (Overlapping Grid)
        # ==========================================
        self.home_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.bench_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.settings_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")

        # Place them all in the same grid cell
        for frame in (self.home_frame, self.bench_frame, self.settings_frame):
            frame.grid(row=1, column=1, sticky="nsew")

        # ==========================================
        # 2.1 HOME FRAME (History + Connection)
        # ==========================================
        self.home_frame.grid_columnconfigure(0, weight=1)
        self.home_frame.grid_rowconfigure(3, weight=1)
        self.home_frame.bind("<Configure>", self._fit_home_content)

        self.home_header = ctk.CTkLabel(self.home_frame, text=self.t("connect_to_server"), font=ctk.CTkFont(size=17, weight="bold"), text_color=COLORS["text"])
        self.home_header.grid(row=0, column=0, padx=20, pady=(12, 6), sticky="w")
        self.home_subtitle = ctk.CTkLabel(self.home_frame, text="", font=ctk.CTkFont(size=1), text_color=COLORS["muted"])

        self.input_frame = ctk.CTkFrame(self.home_frame, corner_radius=4, fg_color=COLORS["surface"], border_width=1, border_color=COLORS["border"])
        self.input_frame.grid(row=1, column=0, padx=20, pady=(0, 0), sticky="ew")
        self.input_frame.grid_columnconfigure(0, weight=1)
        self.address_label = ctk.CTkLabel(self.input_frame, text=self.t("server_address"), font=ctk.CTkFont(size=10, weight="bold"), text_color=COLORS["muted"])
        self.address_label.grid(row=0, column=0, padx=14, pady=(8, 0), sticky="w")
        self.connection_row = ctk.CTkFrame(self.input_frame, fg_color="transparent")
        self.connection_row.grid(row=1, column=0, padx=14, pady=(2, 10), sticky="ew")
        self.connection_row.grid_columnconfigure(0, weight=1)
        self.ip_entry = ctk.CTkEntry(self.connection_row, height=34, border_width=1, border_color=COLORS["border"], fg_color=COLORS["surface_alt"], text_color=COLORS["text"], font=ctk.CTkFont(family="Consolas", size=14))
        self.ip_entry.grid(row=0, column=0, sticky="ew")
        self.connect_btn = ctk.CTkButton(self.connection_row, text=self.t("connect"), command=self._on_connect_btn_click, width=136, height=34, corner_radius=3, fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"], text_color=COLORS["canvas"], font=ctk.CTkFont(size=12, weight="bold"))
        self.connect_btn.grid(row=0, column=1, padx=(8, 0), sticky="ew")

        self.status_strip = ctk.CTkFrame(self.home_frame, corner_radius=0, fg_color="transparent", border_width=0)
        self.status_strip.grid(row=2, column=0, padx=20, pady=(0, 8), sticky="ew")
        self.status_strip.grid_columnconfigure(9, weight=1)
        ctk.CTkLabel(self.status_strip, text="●", text_color=COLORS["success"], font=ctk.CTkFont(size=14)).grid(row=0, column=0, padx=(0, 6), pady=8)
        ctk.CTkLabel(self.status_strip, text=self.t("status_lbl"), text_color=COLORS["muted"], font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=1, pady=8)
        self.session_status_label = ctk.CTkLabel(self.status_strip, textvariable=self.session_status_var, font=ctk.CTkFont(size=12))
        self.session_status_label.grid(row=0, column=2, padx=(4, 14), pady=8)
        ctk.CTkLabel(self.status_strip, text="|", text_color=COLORS["border"]).grid(row=0, column=3, pady=8)
        ctk.CTkLabel(self.status_strip, text=self.t("last_connected_lbl"), text_color=COLORS["muted"], font=ctk.CTkFont(size=12)).grid(row=0, column=4, padx=(14, 4), pady=8)
        self.last_connected_label = ctk.CTkLabel(self.status_strip, textvariable=self.last_connected_var, font=ctk.CTkFont(size=12))
        self.last_connected_label.grid(row=0, column=5, padx=(0, 14), pady=8)
        self.last_connected_tooltip = ToolTip(self.last_connected_label, self.t("not_connected"))
        ctk.CTkLabel(self.status_strip, text="|", text_color=COLORS["border"]).grid(row=0, column=6, pady=8)
        ctk.CTkLabel(self.status_strip, text=self.t("playtime_lbl"), text_color=COLORS["muted"], font=ctk.CTkFont(size=12)).grid(row=0, column=7, padx=(14, 4), pady=8, sticky="w")
        ctk.CTkLabel(self.status_strip, textvariable=self.playtime_var, font=ctk.CTkFont(size=12)).grid(row=0, column=8, padx=(0, 14), pady=8, sticky="w")
        self.home_content = ctk.CTkFrame(self.home_frame, corner_radius=0, fg_color="transparent")
        self.home_content.grid(row=3, column=0, padx=0, pady=(0, 0), sticky="nsew")
        self.home_content.grid_propagate(False)
        self.home_content.grid_columnconfigure(0, minsize=HOME_HISTORY_DEFAULT_WIDTH)
        self.home_content.grid_columnconfigure(1, minsize=SPLITTER_WIDTH)
        self.home_content.grid_columnconfigure(2, weight=1)
        self.home_content.grid_rowconfigure(0, weight=1)

        self.history_panel = ctk.CTkFrame(self.home_content, corner_radius=0, fg_color=COLORS["surface"], border_width=1, border_color=COLORS["border"])
        self.history_panel.grid(row=0, column=0, sticky="nsew")
        self.history_panel.grid_columnconfigure(0, weight=1)
        self.history_panel.grid_rowconfigure(2, weight=1)

        self.history_label = ctk.CTkLabel(self.history_panel, text=self.t("history"), font=ctk.CTkFont(size=13, weight="bold"), text_color=COLORS["text"])
        self.history_label.grid(row=0, column=0, padx=16, pady=(8, 4), sticky="w")
        self.history_actions = ctk.CTkFrame(self.history_panel, fg_color="transparent")
        self.history_actions.grid(row=0, column=1, padx=12, pady=(6, 4), sticky="e")
        self.import_servers_btn = ctk.CTkButton(self.history_actions, text=self.t("import"), width=58, height=24, command=self.import_server_library, fg_color="transparent", hover_color=COLORS["surface_alt"])
        self.import_servers_btn.pack(side="left", padx=2)
        ToolTip(self.import_servers_btn, self.t("import_tooltip"))
        self.export_servers_btn = ctk.CTkButton(self.history_actions, text=self.t("export"), width=58, height=24, command=self.export_server_library, fg_color="transparent", hover_color=COLORS["surface_alt"])
        self.export_servers_btn.pack(side="left", padx=2)
        ToolTip(self.export_servers_btn, self.t("export_tooltip"))

        self.filter_var = ctk.StringVar(value=self.t("filter_all"))
        self.filter_menu = ctk.CTkOptionMenu(self.history_panel, values=[self.t("filter_all"), self.t("filter_favorites")], variable=self.filter_var, command=lambda e: self.refresh_history_ui(), width=120, fg_color=COLORS["surface_alt"], button_color=COLORS["border"], dropdown_fg_color=COLORS["surface_alt"])
        self.filter_menu.grid(row=1, column=1, padx=(4, 16), pady=(0, 6), sticky="e")

        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", self._on_search_changed)
        self.search_entry = ctk.CTkEntry(self.history_panel, placeholder_text=self.t("search_servers_placeholder"), textvariable=self.search_var, fg_color=COLORS["surface_alt"], border_color=COLORS["border"])
        self.search_entry.grid(row=1, column=0, padx=(16, 4), pady=(0, 6), sticky="ew")

        self.history_scroll = ctk.CTkScrollableFrame(self.history_panel, fg_color="transparent")
        self.history_scroll.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=8, pady=(0, 8))

        self.home_splitter = ctk.CTkFrame(self.home_content, width=SPLITTER_WIDTH, corner_radius=0, fg_color=COLORS["canvas"], cursor="sb_h_double_arrow")
        self.home_splitter.grid(row=0, column=1, sticky="ns")
        self.home_splitter.bind("<ButtonPress-1>", self._start_home_resize)
        self.home_splitter.bind("<B1-Motion>", self._resize_home_panels)
        self.home_splitter.bind("<ButtonRelease-1>", self._finish_home_resize)
        self.home_splitter.bind("<Double-Button-1>", self._reset_home_split)
        
        self.home_split_preview = ctk.CTkFrame(self.home_content, width=SPLITTER_WIDTH, corner_radius=0, fg_color=COLORS["border"], cursor="sb_h_double_arrow")


        self.connection_panel = ctk.CTkFrame(self.home_content, corner_radius=0, fg_color=COLORS["surface"], border_width=1, border_color=COLORS["border"])
        self.connection_panel.grid(row=0, column=2, sticky="nsew")
        self.connection_panel.grid_columnconfigure(0, weight=1)
        self.connection_panel.grid_rowconfigure(1, weight=1)
        self.log_title = ctk.CTkLabel(self.connection_panel, text=self.t("activity_log"), font=ctk.CTkFont(size=13, weight="bold"), text_color=COLORS["text"])
        self.log_title.grid(row=0, column=0, padx=16, pady=(8, 4), sticky="w")
        self.log_toolbar = ctk.CTkFrame(self.connection_panel, fg_color="transparent")
        self.log_toolbar.grid(row=0, column=0, padx=16, pady=(5, 3), sticky="e")
        self.auto_scroll_check = ctk.CTkCheckBox(self.log_toolbar, text=self.t("auto_scroll"), variable=self.auto_scroll, checkbox_width=14, checkbox_height=14, font=ctk.CTkFont(size=11), text_color=COLORS["muted"], fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"])
        self.auto_scroll_check.pack(side="left", padx=(0, 12))
        self.clear_log_btn = ctk.CTkButton(self.log_toolbar, text=self.t("clear"), command=self.clear_log, width=62, height=26, fg_color=COLORS["surface_alt"], hover_color=COLORS["border"], border_width=1, border_color=COLORS["border"])
        self.clear_log_btn.pack(side="left")
        self.log_frame = ctk.CTkFrame(self.connection_panel, fg_color=COLORS["surface_alt"], corner_radius=2)
        self.log_frame.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 10))
        self.log_frame.grid_columnconfigure(0, weight=1)
        self.log_frame.grid_rowconfigure(0, weight=1)

        self.log_textbox = ctk.CTkTextbox(self.log_frame, state="disabled", fg_color=COLORS["surface_alt"], text_color="#D4DAE2", font=ctk.CTkFont(family="Consolas", size=12), corner_radius=4)
        self.log_textbox.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        
        self.bottom_frame = ctk.CTkFrame(self.connection_panel, height=8, fg_color="transparent")
        self.bottom_frame.grid(row=2, column=0, padx=16, pady=(0, 6), sticky="ew")

        # ==========================================
        # 2.2 BENCHMARK FRAME
        # ==========================================
        self.bench_frame.grid_columnconfigure(0, weight=1)
        self.bench_frame.grid_rowconfigure(2, weight=1)
        self.bench_frame.bind("<Configure>", self._fit_bench_content)
        self.bench_title = ctk.CTkLabel(self.bench_frame, text=self.t("tab_bench"), font=ctk.CTkFont(size=17, weight="bold"), text_color=COLORS["text"])
        self.bench_title.grid(row=0, column=0, padx=24, pady=(18, 4), sticky="w")
        self.bench_subtitle = ctk.CTkLabel(self.bench_frame, text=self.t("bench_subtitle"), text_color=COLORS["muted"], font=ctk.CTkFont(size=13))
        self.bench_subtitle.grid(row=1, column=0, padx=24, pady=(0, 12), sticky="w")
        self.bench_content = ctk.CTkFrame(self.bench_frame, fg_color="transparent")
        self.bench_content.grid(row=2, column=0, padx=20, pady=(0, 0), sticky="nsew")
        self.bench_content.grid_propagate(False)
        self.bench_content.grid_columnconfigure(0, minsize=BENCH_CONTROLS_DEFAULT_WIDTH)
        self.bench_content.grid_columnconfigure(1, minsize=SPLITTER_WIDTH)
        self.bench_content.grid_columnconfigure(2, weight=1)
        self.bench_content.grid_rowconfigure(0, weight=1)
        self.bench_controls = ctk.CTkFrame(self.bench_content, fg_color=COLORS["surface"], corner_radius=0, border_width=1, border_color=COLORS["border"])
        self.bench_controls.grid(row=0, column=0, sticky="nsew")
        self.bench_btn = ctk.CTkButton(self.bench_controls, text=self.t("run_test"), command=self._on_run_test_click, fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"], text_color=COLORS["canvas"], height=42, font=ctk.CTkFont(weight="bold"))
        self.bench_btn.pack(fill="x", padx=16, pady=(18, 8))
        self.bench_mode_label = ctk.CTkLabel(self.bench_controls, text=self.t("hw_benchmark"), font=ctk.CTkFont(size=12, weight="bold"), text_color=COLORS["text"])
        self.bench_mode_label.pack(anchor="w", padx=16, pady=(12, 6))
        self.hardware_label = ctk.CTkLabel(self.bench_controls, text=self.t("lb_load"), justify="left", wraplength=260, text_color=COLORS["muted"], font=ctk.CTkFont(size=13))
        self.hardware_label.pack(fill="x", padx=16, pady=(0, 18))
        local_run_count = len(self.history_store.get_benchmark_runs())
        summary_text = self.t("local_results_none") if not local_run_count else self.t("local_results_fmt", count=local_run_count)
        self.benchmark_summary_label = ctk.CTkLabel(self.bench_controls, text=summary_text, justify="left", wraplength=260, text_color=COLORS["muted"], font=ctk.CTkFont(size=12))
        self.benchmark_summary_label.pack(fill="x", padx=16, pady=(0, 18))
        self.bench_splitter = ctk.CTkFrame(self.bench_content, width=SPLITTER_WIDTH, corner_radius=0, fg_color=COLORS["canvas"], cursor="sb_h_double_arrow")
        self.bench_splitter.grid(row=0, column=1, sticky="ns")
        self.bench_splitter.bind("<ButtonPress-1>", self._start_bench_resize)
        self.bench_splitter.bind("<B1-Motion>", self._resize_bench_panels)
        self.bench_splitter.bind("<ButtonRelease-1>", self._finish_bench_resize)
        self.bench_splitter.bind("<Double-Button-1>", self._reset_bench_split)
        
        self.bench_split_preview = ctk.CTkFrame(self.bench_content, width=SPLITTER_WIDTH, corner_radius=0, fg_color=COLORS["border"], cursor="sb_h_double_arrow")

        self.bench_results_panel = ctk.CTkFrame(self.bench_content, fg_color=COLORS["surface"], corner_radius=0, border_width=1, border_color=COLORS["border"])
        self.bench_results_panel.grid(row=0, column=2, sticky="nsew")
        self.bench_results_panel.grid_columnconfigure(0, weight=1)
        self.bench_results_panel.grid_rowconfigure(1, weight=1)
        self.bench_view_var = ctk.StringVar(value=self.t("tab_run_log"))
        self.bench_view_tabs = ctk.CTkSegmentedButton(
            self.bench_results_panel,
            values=[self.t("tab_run_log"), self.t("tab_online_ranking")],
            variable=self.bench_view_var,
            command=self.show_benchmark_view,
            fg_color=COLORS["surface_alt"],
            selected_color=COLORS["accent"],
            selected_hover_color=COLORS["accent_hover"],
            unselected_color=COLORS["surface_alt"],
            unselected_hover_color=COLORS["border"],
        )
        self.bench_view_tabs.grid(row=0, column=0, padx=14, pady=(12, 8), sticky="w")
        self.bench_views = ctk.CTkFrame(self.bench_results_panel, fg_color="transparent")
        self.bench_views.grid(row=1, column=0, padx=14, pady=(0, 14), sticky="nsew")
        self.bench_views.grid_rowconfigure(0, weight=1)
        self.bench_views.grid_columnconfigure(0, weight=1)
        self.bench_log = ctk.CTkTextbox(self.bench_views, state="disabled", fg_color=COLORS["surface_alt"], text_color="#D4DAE2", font=ctk.CTkFont(family="Consolas", size=12), corner_radius=2)
        self.bench_online_ranking = ctk.CTkScrollableFrame(self.bench_views, fg_color=COLORS["surface_alt"], corner_radius=2)
        for view in (self.bench_log, self.bench_online_ranking):
            view.grid(row=0, column=0, sticky="nsew")
        self.show_benchmark_view("Run log")

        # ==========================================
        # 2.3 SETTINGS FRAME
        # ==========================================
        self.settings_frame.grid_columnconfigure(1, weight=0)
        self.settings_title = ctk.CTkLabel(self.settings_frame, text=self.t("settings_title"), font=ctk.CTkFont(size=17, weight="bold"), text_color=COLORS["text"])
        self.settings_title.grid(row=0, column=0, columnspan=2, padx=24, pady=(18, 4), sticky="w")
        self.settings_subtitle = ctk.CTkLabel(self.settings_frame, text=self.t("settings_subtitle"), font=ctk.CTkFont(size=13), text_color=COLORS["muted"])
        self.settings_subtitle.grid(row=1, column=0, columnspan=2, padx=24, pady=(0, 12), sticky="w")
        self.settings_panel = ctk.CTkFrame(self.settings_frame, fg_color=COLORS["surface"], corner_radius=0, border_width=1, border_color=COLORS["border"])
        self.settings_panel.grid(row=2, column=0, columnspan=2, padx=20, pady=(0, 0), sticky="nw")
        self.settings_panel.grid_columnconfigure(1, weight=0)

        # Language
        self.lang_label = ctk.CTkLabel(self.settings_panel, text=self.t("lang_lbl"), font=ctk.CTkFont(weight="bold"))
        self.lang_label.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")
        
        self.lang_menu = ctk.CTkOptionMenu(
            self.settings_panel,
            values=list(I18nManager.LANG_MAP.values()),
            command=self.change_lang,
            width=200,
            fg_color=COLORS["surface_alt"],
            button_color=COLORS["border"],
            button_hover_color=COLORS["accent_hover"],
            dropdown_fg_color=COLORS["surface_alt"],
        )
        self.lang_menu.grid(row=0, column=1, padx=20, pady=(20, 10), sticky="w")
        self.lang_menu.set(I18nManager.LANG_MAP.get(self.history_store.get_lang(), self.history_store.get_lang()))

        # Tray Checkbox
        self.tray_var = ctk.BooleanVar(value=self.history_store.get_minimize_to_tray())
        self.tray_checkbox = ctk.CTkCheckBox(self.settings_panel, text=self.t("tray_lbl"), variable=self.tray_var, command=self._on_tray_change, fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"], border_color=COLORS["muted"])
        self.tray_checkbox.grid(row=1, column=0, columnspan=2, padx=20, pady=12, sticky="w")
        self.tray_tooltip = ToolTip(self.tray_checkbox, self.t("tooltip_tray"))

        # Swarm Checkbox
        self.swarm_var = ctk.BooleanVar(value=self.history_store.get_swarm_enabled())
        self.swarm_checkbox = ctk.CTkCheckBox(self.settings_panel, text=self.t("swarm_lbl"), variable=self.swarm_var, command=self._on_swarm_change, fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"], border_color=COLORS["muted"])
        self.swarm_checkbox.grid(row=2, column=0, columnspan=2, padx=20, pady=12, sticky="w")
        self.swarm_tooltip = ToolTip(self.swarm_checkbox, self.t("tooltip_swarm"))

        self.auto_update_settings = ctk.CTkCheckBox(
            self.settings_panel,
            text=self.t("check_rust_updates"),
            variable=self.auto_update,
            command=self.on_auto_update_change,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            border_color=COLORS["muted"],
        )
        self.auto_update_settings.grid(row=3, column=0, columnspan=2, padx=20, pady=12, sticky="w")
        
        # Auto-Arm Checkbox
        self.auto_arm_var = ctk.BooleanVar(value=self.history_store.get_auto_arm())
        self.auto_arm_checkbox = ctk.CTkCheckBox(
            self.settings_panel,
            text=self.t("auto_arm_lbl"),
            variable=self.auto_arm_var,
            command=self._on_auto_arm_change,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            border_color=COLORS["muted"],
        )
        self.auto_arm_checkbox.grid(row=4, column=0, columnspan=2, padx=20, pady=12, sticky="w")

        # Telegram Bot Linking
        self.tg_frame = ctk.CTkFrame(self.settings_panel, fg_color="transparent")
        self.tg_frame.grid(row=5, column=0, columnspan=2, padx=20, pady=12, sticky="w")
        code_txt = f"Code: {telegram_service.link_code}" if telegram_service.link_code else self.t("tg_status_unlinked")
        self.tg_status_lbl = ctk.CTkLabel(self.tg_frame, text=code_txt, text_color=COLORS["muted"])
        self.tg_status_lbl.pack(side="left", padx=(0, 10))
        self.tg_link_btn = ctk.CTkButton(
            self.tg_frame,
            text=self.t("tg_link_btn"),
            command=self._on_tg_link_click,
            width=120,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"]
        )
        self.tg_link_btn.pack(side="left")

        # Start by showing Home
        self.refresh_history_ui()
        self._refresh_session_state()
        self.show_home_frame()

    def _nav_button(self, text, command, icon_name):
        return ctk.CTkButton(
            self.sidebar_frame, text=text, image=self._icon_images[f"{icon_name}_muted"], compound="left", command=command, anchor="w", height=44, border_spacing=10,
            corner_radius=0, fg_color="transparent", hover_color=COLORS["surface_alt"],
            text_color=COLORS["muted"],
        )

    def _fit_home_content(self, event):
        """Keep the workspace within the actual available window width."""
        content_width = max(0, event.width)
        if content_width == self._last_home_workspace_width:
            return
        self._last_home_workspace_width = content_width
        if self._home_drag_origin_x is None:
            self._apply_home_split(content_width)

    def _apply_home_split(self, workspace_width: int) -> None:
        effective_width = self._clamp_home_split(self._history_width, workspace_width)
        if effective_width == self._applied_history_width:
            return
        self._applied_history_width = effective_width
        self.home_content.grid_columnconfigure(0, minsize=effective_width)

    @staticmethod
    def _home_split_limits(workspace_width: int) -> tuple[int, int]:
        history_min = min(HOME_HISTORY_MIN_WIDTH, max(220, workspace_width - SPLITTER_WIDTH - HOME_LOG_MIN_WIDTH))
        log_min = min(HOME_LOG_MIN_WIDTH, max(220, workspace_width - SPLITTER_WIDTH - history_min))
        history_max = max(history_min, workspace_width - SPLITTER_WIDTH - log_min)
        return history_min, history_max

    def _clamp_home_split(self, requested_width: int, workspace_width: int) -> int:
        minimum, maximum = self._home_split_limits(workspace_width)
        return max(minimum, min(requested_width, maximum))

    def _start_home_resize(self, event) -> None:
        self._home_drag_origin_x = event.x_root
        self._home_drag_origin_width = max(1, self.history_panel.winfo_width())
        self._pending_home_width = self._applied_history_width or self._clamp_home_split(self._history_width, self.home_content.winfo_width())
        self.home_splitter.configure(fg_color="transparent")
        self.home_split_preview.place(x=self._pending_home_width, y=0, relheight=1)
        self.home_split_preview.lift()

    def _resize_home_panels(self, event) -> None:
        if self._home_drag_origin_x is None or self._home_drag_origin_width is None:
            return
        requested_width = self._home_drag_origin_width + (event.x_root - self._home_drag_origin_x)
        self._pending_home_width = self._clamp_home_split(requested_width, self.home_content.winfo_width())
        self.home_split_preview.place(x=self._pending_home_width, y=0, relheight=1)

    def _finish_home_resize(self, _event) -> None:
        if getattr(self, "_pending_home_width", None) is not None:
            self._history_width = self._pending_home_width
            self._apply_home_split(self.home_content.winfo_width())
            self.history_store.set_home_splitter_width(self._history_width)
            
        self._home_drag_origin_x = None
        self._home_drag_origin_width = None
        self._pending_home_width = None
        
        self.home_split_preview.place_forget()
        self.home_splitter.configure(fg_color=COLORS["canvas"])

    def _reset_home_split(self, _event) -> None:
        self._history_width = HOME_HISTORY_DEFAULT_WIDTH
        self._apply_home_split(self.home_content.winfo_width())
        self.history_store.set_home_splitter_width(self._history_width)

    def _fit_bench_content(self, event) -> None:
        width = max(0, event.width - 40)
        if width == self._last_bench_workspace_width:
            return
        self._last_bench_workspace_width = width
        if self._bench_drag_origin_x is None:
            self._apply_bench_split(width)

    def _apply_bench_split(self, workspace_width: int) -> None:
        effective_width = self._clamp_bench_split(self._bench_controls_width, workspace_width)
        if effective_width == self._applied_bench_controls_width:
            return
        self._applied_bench_controls_width = effective_width
        self.bench_content.grid_columnconfigure(0, minsize=effective_width)

    @staticmethod
    def _bench_split_limits(workspace_width: int) -> tuple[int, int]:
        controls_min = min(BENCH_CONTROLS_MIN_WIDTH, max(180, workspace_width - SPLITTER_WIDTH - BENCH_LOG_MIN_WIDTH))
        log_min = min(BENCH_LOG_MIN_WIDTH, max(220, workspace_width - SPLITTER_WIDTH - controls_min))
        controls_max = max(controls_min, workspace_width - SPLITTER_WIDTH - log_min)
        return controls_min, controls_max

    def _clamp_bench_split(self, requested_width: int, workspace_width: int) -> int:
        minimum, maximum = self._bench_split_limits(workspace_width)
        return max(minimum, min(requested_width, maximum))

    def _start_bench_resize(self, event) -> None:
        self._bench_drag_origin_x = event.x_root
        self._bench_drag_origin_width = max(1, self.bench_controls.winfo_width())
        self._pending_bench_width = self._applied_bench_controls_width or self._clamp_bench_split(self._bench_controls_width, self.bench_content.winfo_width())
        self.bench_splitter.configure(fg_color="transparent")
        self.bench_split_preview.place(x=self._pending_bench_width, y=0, relheight=1)
        self.bench_split_preview.lift()

    def _resize_bench_panels(self, event) -> None:
        if self._bench_drag_origin_x is None or self._bench_drag_origin_width is None:
            return
        requested_width = self._bench_drag_origin_width + (event.x_root - self._bench_drag_origin_x)
        self._pending_bench_width = self._clamp_bench_split(requested_width, self.bench_content.winfo_width())
        self.bench_split_preview.place(x=self._pending_bench_width, y=0, relheight=1)

    def _finish_bench_resize(self, _event) -> None:
        if getattr(self, "_pending_bench_width", None) is not None:
            self._bench_controls_width = self._pending_bench_width
            self._apply_bench_split(self.bench_content.winfo_width())
            self.history_store.set_bench_splitter_width(self._bench_controls_width)
            
        self._bench_drag_origin_x = None
        self._bench_drag_origin_width = None
        self._pending_bench_width = None
        
        self.bench_split_preview.place_forget()
        self.bench_splitter.configure(fg_color=COLORS["canvas"])

    def _reset_bench_split(self, _event) -> None:
        self._bench_controls_width = BENCH_CONTROLS_DEFAULT_WIDTH
        self._apply_bench_split(self.bench_content.winfo_width())
        self.history_store.set_bench_splitter_width(self._bench_controls_width)



    def _status_item(self, label, value, column):
        container = ctk.CTkFrame(self.status_strip, fg_color="transparent")
        container.grid(row=0, column=column, padx=16, pady=12, sticky="ew")
        ctk.CTkLabel(container, text=label, font=ctk.CTkFont(size=10, weight="bold"), text_color=COLORS["muted"]).pack(anchor="w")
        ctk.CTkLabel(container, textvariable=value, font=ctk.CTkFont(size=13, weight="bold"), text_color=COLORS["text"]).pack(anchor="w", pady=(3, 0))

    def _refresh_session_state(self):
        elapsed = 0 if self.rust_playtime_started_at is None else int(time.monotonic() - self.rust_playtime_started_at)
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        self.playtime_var.set(f"{hours:02}:{minutes:02}:{seconds:02}")
        self._refresh_session_state_once()
        self._session_state_after_id = self.after(1000, self._refresh_session_state)

    def _refresh_session_state_once(self):
        armed = self.history_store.get_armed_server()
        if armed:
            self.footer_armed_label.configure(text=self.t("reconnect_armed"), text_color=COLORS["accent"])
            self.disarm_btn.configure(state="normal")
        else:
            self.footer_armed_label.configure(text=self.t("reconnect_disarmed"), text_color=COLORS["muted"])
            self.disarm_btn.configure(state="disabled")

    def set_connection_state(self, state: str, target: Optional[str] = None):
        state_map = {
            "Idle": self.t("idle"),
            "Monitoring": self.t("monitoring_status"),
            "Launching": self.t("launching"),
            "Connected": self.t("rust_running"),
            "Launch failed": self.t("launch_failed"),
        }
        display_state = state_map.get(state, self.t(state))
        self.session_status_var.set(display_state)
        self._pulse_status(self.session_status_label, COLORS["accent"] if state != "Idle" else COLORS["text"])
        if target:
            display_target = target if len(target) <= 42 else f"{target[:20]}…{target[-18:]}"
            self.last_connected_var.set(display_target)
            self.last_connected_tooltip.text = target

    def set_rust_status(self, is_running: bool) -> None:
        if is_running and self.rust_playtime_started_at is None:
            self.rust_playtime_started_at = time.monotonic()
        elif not is_running:
            self.rust_playtime_started_at = None
            self.playtime_var.set("00:00:00")
        color = "#2ECC71" if is_running else COLORS["danger"]
        self.rust_status_label.configure(text="Rust", text_color=color)
        self.rust_status_tooltip.text = self.t("rust_running") if is_running else self.t("rust_not_running")
        self._pulse_status(self.rust_status_label, color, rest_color=color)

    def set_version_status(self, version: str, status: str, color: str) -> None:
        self.version_label.configure(text=self.t("version_fmt", version=version))
        display_status = self.t(status) if status in ("Checking...", "Offline", "Latest") else status
        self.version_state_label.configure(text=display_status, text_color=color)

    def update_benchmark_summary(self, run: dict):
        if not hasattr(self, "benchmark_summary_label"):
            return
        run_count = len(self.history_store.get_benchmark_runs(run.get("configuration_key", "")))
        self.benchmark_summary_label.configure(
            text=self.t("current_config_summary", time=run.get('total_time', 0), count=run_count)
        )

    # --- NAVIGATION LOGIC ---
    def show_home_frame(self):
        self._cancel_split_drags()
        self.home_frame.tkraise()
        self._highlight_nav(self.nav_home_btn)

    def show_bench_frame(self):
        self._cancel_split_drags()
        self.bench_frame.tkraise()
        self._highlight_nav(self.nav_bench_btn)

    def show_settings_frame(self):
        self._cancel_split_drags()
        self.settings_frame.tkraise()
        self._highlight_nav(self.nav_settings_btn)

    def _cancel_split_drags(self) -> None:
        self._home_drag_origin_x = None
        self._home_drag_origin_width = None
        self._bench_drag_origin_x = None
        self._bench_drag_origin_width = None
        self._pending_home_width = None
        self._pending_bench_width = None
        self.home_splitter.configure(fg_color=COLORS["canvas"])
        self.bench_splitter.configure(fg_color=COLORS["canvas"])
        if hasattr(self, "home_split_preview"):
            self.home_split_preview.place_forget()
        if hasattr(self, "bench_split_preview"):
            self.bench_split_preview.place_forget()
        
    def _highlight_nav(self, active_btn):
        # Reset all
        for button in (self.nav_home_btn, self.nav_bench_btn, self.nav_settings_btn):
            icon_name = self._nav_icon_names[button]
            button.configure(fg_color="transparent", text_color=COLORS["muted"], image=self._icon_images[f"{icon_name}_muted"])
        # Highlight active
        active_icon = self._nav_icon_names[active_btn]
        active_btn.configure(fg_color="#252525", text_color=COLORS["text"], image=self._icon_images[f"{active_icon}_active"])
        self.after_idle(lambda: self._animate_nav_marker(active_btn))

    def _animate_nav_marker(self, active_btn) -> None:
        target_y = active_btn.winfo_y()
        target_height = active_btn.winfo_height()
        if target_height <= 1:
            return
        if self._nav_marker_after_id is not None:
            self.after_cancel(self._nav_marker_after_id)
        start_y = self.nav_active_marker.winfo_y()
        self.nav_active_marker.grid_forget()
        self.nav_active_marker.place(x=3, y=start_y)
        self.nav_active_marker.lift()
        steps = 12

        def tick(step: int = 0) -> None:
            if not self.winfo_exists():
                return
            progress = step / steps
            eased = 1 - (1 - progress) ** 3
            self.nav_active_marker.place_configure(y=round(start_y + (target_y - start_y) * eased))
            if step < steps:
                self._nav_marker_after_id = self.after(16, tick, step + 1)
            else:
                self._nav_marker_after_id = None

        tick()

    def _pulse_status(self, label, color: str, rest_color: Optional[str] = None) -> None:
        if self._status_pulse_after_id is not None:
            self.after_cancel(self._status_pulse_after_id)
        label.configure(text_color=color)
        def _reset_color():
            if self.winfo_exists() and label.winfo_exists():
                label.configure(text_color=rest_color or COLORS["text"])
        self._status_pulse_after_id = self.after(220, _reset_color)

    # --- SETTINGS LOGIC ---
    def _on_tray_change(self):
        self.history_store.set_minimize_to_tray(self.tray_var.get())

    def _on_auto_arm_change(self):
        self.history_store.set_auto_arm(self.auto_arm_var.get())

    def _on_tg_link_click(self):
        import random
        from tkinter import messagebox
        code = f"{random.randint(1000, 9999)}"
        messagebox.showinfo(self.t("tg_bot_title"), self.t("tg_bot_msg", code=code), parent=self)

    def dispatch_ui(self, callback, *args, **kwargs):
        if getattr(self, "_ui_dispatch_closing", False):
            return
        if threading.current_thread() is threading.main_thread():
            try:
                if self.winfo_exists():
                    callback(*args, **kwargs)
            except Exception as error:
                from ..core.logger import app_logger
                app_logger.warning(f"UI callback failed: {type(error).__name__}")
            return
        self._ui_callback_queue.put((callback, args, kwargs))

    def _dispatch_ui(self, callback, *args, **kwargs):
        dispatcher = getattr(self, "dispatch_ui", None)
        if callable(dispatcher) and getattr(dispatcher, "__func__", None) != MainWindow.dispatch_ui:
            dispatcher(callback, *args, **kwargs)
            return
        self.dispatch_ui(callback, *args, **kwargs)

    def _drain_ui_callbacks(self) -> None:
        while not getattr(self, "_ui_dispatch_closing", False) and self.winfo_exists():
            try:
                callback, args, kwargs = self._ui_callback_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback(*args, **kwargs)
            except Exception:
                continue
        if not getattr(self, "_ui_dispatch_closing", False) and self.winfo_exists():
            self._ui_dispatch_after_id = self.after(25, self._drain_ui_callbacks)

    def _on_swarm_change(self):
        from ..services.swarm_service import swarm_service
        is_checked = self.swarm_var.get()
        
        if is_checked:
            if not swarm_service.is_configured:
                import tkinter.messagebox as messagebox
                self.history_store.set_swarm_enabled(False)
                self.swarm_var.set(False)
                swarm_service.is_enabled = False
                swarm_service._notify_status(swarm_service.configuration_status)
                detail = (
                    self.t("swarm_invalid_key_msg")
                    if swarm_service.configuration_status == "invalid_key"
                    else self.t("swarm_not_configured_msg")
                )
                messagebox.showerror(self.t("swarm_config_title"), detail, parent=self)
                return
            self.history_store.set_swarm_enabled(True)
            swarm_service.is_enabled = True
            swarm_service.start()
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
        self.topbar_subtitle.configure(text=self.t("command_center"))
        self.home_header.configure(text=self.t("connect_to_server"))
        self.address_label.configure(text=self.t("server_address"))
        if not self.history_store.get_armed_server():
            self.footer_armed_label.configure(text=self.t("reconnect_disarmed"))
        else:
            self.footer_armed_label.configure(text=self.t("reconnect_armed"))
        self.disarm_btn.configure(text=self.t("disarm"))
        self.history_label.configure(text=self.t("server_history"))
        self.import_servers_btn.configure(text=self.t("import"))
        self.export_servers_btn.configure(text=self.t("export"))
        self.filter_menu.configure(values=[self.t("filter_all"), self.t("filter_favorites")])
        self.search_entry.configure(placeholder_text=self.t("search_servers_placeholder"))
        self.log_title.configure(text=self.t("activity_log"))
        self.auto_scroll_check.configure(text=self.t("auto_scroll"))
        self.clear_log_btn.configure(text=self.t("clear"))
        self.nav_home_btn.configure(text=self.t("nav_home"))
        self.nav_bench_btn.configure(text=self.t("nav_bench"))
        self.nav_settings_btn.configure(text=self.t("nav_settings"))
        self.bench_title.configure(text=self.t("tab_bench"))
        self.bench_subtitle.configure(text=self.t("bench_subtitle"))
        self.bench_mode_label.configure(text=self.t("hw_benchmark"))
        self.bench_view_tabs.configure(values=[self.t("tab_run_log"), self.t("tab_online_ranking")])
        self.bench_btn.configure(text=self.t("run_test"))
        self.settings_title.configure(text=self.t("settings_title"))
        self.settings_subtitle.configure(text=self.t("settings_subtitle"))
        self.lang_label.configure(text=self.t("lang_lbl"))
        self.tray_checkbox.configure(text=self.t("tray_lbl"))
        self.swarm_checkbox.configure(text=self.t("swarm_lbl"))
        self.auto_update_settings.configure(text=self.t("check_rust_updates"))
        self.auto_arm_checkbox.configure(text=self.t("auto_arm_lbl"))
        self.tg_status_lbl.configure(text=self.t("tg_status_unlinked"))
        self.tg_link_btn.configure(text=self.t("tg_link_btn"))
        if hasattr(self, "connect_btn"):
            self.connect_btn.configure(text=self.t("connect"))
        
        if hasattr(self, 'tray_tooltip'):
            self.tray_tooltip.text = self.t("tooltip_tray")
        if hasattr(self, 'swarm_tooltip'):
            self.swarm_tooltip.text = self.t("tooltip_swarm")

        self.refresh_history_ui()

    # --- OTHER METHODS ---
    def t(self, key: str, **kwargs) -> str:
        i18n_mgr = self.__dict__.get("i18n")
        if i18n_mgr is not None:
            return i18n_mgr.t(key, **kwargs)
        from ..core.i18n import i18n
        return i18n.t(key, **kwargs)

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

    def show_benchmark_view(self, view_name: str) -> None:
        if self.bench_view_var.get() != view_name:
            self.bench_view_var.set(view_name)
        views = {
            self.t("tab_run_log"): self.bench_log,
            "Run log": self.bench_log,
            self.t("tab_online_ranking"): self.bench_online_ranking,
            "Online ranking": self.bench_online_ranking,
        }
        view = views.get(view_name, self.bench_log)
        view.tkraise()
        if view_name in (self.t("tab_online_ranking"), "Online ranking"):
            self._load_online_benchmark_ranking()

    def _clear_benchmark_view(self, view) -> None:
        for widget in view.winfo_children():
            widget.destroy()

    def _load_online_benchmark_ranking(self) -> None:
        self._clear_benchmark_view(self.bench_online_ranking)
        loading = ctk.CTkLabel(self.bench_online_ranking, text=self.t("lb_load"), text_color=COLORS["muted"])
        loading.pack(anchor="w", padx=12, pady=12)

        def load() -> None:
            from ..services.leaderboard_service import leaderboard_service
            rows = leaderboard_service.fetch_configurations(limit=50)
            error = leaderboard_service.last_error
            self._dispatch_ui(self._render_online_benchmark_ranking, rows, error)

        threading.Thread(target=load, daemon=True, name="benchmark-ranking").start()

    def _render_online_benchmark_ranking(self, rows, error: Optional[str]) -> None:
        if self.bench_view_var.get() not in (self.t("tab_online_ranking"), "Online ranking", "Ranking"):
            return
        self._clear_benchmark_view(self.bench_online_ranking)
        if error:
            ctk.CTkLabel(self.bench_online_ranking, text=self.t("ranking_unavailable_fmt", err=error), text_color=COLORS["muted"]).pack(anchor="w", padx=12, pady=12)
            return
        if not rows:
            ctk.CTkLabel(self.bench_online_ranking, text=self.t("no_bench_results_yet"), text_color=COLORS["muted"]).pack(anchor="w", padx=12, pady=12)
            return
        for index, row_data in enumerate(rows, start=1):
            total = row_data.get("best_total_time") or row_data.get("total_time")
            score = f"{total:.1f}s" if isinstance(total, (int, float)) else "-"
            row = ctk.CTkFrame(self.bench_online_ranking, fg_color="transparent", corner_radius=0)
            row.pack(fill="x", padx=10, pady=3)
            ctk.CTkLabel(row, text=f"{index}. {row_data.get('cpu', 'Unknown CPU')}", anchor="w", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(row, text=score, text_color=COLORS["accent"], font=ctk.CTkFont(size=12, weight="bold")).pack(side="right")
            ctk.CTkLabel(self.bench_online_ranking, text=str(row_data.get("storage", "Unknown storage")), anchor="w", font=ctk.CTkFont(size=11), text_color=COLORS["muted"]).pack(fill="x", padx=10)


    def set_address(self, value: str) -> None:
        state = self.ip_entry.cget("state")
        self.ip_entry.configure(state="normal")
        self.ip_entry.delete(0, "end")
        self.ip_entry.insert(0, value)
        self.ip_entry.configure(state=state)

    def refresh_history_ui(self):
        for widget in self.history_scroll.winfo_children():
            widget.destroy()

        show_favs_only = (self.filter_var.get() in (self.t("filter_favorites"), "Favorites"))
        search_query = self.search_var.get().lower().strip()

        history_items = self.history_store.get_history()
        history_items = sorted(history_items, key=lambda x: x.get("added_at", 0), reverse=True)
        favorites = self.history_store.get_favorites()

        visible_items = []
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

            visible_items.append((item, is_fav))

        # Keep favorites at the top, followed by regular recent servers.
        visible_items.sort(key=lambda entry: (not entry[1], -entry[0].get("added_at", 0)))
        section = None
        for item, is_fav in visible_items:
            ip = item['ip']
            display_name = item.get('name', 'Rust Server')
            is_armed = (self.history_store.get_armed_server() == ip)

            next_section = self.t("sec_favorites") if is_fav else self.t("sec_recent")
            if next_section != section:
                section = next_section
                ctk.CTkLabel(
                    self.history_scroll,
                    text=section,
                    anchor="w",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color=COLORS["accent"] if is_fav else COLORS["muted"],
                ).pack(fill="x", padx=10, pady=(10, 5), anchor="w")

            frame = ctk.CTkFrame(self.history_scroll, height=52, corner_radius=0, fg_color="transparent")
            frame.pack(fill="x", padx=4, pady=1)
            frame.grid_propagate(False)
            frame.grid_columnconfigure(1, weight=1)

            fav_btn = ctk.CTkButton(
                frame,
                text="",
                image=self._icon_images["favorite"] if is_fav else self._icon_images["favorite_off"],
                width=34,
                height=34,
                corner_radius=0,
                fg_color="transparent",
                hover_color=COLORS["surface_alt"],
                command=lambda i=ip, n=display_name: self.toggle_favorite(i, n),
            )
            fav_btn.grid(row=0, column=0, padx=(0, 5), pady=8)
            ToolTip(fav_btn, self.t("toggle_fav_tooltip"))

            text_frame = ctk.CTkFrame(frame, fg_color="transparent")
            text_frame.grid(row=0, column=1, sticky="ew", pady=5)
            title = ctk.CTkLabel(text_frame, text=display_name[:38], anchor="w", font=ctk.CTkFont(size=14), text_color=COLORS["text"])
            title.pack(fill="x", anchor="w")
            endpoint = ctk.CTkLabel(text_frame, text=f"client.connect {ip}", anchor="w", font=ctk.CTkFont(size=11), text_color=COLORS["muted"])
            endpoint.pack(fill="x", anchor="w")
            for widget in (text_frame, title, endpoint):
                widget.bind("<Button-1>", lambda event, i=ip: self.select_history(i))
                widget.bind("<Double-Button-1>", lambda event, i=ip: self.edit_server_metadata(i))

            arm_btn = ctk.CTkButton(
                frame,
                text="",
                image=self._icon_images["armed"] if is_armed else self._icon_images["disarmed"],
                width=34,
                height=34,
                corner_radius=0,
                fg_color="transparent",
                hover_color=COLORS["surface_alt"],
                command=lambda i=ip: self.toggle_armed(i),
            )
            arm_btn.grid(row=0, column=2, padx=2, pady=8)
            ToolTip(arm_btn, self.t("disarm_tooltip") if is_armed else self.t("arm_tooltip"))

            go_btn = ctk.CTkButton(
                frame,
                text="",
                image=self._icon_images["connect"],
                width=34,
                height=34,
                corner_radius=2,
                fg_color=COLORS["surface_alt"],
                hover_color="#303030",
                border_width=1,
                border_color=COLORS["border"],
                command=lambda i=ip: self._connect_history_server(i),
            )
            go_btn.grid(row=0, column=3, padx=(3, 0), pady=8)
            ToolTip(go_btn, self.t("connect_tooltip"))
            ctk.CTkFrame(self.history_scroll, height=1, corner_radius=0, fg_color="#2A2A2A").pack(fill="x", padx=8)
            
    def toggle_armed(self, ip_port: str):
        import tkinter.messagebox as messagebox
        is_currently_armed = (self.history_store.get_armed_server() == ip_port)
        if not is_currently_armed:
            msg = self.t("arm_warning_msg")
            if not messagebox.askyesno(self.t("arm_warning_title"), msg, parent=self):
                return
                
        self.history_store.set_armed_server(ip_port)
        self.refresh_history_ui()
        # Ensure the armed server also gets selected in the combo box
        if self.history_store.get_armed_server() == ip_port:
            self.select_history(ip_port)
        self._refresh_session_state_once()

    def disarm_server(self):
        armed = self.history_store.get_armed_server()
        if not armed:
            return
        self.history_store.set_armed_server(armed)
        self.refresh_history_ui()
        self._refresh_session_state_once()

    def toggle_favorite(self, ip_port: str, name: str):
        self.history_store.toggle_favorite(ip_port, name)
        self.refresh_history_ui()

    def edit_server_metadata(self, ip_port: str):
        item = next((entry for entry in self.history_store.get_history() if entry.get("ip") == ip_port), None)
        if not item:
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title(self.t("server_details"))
        dialog.geometry("460x270")
        dialog.configure(fg_color=COLORS["canvas"])
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text=item.get("name", ip_port), font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=20, pady=(20, 8))
        tags_entry = ctk.CTkEntry(dialog, placeholder_text=self.t("tags_placeholder"), fg_color=COLORS["surface_alt"])
        tags_entry.insert(0, ", ".join(item.get("tags", [])))
        tags_entry.pack(fill="x", padx=20, pady=6)
        note_box = ctk.CTkTextbox(dialog, height=95, fg_color=COLORS["surface_alt"])
        note_box.insert("1.0", item.get("note", ""))
        note_box.pack(fill="both", expand=True, padx=20, pady=6)

        def save_metadata():
            tags = tags_entry.get().split(",")
            self.history_store.update_server_metadata(ip_port, tags, note_box.get("1.0", "end-1c"))
            dialog.destroy()
            self.refresh_history_ui()

        ctk.CTkButton(dialog, text=self.t("save"), command=save_metadata, fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"], text_color=COLORS["canvas"]).pack(anchor="e", padx=20, pady=(4, 20))

    def export_server_library(self):
        from tkinter import filedialog, messagebox
        import json

        destination = filedialog.asksaveasfilename(
            parent=self,
            title=self.t("export_lib_title"),
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
        )
        if not destination:
            return
        try:
            with open(destination, "w", encoding="utf-8") as file:
                json.dump(self.history_store.export_server_library(), file, ensure_ascii=False, indent=2)
            messagebox.showinfo(self.t("export_complete"), self.t("export_complete_msg"), parent=self)
        except OSError as error:
            messagebox.showerror(self.t("export_failed"), self.t("export_failed_msg", err=type(error).__name__), parent=self)

    def import_server_library(self):
        from tkinter import filedialog, messagebox
        import json

        source = filedialog.askopenfilename(parent=self, title=self.t("import_lib_title"), filetypes=[("JSON files", "*.json")])
        if not source:
            return
        try:
            with open(source, "r", encoding="utf-8") as file:
                payload = json.load(file)
            added, updated = self.history_store.import_server_library(payload)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            messagebox.showerror(self.t("import_failed"), self.t("import_failed_msg", err=type(error).__name__), parent=self)
            return
        self.refresh_history_ui()
        messagebox.showinfo(self.t("import_complete"), self.t("import_complete_msg", added=added, updated=updated), parent=self)

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
                
                current_text = self.ip_entry.get()
                if current_text.endswith(f"({ip})"):
                    self.set_address(f"{new_name} ({ip})")
                    
            self.refresh_history_ui()

        entry.bind("<Return>", save_inline)
        entry.bind("<FocusOut>", save_inline)
        if hasattr(entry, "_entry"):
            entry._entry.bind("<Return>", save_inline)
            entry._entry.bind("<FocusOut>", save_inline)
        return save_inline

    def select_history(self, ip_port: str):
        self.set_address(ip_port)

    def _connect_history_server(self, ip_port: str):
        self.select_history(ip_port)
        self._on_connect_btn_click()

    def get_target_ip(self) -> str:
        target = self.ip_entry.get().strip()
        if "(" in target and ")" in target:
            target = target.split("(")[-1].replace(")", "").strip()
        if target.lower().startswith("client.connect "):
            target = target.split(None, 1)[1].strip()
        return target

    def update_entry(self, text: str):
        self.set_address(text)

    def log(self, msg: str, color: Optional[str] = None):
        from ..core.logger import app_logger
        app_logger.info(msg)
        ts = time.strftime("[%H:%M:%S]")
        self.log_textbox.configure(state="normal")
        
        # Insert time timestamp normally
        self.log_textbox.insert("end", f"{ts} ")
        
        if color:
            tag_name = f"color_{color.replace('#', '')}"
            self.log_textbox.tag_config(tag_name, foreground=color)
            self.log_textbox.insert("end", f"{msg}\n", tag_name)
        else:
            self.log_textbox.insert("end", f"{msg}\n")
            
        lines = int(self.log_textbox.index('end-1c').split('.')[0])
        if lines > 500:
            self.log_textbox.delete('1.0', f'{lines - 500 + 1}.0')
        if self.auto_scroll.get():
            self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def clear_log(self):
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")

    def log_safe(self, msg: str, color: Optional[str] = None):
        self.dispatch_ui(self.log, msg, color=color)

    def create_tray_image(self):
        image = Image.new('RGB', (64, 64), color=(59, 142, 208))
        d = ImageDraw.Draw(image)
        d.text((24, 24), "R", fill=(255, 255, 255))
        return image

    def on_unmap(self, event):
        if event.widget == self and self.state() == 'iconic':
            if self.history_store.get_minimize_to_tray():
                self.withdraw_window()

    def _on_close_requested(self):
        if self.history_store.get_minimize_to_tray():
            self.withdraw_window()
        else:
            self.shutdown()

    def withdraw_window(self):
        self.withdraw()
        if not self.tray_icon:
            image = self.create_tray_image()
            menu = pystray.Menu(
                pystray.MenuItem(self.t("tray_show"), self.show_window, default=True),
                pystray.MenuItem(self.t("tray_quit"), self.quit_window)
            )
            self.tray_icon = pystray.Icon("RustAutoConnect", image, "Rust AutoConnect", menu)
            self.tray_icon.run_detached()

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
        self._ui_dispatch_closing = True
        if self._ui_dispatch_after_id is not None:
            self.after_cancel(self._ui_dispatch_after_id)
        if self._search_timer is not None:
            self.after_cancel(self._search_timer)
        if hasattr(self, "_session_state_after_id"):
            self.after_cancel(self._session_state_after_id)
        if getattr(self, "_nav_marker_after_id", None) is not None:
            self.after_cancel(self._nav_marker_after_id)
            self._nav_marker_after_id = None
        if getattr(self, "_status_pulse_after_id", None) is not None:
            self.after_cancel(self._status_pulse_after_id)
            self._status_pulse_after_id = None
        try:
            self.destroy()
        except Exception:
            pass



