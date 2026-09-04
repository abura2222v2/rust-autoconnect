import concurrent.futures
import json

import pytest

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


def test_text_library_resolves_and_deduplicates_domain_and_ip(monkeypatch, tmp_path):
    store = configure_store(monkeypatch, tmp_path)
    text = "# Shared servers\n* eu-trio-mon.rusticated.com\n185.248.134.142:28010\n"

    added, updated, unresolved = store.import_server_text(
        text,
        resolver=lambda host: {"eu-trio-mon.rusticated.com": "185.248.134.142"}[host],
    )

    assert (added, updated, unresolved) == (1, 0, 0)
    assert store.get_history() == [{
        "ip": "eu-trio-mon.rusticated.com:28010",
        "name": "eu-trio-mon.rusticated.com",
        "canonical_endpoint": "185.248.134.142:28010",
        "added_at": store.get_history()[0]["added_at"],
    }]
    assert store.get_favorites() == [{
        "ip": "eu-trio-mon.rusticated.com:28010",
        "name": "eu-trio-mon.rusticated.com",
    }]


def test_text_library_keeps_unresolved_domain_for_later_connection(monkeypatch, tmp_path):
    store = configure_store(monkeypatch, tmp_path)
    added, updated, unresolved = store.import_server_text(
        "temporary.example:28015\n",
        resolver=lambda _host: (_ for _ in ()).throw(OSError("DNS unavailable")),
    )

    assert (added, updated, unresolved) == (1, 0, 1)
    assert store.get_history()[0]["ip"] == "temporary.example:28015"
    assert store.get_history()[0]["canonical_endpoint"] == ""


def test_text_library_export_marks_favorites(monkeypatch, tmp_path):
    store = configure_store(monkeypatch, tmp_path)
    store.add_to_history("127.0.0.1:28015", "Rust Server")
    store.toggle_favorite("127.0.0.1:28015", "Rust Server")

    assert store.export_server_text().splitlines()[-1] == "* 127.0.0.1:28015"


def test_remove_server_forgets_favorite_and_armed_state(monkeypatch, tmp_path):
    store = configure_store(monkeypatch, tmp_path)
    endpoint = "127.0.0.1:28015"
    store.add_to_history(endpoint, "Test Server")
    store.toggle_favorite(endpoint, "Test Server")
    store.set_armed_server(endpoint)

    assert store.remove_from_history(endpoint)
    assert store.get_history() == []
    assert store.get_favorites() == []
    assert store.get_armed_server() == ""


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


def test_server_profile_tracks_local_connection_state(monkeypatch, tmp_path):
    store = configure_store(monkeypatch, tmp_path)
    endpoint = "127.0.0.1:28015"
    store.add_to_history(endpoint, "Test Server")
    store.toggle_favorite(endpoint, "Test Server")
    store.set_armed_server(endpoint)
    assert store.update_server_profile(endpoint, state="disconnected", reason="Timed out", checked_at=123)
    assert store.get_server_profile(endpoint) == {
        "favorite": True,
        "armed": True,
        "last_state": "disconnected",
        "last_checked_at": 123,
        "last_disconnect_reason": "Timed out",
        "last_connected_at": 0,
    }


def test_share_saved_servers_is_opt_in_and_persisted(monkeypatch, tmp_path):
    store = configure_store(monkeypatch, tmp_path)
    assert store.get_share_saved_servers() is False
    store.set_share_saved_servers(True)
    assert store.get_share_saved_servers() is True
    assert configure_store(monkeypatch, tmp_path).get_share_saved_servers() is True


def test_deleted_popular_servers_tracking_and_active_history(monkeypatch, tmp_path):
    store = configure_store(monkeypatch, tmp_path)
    popular = [
        {"name": "Popular 1", "ip": "1.1.1.1:28015"},
        {"name": "Popular 2", "ip": "2.2.2.2:28015"},
    ]
    # Initially, active history includes popular servers
    active = store.get_active_history(popular)
    assert len(active) == 2
    assert {s["ip"] for s in active} == {"1.1.1.1:28015", "2.2.2.2:28015"}

    # Remove popular 1
    store.remove_from_history("1.1.1.1:28015")
    assert "1.1.1.1:28015" in store.get_deleted_popular_ips()

    # Active history should no longer include popular 1
    active_after = store.get_active_history(popular)
    assert len(active_after) == 1
    assert active_after[0]["ip"] == "2.2.2.2:28015"

    # User re-adds 1.1.1.1:28015 manually
    store.add_to_history("1.1.1.1:28015", "My Custom Server")
    assert "1.1.1.1:28015" not in store.get_deleted_popular_ips()
    active_readded = store.get_active_history(popular)
    assert len(active_readded) == 2
    assert active_readded[0]["ip"] == "1.1.1.1:28015"


