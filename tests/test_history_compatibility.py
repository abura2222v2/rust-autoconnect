import json

from src.core.config import AppConfig
from src.core.history_store import HistoryStore


def test_unknown_settings_are_preserved(monkeypatch, tmp_path):
    data_file = tmp_path / "data.json"
    data_file.write_text(json.dumps({"history": [], "tray_enabled": True}), encoding="utf-8")
    monkeypatch.setattr(AppConfig, "appdata_dir", property(lambda self: tmp_path))
    monkeypatch.setattr(AppConfig, "data_file", property(lambda self: data_file))
    store = HistoryStore()
    store.set_username("tester")
    saved = json.loads(data_file.read_text(encoding="utf-8"))
    assert saved["tray_enabled"] is True
