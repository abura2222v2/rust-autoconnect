"""
Unit test suite for src/gui.py (MainWindow, HistoryPanel, ControlPanel, LogStatusPanel, validate_ip_port).
Tests run headlessly via root.withdraw() and root.destroy() fixtures.
Covers GUI initialization, minsize enforcement, input validation, smart IP:Port paste,
listbox selection, log appending, line truncation, thread-safe queue handling, and callback hooks.
"""

from pathlib import Path
import time
import tkinter as tk
import pytest
from src.gui import (
    ControlPanel,
    HistoryPanel,
    LogStatusPanel,
    MainWindow,
    validate_ip_port,
)
from src.history import HistoryManager


@pytest.fixture
def tk_root():
    """Headless Tkinter root fixture."""
    root = tk.Tk()
    root.withdraw()
    try:
        style = ttk.Style(root)
        style.theme_use('clam')
    except Exception:
        pass
    yield root
    try:
        root.destroy()
    except Exception:
        pass


@pytest.fixture
def temp_history(tmp_path):
    """Temporary HistoryManager fixture."""
    file_path = tmp_path / "test_gui_servers.json"
    return HistoryManager(filepath=file_path)


def test_validate_ip_port():
    """Test validate_ip_port helper function."""
    is_valid, err, ip, port = validate_ip_port("127.0.0.1", "28015")
    assert is_valid is True
    assert err == ""
    assert ip == "127.0.0.1"
    assert port == 28015

    # Empty IP
    is_valid, err, _, _ = validate_ip_port("", "28015")
    assert is_valid is False
    assert "cannot be empty" in err

    # Invalid port string
    is_valid, err, _, _ = validate_ip_port("127.0.0.1", "invalid")
    assert is_valid is False
    assert "Invalid port number" in err

    # Out of range port
    is_valid, err, _, _ = validate_ip_port("127.0.0.1", "70000")
    assert is_valid is False
    assert "between 1 and 65535" in err


def test_gui_init_and_minsize(tk_root, temp_history):
    """Test MainWindow initialization and minimum window size enforcement."""
    window = MainWindow(root=tk_root, history_manager=temp_history)
    assert window.root.wm_minsize() == (800, 500)
    assert window.history_panel is not None
    assert window.control_panel is not None
    assert window.log_panel is not None
    window.destroy()


def test_smart_paste(tk_root):
    """Test smart paste auto-splitting IP:Port strings."""
    cp = ControlPanel(tk_root)
    cp.ip_var.set("192.168.1.100:28016")
    tk_root.update_idletasks()

    assert cp.ip_var.get() == "192.168.1.100"
    assert cp.port_var.get() == "28016"


def test_control_panel_inputs(tk_root):
    """Test get_inputs and set_inputs in ControlPanel."""
    cp = ControlPanel(tk_root)
    cp.set_inputs("10.0.0.1", 28015, "Test Server")
    assert cp.get_inputs() == ("10.0.0.1", "28015", "Test Server")

    cp.set_connecting_state(True)
    assert cp.is_connecting is True
    assert cp.btn_connect.cget("text") == "Stop"

    cp.set_connecting_state(False)
    assert cp.is_connecting is False
    assert cp.btn_connect.cget("text") == "Connect"


def test_history_panel_selection(tk_root, temp_history):
    """Test updating history listbox and selecting entries."""
    temp_history.add_server("127.0.0.1", 28015, "Local Server")
    temp_history.add_server("192.168.1.1", 28016, "Remote Server")

    selected_server = None

    def on_select(server_dict):
        nonlocal selected_server
        selected_server = server_dict

    hp = HistoryPanel(tk_root, on_select_callback=on_select)
    hp.update_history(temp_history.get_history())

    assert hp.listbox.size() == 2
    # Select first item in listbox (MRU order: 192.168.1.1 is at index 0)
    hp.listbox.selection_set(0)
    hp._on_listbox_select()

    assert selected_server is not None
    assert selected_server["ip"] == "192.168.1.1"
    assert selected_server["port"] == 28016