def test_set_armed_server_force_flag(monkeypatch, tmp_path):
    store = configure_store(monkeypatch, tmp_path)
    endpoint = "127.0.0.1:28015"

    # Default toggling behavior
    store.set_armed_server(endpoint, force=False)
    assert store.get_armed_server() == endpoint

    store.set_armed_server(endpoint, force=False)
    assert store.get_armed_server() == ""

    # Force flag behavior (does not toggle off if already set)
    store.set_armed_server(endpoint, force=True)
    assert store.get_armed_server() == endpoint

    store.set_armed_server(endpoint, force=True)
    assert store.get_armed_server() == endpoint

    store.set_armed_server("", force=True)
    assert store.get_armed_server() == ""


# ---------------------------------------------------------------------------
# Moved from tests/test_challenger_m1.py when the legacy Tkinter GUI (and its
# test file, which mixed these pure HistoryStore checks in with GUI-specific
# ones) was removed. These cover adversarial/concurrency edge cases the tests
# above don't.
# ---------------------------------------------------------------------------

def test_concurrent_history_store_operations(monkeypatch, tmp_path):
    """Stress test HistoryStore with 50 concurrent threads executing interleaved mutations."""
    store = configure_store(monkeypatch, tmp_path)
    popular = [{"name": f"Pop {i}", "ip": f"10.0.0.{i}:28015"} for i in range(10)]

    num_threads = 50
    ops_per_thread = 20
    errors = []

    def worker(worker_id):
        try:
            for i in range(ops_per_thread):
                ip = f"10.0.0.{i % 10}:28015"
                custom_ip = f"192.168.1.{worker_id}_{i}:28015"

                # Interleaved operations
                store.add_to_history(custom_ip, f"Custom {worker_id}_{i}")
                store.toggle_favorite(custom_ip, f"Custom {worker_id}_{i}")
                store.set_armed_server(custom_ip, force=(i % 2 == 0))

                # Active history querying under concurrent mutation
                active = store.get_active_history(popular)
                assert isinstance(active, list)

                # Delete operation
                if i % 3 == 0:
                    store.remove_from_history(ip)
                elif i % 3 == 1:
                    store.remove_from_history(custom_ip)
                else:
                    store.add_to_history(ip, f"Re-added Pop {i}")

                # Profile queries
                profile = store.get_server_profile(custom_ip)
                assert isinstance(profile, dict)
        except Exception as exc:
            errors.append(exc)

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker, tid) for tid in range(num_threads)]
        concurrent.futures.wait(futures)

    assert len(errors) == 0, f"Encountered {len(errors)} concurrency errors: {errors}"
    # Verify the final state can still be cleanly loaded and saved
    assert isinstance(store.get_history(), list)
    assert len(store.get_history()) <= 20
    assert store.save() is True


def test_rapid_add_remove_cycles(monkeypatch, tmp_path):
    """Rapidly cycle add and remove 500 times on a single IP."""
    store = configure_store(monkeypatch, tmp_path)
    target_ip = "185.248.134.142:28015"
    popular = [{"name": "Rusticated Trio", "ip": target_ip}]

    for cycle in range(500):
        store.add_to_history(target_ip, f"Server Cycle {cycle}")
        assert target_ip not in store.get_deleted_popular_ips()
        active = store.get_active_history(popular)
        assert len(active) == 1
        assert active[0]["ip"] == target_ip

        store.remove_from_history(target_ip)
        assert target_ip in store.get_deleted_popular_ips()
        active_after = store.get_active_history(popular)
        assert len(active_after) == 0


@pytest.mark.parametrize("corrupt_deleted_value", [
    None,
    12345,
    "not-a-list",
    {"ip": "1.2.3.4:28015"},
    [None, 123, True, {"bad": "data"}, "1.2.3.4:28015", 3.14, []],
    [-1, -999999],
])
def test_deleted_popular_ips_sanitization(corrupt_deleted_value):
    """Ensure _normalize cleanly purges corrupted deleted_popular_ips structures."""
    raw_data = {
        "history": [],
        "favorites": [],
        "benchmark_runs": [],
        "deleted_popular_ips": corrupt_deleted_value,
    }
    normalized = HistoryStore._normalize(raw_data)
    assert isinstance(normalized["deleted_popular_ips"], list)
    assert all(isinstance(ip, str) for ip in normalized["deleted_popular_ips"])
    if isinstance(corrupt_deleted_value, list):
        assert normalized["deleted_popular_ips"] == [ip for ip in corrupt_deleted_value if isinstance(ip, str)]
    else:
        assert normalized["deleted_popular_ips"] == []


def test_corrupted_data_file_retains_default_structure(monkeypatch, tmp_path):
    """Disk corruption recovery when data_file contains a completely invalid type (a bare string)."""
    data_file = tmp_path / "data.json"
    data_file.write_text(json.dumps("Just a string"), encoding="utf-8")
    store = configure_store(monkeypatch, tmp_path)
    assert store.data == DEFAULT_DATA
    assert isinstance(store.get_deleted_popular_ips(), list)
    assert store.get_deleted_popular_ips() == []


