from unittest.mock import MagicMock, patch

from src.core.config import AppConfig
from src.core.history_store import HistoryStore
from src.gui.main_window import MainWindow, POPULAR_SERVERS_DATA


def configure_store(monkeypatch, tmp_path):
    monkeypatch.setattr(AppConfig, "appdata_dir", property(lambda self: tmp_path))
    monkeypatch.setattr(AppConfig, "data_file", property(lambda self: tmp_path / "data.json"))
    return HistoryStore()


def test_remove_from_history_user_confirmation_and_store_call(monkeypatch, tmp_path):
    store = configure_store(monkeypatch, tmp_path)
    store.add_to_history("198.244.168.34:28015", "Rustafied EU")

    window = object.__new__(MainWindow)
    window.history_store = store
    window.t = lambda key, **kwargs: key
    window.refresh_history_ui = MagicMock()

    # User cancels confirmation dialog -> server remains
    with patch("tkinter.messagebox.askyesno", return_value=False):
        MainWindow.remove_from_history(window, "198.244.168.34:28015", "Rustafied EU")
    assert len(store.get_history()) == 1
    window.refresh_history_ui.assert_not_called()

    # User confirms dialog -> server removed and UI refreshed
    with patch("tkinter.messagebox.askyesno", return_value=True):
        MainWindow.remove_from_history(window, "198.244.168.34:28015", "Rustafied EU")
    assert len(store.get_history()) == 0
    assert "198.244.168.34:28015" in store.get_deleted_popular_ips()
    window.refresh_history_ui.assert_called_once()


def test_toggle_armed_flow(monkeypatch, tmp_path):
    store = configure_store(monkeypatch, tmp_path)
    endpoint = "198.244.168.35:28015"

    window = object.__new__(MainWindow)
    window.history_store = store
    window.t = lambda key, **kwargs: key
    window.refresh_history_ui = MagicMock()
    window.select_history = MagicMock()
    window._refresh_session_state_once = MagicMock()

    # When not armed, user cancels warning dialog -> not armed
    with patch("tkinter.messagebox.askyesno", return_value=False):
        MainWindow.toggle_armed(window, endpoint, "Rustopia")
    assert store.get_armed_server() == ""
    window.refresh_history_ui.assert_not_called()

    # When not armed, user confirms warning -> server armed
    with patch("tkinter.messagebox.askyesno", return_value=True):
        MainWindow.toggle_armed(window, endpoint, "Rustopia")
    assert store.get_armed_server() == endpoint
    window.refresh_history_ui.assert_called_once()
    window.select_history.assert_called_once_with(endpoint)
    window._refresh_session_state_once.assert_called_once()

    # When already armed, toggling disarms without prompt
    window.refresh_history_ui.reset_mock()
    MainWindow.toggle_armed(window, endpoint, "Rustopia")
    assert store.get_armed_server() == ""
    window.refresh_history_ui.assert_called_once()


def test_connect_history_server_initiates_connect_action():
    window = object.__new__(MainWindow)
    window.set_address = MagicMock()
    window._on_connect_btn_click = MagicMock()

    MainWindow._connect_history_server(window, "1.2.3.4:28015")
    window.set_address.assert_called_once_with("1.2.3.4:28015")
    window._on_connect_btn_click.assert_called_once()


def test_popular_servers_never_resurface_after_deletion(monkeypatch, tmp_path):
    store = configure_store(monkeypatch, tmp_path)
    pop_list = [
        {"name": data["name"], "ip": pop_ip, "added_at": 0}
        for pop_ip, data in POPULAR_SERVERS_DATA.items()
    ]
    initial_count = len(POPULAR_SERVERS_DATA)
    active = store.get_active_history(pop_list)
    assert len(active) == initial_count

    first_popular_ip = next(iter(POPULAR_SERVERS_DATA.keys()))
    store.remove_from_history(first_popular_ip)

    active_after = store.get_active_history(pop_list)
    assert len(active_after) == initial_count - 1
    assert first_popular_ip not in {s["ip"] for s in active_after}
