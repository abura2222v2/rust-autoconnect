"""
Unit test suite for src/history.py (HistoryManager & format_server_entry).
Covers CRUD operations, format helpers, deduplication/MRU, max entries pruning,
atomic file writes, input validation, and corrupted file recovery.
"""

from pathlib import Path
import json
import pytest
from src.history import HistoryManager, format_server_entry


def test_format_server_entry():
    """Test format_server_entry returns correct formatted string."""
    assert format_server_entry({"ip": "127.0.0.1", "port": 28015, "name": "Rust Server #1"}) == "[127.0.0.1:28015] (Rust Server #1)"
    assert format_server_entry({"ip": "192.168.1.100", "port": 28016, "name": ""}) == "[192.168.1.100:28016]"
    assert format_server_entry({"ip": "10.0.0.1", "port": 28015}) == "[10.0.0.1:28015]"
    assert format_server_entry({"ip": "10.0.0.1", "port": 28015, "name": "   "}) == "[10.0.0.1:28015]"


def test_history_init_empty(tmp_path):
    """Test initializing HistoryManager with nonexistent file results in empty history."""
    file_path = tmp_path / "servers.json"
    hm = HistoryManager(filepath=file_path)
    assert hm.get_history() == []
    assert not file_path.exists()  # Not created until saved


def test_add_and_get_server(tmp_path):
    """Test adding servers and retrieving history."""
    file_path = tmp_path / "servers.json"
    hm = HistoryManager(filepath=file_path)

    entry1 = hm.add_server("127.0.0.1", 28015, "Local Test Server")
    assert entry1 == {"ip": "127.0.0.1", "port": 28015, "name": "Local Test Server"}
    assert file_path.exists()

    entry2 = hm.add_server("192.168.1.50", "28016", "Secondary Server")
    assert entry2 == {"ip": "192.168.1.50", "port": 28016, "name": "Secondary Server"}

    history = hm.get_history()
    assert len(history) == 2
    # MRU ordering: newest added is at index 0
    assert history[0]["ip"] == "192.168.1.50"
    assert history[1]["ip"] == "127.0.0.1"


def test_deduplication_and_mru(tmp_path):
    """Test adding an existing server moves it to top and updates name appropriately."""
    file_path = tmp_path / "servers.json"
    hm = HistoryManager(filepath=file_path)

    hm.add_server("127.0.0.1", 28015, "Original Name")
    hm.add_server("10.0.0.1", 28015, "Other Server")
    assert hm.get_history()[0]["ip"] == "10.0.0.1"

    # Re-add first server with a new name -> moves to index 0, updates name
    hm.add_server("127.0.0.1", 28015, "Updated Name")
    history = hm.get_history()
    assert len(history) == 2
    assert history[0]["ip"] == "127.0.0.1"
    assert history[0]["name"] == "Updated Name"

    # Re-add first server with empty name -> moves to index 0, keeps existing name
    hm.add_server("127.0.0.1", 28015, "")
    history2 = hm.get_history()
    assert len(history2) == 2
    assert history2[0]["ip"] == "127.0.0.1"
    assert history2[0]["name"] == "Updated Name"


def test_remove_server(tmp_path):
    """Test removing existing and non-existing servers."""
    file_path = tmp_path / "servers.json"
    hm = HistoryManager(filepath=file_path)

    hm.add_server("127.0.0.1", 28015, "Server 1")
    hm.add_server("192.168.1.1", 28015, "Server 2")

    # Remove existing
    assert hm.remove_server("127.0.0.1", 28015) is True
    history = hm.get_history()
    assert len(history) == 1
    assert history[0]["ip"] == "192.168.1.1"

    # Remove non-existing
    assert hm.remove_server("127.0.0.1", 28015) is False
    assert hm.remove_server("invalid_ip", "invalid_port") is False
    assert len(hm.get_history()) == 1


def test_clear_history(tmp_path):
    """Test clearing all history entries."""
    file_path = tmp_path / "servers.json"
    hm = HistoryManager(filepath=file_path)

    hm.add_server("127.0.0.1", 28015, "Server 1")
    hm.add_server("192.168.1.1", 28015, "Server 2")
    assert len(hm.get_history()) == 2

    hm.clear_history()
    assert hm.get_history() == []

    # Reload from disk to verify persistence
    hm2 = HistoryManager(filepath=file_path)
    assert hm2.get_history() == []


def test_max_entries_pruning(tmp_path):
    """Test that history list is pruned to max_entries."""
    file_path = tmp_path / "servers.json"
    hm = HistoryManager(filepath=file_path, max_entries=3)

    for i in range(5):
        hm.add_server(f"10.0.0.{i}", 28015, f"Server {i}")

    history = hm.get_history()
    assert len(history) == 3
    # Most recent added (Server 4, Server 3, Server 2) should remain
    assert history[0]["ip"] == "10.0.0.4"
    assert history[1]["ip"] == "10.0.0.3"
    assert history[2]["ip"] == "10.0.0.2"


def test_atomic_save(tmp_path):
    """Test atomic file writing and schema format on disk."""
    file_path = tmp_path / "subfolder" / "servers.json"
    hm = HistoryManager(filepath=file_path)
    hm.add_server("127.0.0.1", 28015, "Atomic Server")

    assert file_path.exists()
    # Confirm temp file does not linger
    tmp_path_file = Path(str(file_path) + ".tmp")
    assert not tmp_path_file.exists()

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert isinstance(data, list)
    assert data[0] == {"ip": "127.0.0.1", "port": 28015, "name": "Atomic Server"}


def test_corrupted_json_recovery(tmp_path):
    """Test recovery when servers.json contains invalid JSON syntax."""
    file_path = tmp_path / "servers.json"
    file_path.write_text("{invalid json structure", encoding="utf-8")

    hm = HistoryManager(filepath=file_path)
    assert hm.get_history() == []

    # Verify backup file was created
    corrupted_files = list(tmp_path.glob("servers.json.corrupted_*"))
    assert len(corrupted_files) == 1
    assert corrupted_files[0].read_text(encoding="utf-8") == "{invalid json structure"


def test_invalid_schema_recovery(tmp_path):
    """Test recovery when servers.json is valid JSON but wrong schema."""
    file_path = tmp_path / "servers.json"
    # Case 1: Dict instead of list
    file_path.write_text(json.dumps({"ip": "127.0.0.1"}), encoding="utf-8")

    hm = HistoryManager(filepath=file_path)
    assert hm.get_history() == []
    assert len(list(tmp_path.glob("servers.json.corrupted_*"))) == 1

    # Case 2: List of items missing required fields
    file_path.write_text(json.dumps([{"name": "No IP"}]), encoding="utf-8")
    hm2 = HistoryManager(filepath=file_path)
    assert hm2.get_history() == []
    assert len(list(tmp_path.glob("servers.json.corrupted_*"))) == 2


def test_input_validation(tmp_path):
    """Test input validation for add_server."""
    file_path = tmp_path / "servers.json"
    hm = HistoryManager(filepath=file_path)

    with pytest.raises(ValueError, match="IP address cannot be empty"):
        hm.add_server("", 28015)

    with pytest.raises(ValueError, match="Port must be between 1 and 65535"):
        hm.add_server("127.0.0.1", 70000)

    with pytest.raises(ValueError, match="Invalid port"):
        hm.add_server("127.0.0.1", "invalid_port")
