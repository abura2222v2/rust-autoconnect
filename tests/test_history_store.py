import json

from src.core.config import AppConfig
from src.core.history_store import DEFAULT_DATA, HistoryStore


def configure_store(monkeypatch, tmp_path):
    monkeypatch.setattr(AppConfig, "appdata_dir", property(lambda self: tmp_path))
    monkeypatch.setattr(AppConfig, "data_file", property(lambda self: tmp_path / "data.json"))
    return HistoryStore()


def test_history_is_mru_limited_and_isolated(monkeypatch, tmp_path):
    store = configure_store(monkeypatch, tmp_path)
    for index in range(22):
        store.add_to_history(f"127.0.0.1:{28015 + index}", f"Server {index}")
    history = store.get_history()
    assert len(history) == 20
    assert history[0]["name"] == "Server 21"
    history[0]["name"] = "changed"
    assert store.get_history()[0]["name"] == "Server 21"


def test_corrupted_settings_are_backed_up_and_reset(monkeypatch, tmp_path):
    data_file = tmp_path / "data.json"
    data_file.write_text("{broken", encoding="utf-8")
    store = configure_store(monkeypatch, tmp_path)
    assert store.data == DEFAULT_DATA
    assert len(list(tmp_path.glob("data.json.corrupted_*"))) == 1


def test_invalid_settings_shape_is_recovered(monkeypatch, tmp_path):
    data_file = tmp_path / "data.json"
    data_file.write_text(json.dumps({"history": "not-a-list"}), encoding="utf-8")
    store = configure_store(monkeypatch, tmp_path)
    assert store.get_history() == []
    assert len(list(tmp_path.glob("data.json.corrupted_*"))) == 1


def test_benchmark_runs_and_installation_identity_are_persisted(monkeypatch, tmp_path):
    store = configure_store(monkeypatch, tmp_path)
    installation_id = store.get_installation_id()
    assert installation_id == store.get_installation_id()

    assert store.add_benchmark_run({"id": "run-1", "configuration_key": "config-a", "total_time": 10.0})
    assert store.get_benchmark_runs("config-a")[0]["sync_state"] == "pending"
    assert store.mark_benchmark_run_synced("run-1")
    assert store.get_benchmark_runs()[0]["sync_state"] == "synced"

    replacement = store.reset_installation_id()
    assert replacement != installation_id


def test_history_metadata_survives_a_new_connection(monkeypatch, tmp_path):
    store = configure_store(monkeypatch, tmp_path)
    store.add_to_history("127.0.0.1:28015", "Rust Server")
    assert store.update_server_metadata("127.0.0.1:28015", ["EU", "PVP"], "Night schedule")
    store.add_to_history("127.0.0.1:28015", "Updated Server")
    item = store.get_history()[0]
    assert item["tags"] == ["EU", "PVP"]
    assert item["note"] == "Night schedule"


def test_server_library_export_import_merges_records(monkeypatch, tmp_path):
    source = configure_store(monkeypatch, tmp_path / "source")
    source.add_to_history("127.0.0.1:28015", "Source Server")
    source.toggle_favorite("127.0.0.1:28015", "Source Server")
    payload = source.export_server_library()

    target = configure_store(monkeypatch, tmp_path / "target")
    target.add_to_history("127.0.0.1:28016", "Existing Server")
    target.toggle_favorite("127.0.0.1:28016", "Existing Server")
    target.set_armed_server("127.0.0.1:28016")
    assert target.import_server_library(payload) == (1, 0)
    assert {item["ip"] for item in target.get_history()} == {"127.0.0.1:28015", "127.0.0.1:28016"}
    assert {item["ip"] for item in target.get_favorites()} == {"127.0.0.1:28015", "127.0.0.1:28016"}
    assert target.get_armed_server() == "127.0.0.1:28016"


def test_server_library_import_normalizes_malformed_records(monkeypatch, tmp_path):
    store = configure_store(monkeypatch, tmp_path)
    payload = {
        "format": "rust-autoconnect-server-library-v1",
        "servers": [
            {"ip": "127.0.0.1:28015", "name": "Valid", "added_at": {"bad": True}},
            {"ip": "x" * 400 + ":28015", "name": "Too long"},
            {"ip": "127.0.0.1:99999", "name": "Bad port"},
        ],
        "favorites": [],
    }

    assert store.import_server_library(payload) == (1, 0)
    assert [item["ip"] for item in store.get_history()] == ["127.0.0.1:28015"]
    assert isinstance(store.get_history()[0]["added_at"], int)


def test_server_wipe_schedule_is_optional_and_persisted(monkeypatch, tmp_path):
    store = configure_store(monkeypatch, tmp_path)
    endpoint = "127.0.0.1:28015"
    store.add_to_history(endpoint, "Test Server")
    assert store.get_server_wipe_schedule(endpoint) == {"wipe_at": None, "wipe_source": ""}
    assert store.set_server_wipe_schedule(endpoint, 1_800_000_000)
    assert store.get_server_wipe_schedule(endpoint) == {"wipe_at": 1_800_000_000, "wipe_source": "manual"}
    assert store.set_server_wipe_schedule(endpoint, None)
    assert store.get_server_wipe_schedule(endpoint) == {"wipe_at": None, "wipe_source": ""}
