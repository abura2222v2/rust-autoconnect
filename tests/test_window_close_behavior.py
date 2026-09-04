"""The desktop window's close (X) button used to be disconnected from the
"Minimize to system tray" setting entirely - the tray icon was started
unconditionally (Python can't see Edge's own minimize button), so closing
the app-mode window never actually exited the process, regardless of the
setting - including while it defaults to off. Found live (2026-09-04) after
several test app instances were left running in the background."""
from unittest.mock import MagicMock, patch

from src.core.history_store import history_store
from src.web import server


def test_closing_window_exits_the_app_when_tray_is_disabled():
    history_store.set_minimize_to_tray(False)
    fake_process = MagicMock()
    try:
        with patch("src.web.server.launch_edge_app_mode", return_value=fake_process), \
             patch("os._exit") as mock_exit:
            server._launch_window_and_watch("http://127.0.0.1:1234")
            fake_process.wait.assert_called_once()
            mock_exit.assert_called_once_with(0)
    finally:
        history_store.set_minimize_to_tray(False)


def test_closing_window_keeps_running_in_tray_when_enabled():
    history_store.set_minimize_to_tray(True)
    fake_process = MagicMock()
    try:
        with patch("src.web.server.launch_edge_app_mode", return_value=fake_process), \
             patch("os._exit") as mock_exit:
            server._launch_window_and_watch("http://127.0.0.1:1234")
            fake_process.wait.assert_called_once()
            mock_exit.assert_not_called()
    finally:
        history_store.set_minimize_to_tray(False)


def test_no_window_process_does_not_crash_or_exit():
    """webbrowser.open() fallback (no Edge found) returns None - nothing to
    watch, and the app must not be torn down because of that."""
    with patch("src.web.server.launch_edge_app_mode", return_value=None), \
         patch("os._exit") as mock_exit:
        server._launch_window_and_watch("http://127.0.0.1:1234")
        mock_exit.assert_not_called()
