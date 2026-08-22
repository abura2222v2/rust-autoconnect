# -*- coding: utf-8 -*-
import os
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from src.core.config import config
from src.core.history_store import HistoryStore, DEFAULT_DATA
from src.gui.main_window import MainWindow, DEFAULT_COL_WIDTHS, MIN_WIDTHS, COLORS


def test_column_widths_default_and_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    store = HistoryStore()

    # Verify default column widths
    widths = store.get_column_widths()
    assert widths == DEFAULT_COL_WIDTHS

    # Test updating column widths
    new_widths = {"name": 320, "addr": 220, "players": 80}
    store.set_column_widths(new_widths)

    saved_widths = store.get_column_widths()
    assert saved_widths["name"] == 320
    assert saved_widths["addr"] == 220
    assert saved_widths["players"] == 80
    assert saved_widths["star"] == 32  # preserved default

    # Reload store from disk
    store_reloaded = HistoryStore()
    assert store_reloaded.get_column_widths()["name"] == 320


def test_main_window_column_resize_logic():
    win = object.__new__(MainWindow)
    win.col_widths = dict(DEFAULT_COL_WIDTHS)
    win.header_cells = {
        "star": MagicMock(),
        "name": MagicMock(),
        "addr": MagicMock(),
        "players": MagicMock(),
        "local": MagicMock(),
        "action": MagicMock(),
    }
    
    mock_title_lbl = MagicMock()
    mock_row_cell = MagicMock()
    win.registered_row_cells = [
        {
            "cells": {"name": mock_row_cell},
            "title_label": mock_title_lbl,
            "full_name": "Rustafied.com - EU Small Friday Server Very Long Name",
        }
    ]
    win.history_store = MagicMock()

    # Apply column widths
    win.col_widths["name"] = 350
    MainWindow.apply_column_widths(win)
    win.header_cells["name"].configure.assert_called_with(width=350)
    mock_row_cell.configure.assert_called_with(width=350)

    # Auto-fit column
    MainWindow.auto_fit_column(win, "name")
    assert win.col_widths["name"] >= MIN_WIDTHS["name"]
    assert win.history_store.set_column_widths.called


def test_drawer_time_based_animation_and_cancellation():
    win = object.__new__(MainWindow)
    win._drawer_animation_id = 999
    win._log_drawer_visible = False
    win._drawer_progress = 0.0
    win.after_cancel = MagicMock()
    win.after = MagicMock(return_value=1001)
    win.connection_panel = MagicMock()
    win.overlay_backdrop = MagicMock()

    MainWindow.cancel_drawer_animation(win)
    win.after_cancel.assert_called_with(999)
    assert win._drawer_animation_id is None

    # Test toggling without animation
    MainWindow._set_activity_log_visible(win, visible=True, animate=False)
    assert win._log_drawer_visible is True
    assert win.connection_panel.place.called

    MainWindow._set_activity_log_visible(win, visible=False, animate=False)
    assert win._log_drawer_visible is False
    assert win.connection_panel.place_forget.called


def test_rust_status_three_states():
    win = object.__new__(MainWindow)
    win.lang = "RU"
    win._cached_rust_status = None
    win.rust_playtime_started_at = None
    win.playtime_var = MagicMock()
    win.rust_status_dot = MagicMock()
    win.rust_status_label = MagicMock()
    win.rust_status_tooltip = MagicMock()
    win.t = lambda k: k

    # 1. Stopped state
    MainWindow.set_rust_status(win, False)
    win.rust_status_dot.configure.assert_called_with(text_color=COLORS["muted"])
    assert "не запущен" in win.rust_status_label.configure.call_args[1]["text"]

    # 2. Starting state
    win._cached_rust_status = None
    MainWindow.set_rust_status(win, "starting")
    win.rust_status_dot.configure.assert_called_with(text_color=COLORS["warning"])
    assert "запуск" in win.rust_status_label.configure.call_args[1]["text"]

    # 3. Running state
    win._cached_rust_status = None
    MainWindow.set_rust_status(win, True)
    win.rust_status_dot.configure.assert_called_with(text_color=COLORS["success"])
    assert "запущен" in win.rust_status_label.configure.call_args[1]["text"]

    # 4. String stopped state
    win._cached_rust_status = None
    MainWindow.set_rust_status(win, "stopped")
    assert win.rust_status_label.configure.called


def test_ghost_guide_line_and_badge():
    win = object.__new__(MainWindow)
    win.col_widths = dict(DEFAULT_COL_WIDTHS)
    win._ghost_guide_frame = MagicMock()
    win._ghost_badge = MagicMock()
    win.history_store = MagicMock()
    win.header_cells = {"name": MagicMock()}
    win.registered_row_cells = []

    # Simulate release after drag
    win._drag_col_target = "name"
    win._drag_threshold_passed = True
    win._drag_current_width = 310

    # Test release behavior
    win._ghost_guide_frame.place_forget()
    win._ghost_badge.place_forget()
    win.col_widths[win._drag_col_target] = win._drag_current_width
    MainWindow.apply_column_widths(win)
    win.history_store.set_column_widths(win.col_widths)

    assert win.col_widths["name"] == 310
    win.history_store.set_column_widths.assert_called_with(win.col_widths)