@pytest.mark.parametrize("adversarial_pop_list", [
    None,
    [],
    [None, 123, "invalid", {}, {"name": "No IP"}],
    [{"name": "Valid 1", "ip": "1.1.1.1:28015"}, {"bad": 1}, {"name": "Valid 2", "ip": "2.2.2.2:28015"}],
    [{"name": "Dup", "ip": "1.1.1.1:28015"}, {"name": "Dup", "ip": "1.1.1.1:28015"}],
])
def test_get_active_history_adversarial_popular_lists(monkeypatch, tmp_path, adversarial_pop_list):
    """Verify get_active_history never raises an unhandled exception with malformed popular_list."""
    store = configure_store(monkeypatch, tmp_path)
    store.add_to_history("100.100.100.100:28015", "My Server")
    store.remove_from_history("1.1.1.1:28015")  # Deleted popular IP

    result = store.get_active_history(adversarial_pop_list)
    assert isinstance(result, list)
    assert any(item.get("ip") == "100.100.100.100:28015" for item in result)
    assert not any(item.get("ip") == "1.1.1.1:28015" for item in result)


def test_get_active_history_preserves_history_precedence_over_popular(monkeypatch, tmp_path):
    """User-customized history entry should take precedence over static popular defaults."""
    store = configure_store(monkeypatch, tmp_path)
    ip = "198.244.168.34:28015"
    store.add_to_history(ip, "My Custom Nickname For Rustafied")

    popular = [{"name": "Default Rustafied EU", "ip": ip}]
    active = store.get_active_history(popular)

    assert len(active) == 1
    assert active[0]["name"] == "My Custom Nickname For Rustafied"


def test_force_armed_server_mutation_and_deletion_isolation(monkeypatch, tmp_path):
    """Test armed server states under multiple force flag calls and deletions."""
    store = configure_store(monkeypatch, tmp_path)
    server_a = "1.1.1.1:28015"
    server_b = "2.2.2.2:28015"

    store.set_armed_server(server_a, force=True)
    assert store.get_armed_server() == server_a

    # Re-arming server A with force=True stays armed
    store.set_armed_server(server_a, force=True)
    assert store.get_armed_server() == server_a

    # Deleting unrelated server B does NOT disarm server A
    store.add_to_history(server_b, "Server B")
    store.remove_from_history(server_b)
    assert store.get_armed_server() == server_a

    # Deleting armed server A disarms cleanly
    store.remove_from_history(server_a)
    assert store.get_armed_server() == ""

    # Calling remove_from_history on empty or nonexistent strings must not raise
    assert store.remove_from_history("")
    assert store.remove_from_history("99.99.99.99:28015")
    assert store.get_armed_server() == ""


def test_import_server_library_un_deletes_imported_popular_ips(monkeypatch, tmp_path):
    """Importing a library containing a previously deleted popular IP resurrects it."""
    store = configure_store(monkeypatch, tmp_path)
    pop_ip = "185.248.134.142:28010"
    store.remove_from_history(pop_ip)
    assert pop_ip in store.get_deleted_popular_ips()

    payload = {
        "format": "rust-autoconnect-server-library-v1",
        "servers": [{"ip": pop_ip, "name": "Imported Rusticated"}],
        "favorites": [],
    }
    added, updated = store.import_server_library(payload)
    assert added == 1
    assert pop_ip not in store.get_deleted_popular_ips()


def test_import_server_text_un_deletes_imported_popular_ips(monkeypatch, tmp_path):
    """Importing a text list containing a previously deleted popular IP resurrects it."""
    store = configure_store(monkeypatch, tmp_path)
    pop_ip = "185.248.134.142:28010"
    store.remove_from_history(pop_ip)
    assert pop_ip in store.get_deleted_popular_ips()

    text = f"{pop_ip}\n"
    added, updated, unresolved = store.import_server_text(text)
    assert added == 1
    assert pop_ip not in store.get_deleted_popular_ips()


def test_rapid_history_mutation_stress(monkeypatch, tmp_path):
    """500 interleaved add/favorite/arm/remove operations, then verify the
    on-disk JSON file itself stays valid and shaped correctly - not just the
    in-memory state (moved from tests/test_adversarial_m1_challenger.py)."""
    store = configure_store(monkeypatch, tmp_path)

    for i in range(500):
        ip = f"192.168.{(i % 50)}.{i}:28015"
        name = f"Server {i}"
        store.add_to_history(ip, name)
        if i % 3 == 0:
            store.toggle_favorite(ip, name)
        if i % 5 == 0:
            store.set_armed_server(ip)
        if i % 7 == 0:
            store.remove_from_history(ip)

    history = store.get_history()
    assert len(history) <= 20
    assert isinstance(store.get_favorites(), list)
    assert isinstance(store.get_deleted_popular_ips(), list)

    data_file = tmp_path / "data.json"
    assert data_file.exists()
    content = json.loads(data_file.read_text(encoding="utf-8"))
    assert "history" in content
    assert "deleted_popular_ips" in content