def test_log_panel_appending_and_truncation(tk_root):
    """Test log appending, tag levels, and line truncation guard."""
    lp = LogStatusPanel(tk_root, max_lines=10)
    lp.append_log("Info log test", "info")
    lp.append_log("Success log test", "success")
    lp.append_log("Warning log test", "warning")
    lp.append_log("Error log test", "error")

    content = lp.text_widget.get("1.0", tk.END)
    assert "Info log test" in content
    assert "Error log test" in content

    # Test truncation exceeding max_lines (10 lines limit)
    for i in range(20):
        lp.append_log(f"Line {i}", "info")

    line_count = int(lp.text_widget.index("end-1c").split(".")[0])
    assert line_count <= 10

    # Test clear_log
    lp.clear_log()
    assert lp.text_widget.get("1.0", tk.END).strip() == ""


def test_connect_toggle_button_and_callbacks(tk_root, temp_history):
    """Test MainWindow Connect/Stop toggle button and callback hooks."""
    connect_calls = []
    stop_calls = []

    def on_connect(ip, port):
        connect_calls.append((ip, port))

    def on_stop():
        stop_calls.append(True)

    window = MainWindow(
        root=tk_root,
        history_manager=temp_history,
        on_connect_click=on_connect,
        on_stop_click=on_stop
    )

    # Fill valid inputs and click connect
    window.control_panel.set_inputs("127.0.0.1", "28015", "Test Server")
    window._on_connect_toggle()

    assert len(connect_calls) == 1
    assert connect_calls[0] == ("127.0.0.1", 28015)

    # Set connecting state to True and toggle to trigger Stop
    window.set_connecting_state(True)
    window._on_connect_toggle()

    assert len(stop_calls) == 1

    # Invalid input should fail without calling connect
    connect_calls.clear()
    window.set_connecting_state(False)
    window.control_panel.set_inputs("invalid_ip", "70000")
    window._on_connect_toggle()

    assert len(connect_calls) == 0
    assert "Error" in window.control_panel.lbl_status.cget("text")

    window.destroy()


def test_threadsafe_queue_processing(tk_root, temp_history):
    """Test thread-safe queue updates (log, status, history, state)."""
    window = MainWindow(root=tk_root, history_manager=temp_history)

    window.append_log_threadsafe("Threadsafe Log Message", "success")
    window.update_status_threadsafe("Threadsafe Polling...", "info")
    window.set_connecting_state_threadsafe(True)

    # Process queue synchronously
    window._process_queue()
    tk_root.update_idletasks()

    assert "Threadsafe Log Message" in window.log_panel.text_widget.get("1.0", tk.END)
    assert window.control_panel.lbl_status.cget("text") == "Threadsafe Polling..."
    assert window.control_panel.is_connecting is True

    window.destroy()


def test_add_remove_clear_history_buttons(tk_root, temp_history):
    """Test Add, Remove, and Clear buttons in HistoryPanel."""
    window = MainWindow(root=tk_root, history_manager=temp_history)

    # Add via panel callback
    window.control_panel.set_inputs("10.0.0.1", "28015", "Server A")
    window._on_history_panel_add()

    assert len(window.history_manager.get_history()) == 1
    assert window.history_panel.listbox.size() == 1

    # Remove via panel callback
    window.history_panel.listbox.selection_set(0)
    window._on_history_panel_remove()

    assert len(window.history_manager.get_history()) == 0
    assert window.history_panel.listbox.size() == 0

    # Add 2 servers and Clear
    window.control_panel.set_inputs("10.0.0.1", "28015", "Server A")
    window._on_history_panel_add()
    window.control_panel.set_inputs("10.0.0.2", "28015", "Server B")
    window._on_history_panel_add()
    assert len(window.history_manager.get_history()) == 2

    window._on_history_panel_clear()
    assert len(window.history_manager.get_history()) == 0

    window.destroy()
