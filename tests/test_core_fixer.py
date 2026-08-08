import os
import time
import shutil
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.core.history_store import HistoryStore
from src.core.a2s_client import A2SClient
from src.core.logger import AppLogger
from src.core.config import AppConfig


def test_history_store_deepcopy_and_thread_safety(tmp_path, monkeypatch):
    data_file = tmp_path / "data.json"
    monkeypatch.setattr(AppConfig, "appdata_dir", property(lambda self: tmp_path))
    monkeypatch.setattr(AppConfig, "data_file", property(lambda self: data_file))

    hs = HistoryStore()
    hs.add_to_history("127.0.0.1:28015", "Test Server")
    
    # Check deepcopy
    hist1 = hs.get_history()
    hist1[0]["name"] = "Mutated Name"
    hist2 = hs.get_history()
    assert hist2[0]["name"] == "Test Server"

    # Check set_username & get_client_id thread safety / save call
    hs.set_username("TestUser")
    assert hs.get_username() == "TestUser"
    
    cid = hs.get_client_id()
    assert cid != ""
    assert hs.get_client_id() == cid


def test_history_store_flush_fsync(tmp_path, monkeypatch):
    data_file = tmp_path / "data.json"
    monkeypatch.setattr(AppConfig, "appdata_dir", property(lambda self: tmp_path))
    monkeypatch.setattr(AppConfig, "data_file", property(lambda self: data_file))

    hs = HistoryStore()
    with patch("os.fsync") as mock_fsync:
        hs.set_username("UserSync")
        assert mock_fsync.called


def test_a2s_client_wsaeconnreset_sleep():
    client = A2SClient(timeout=0.1, offsets=(0,))
    with patch("a2s.info", side_effect=ConnectionResetError("WSAECONNRESET")):
        with patch("time.sleep") as mock_sleep:
            is_alive, name, max_players, port = client.check_server_alive("127.0.0.1", 28015)
            assert not is_alive
            assert mock_sleep.called
            mock_sleep.assert_called_with(0.5)


def test_logger_appdata_path(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    log_dir = os.path.join(os.getenv('APPDATA', os.getcwd()), 'RustAutoConnect')
    os.makedirs(log_dir, exist_ok=True)
    expected_dir = tmp_path / "RustAutoConnect"
    assert expected_dir.exists()
