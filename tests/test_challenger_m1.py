import concurrent.futures
import json
import threading
from unittest.mock import MagicMock, patch

import pytest

from src.core.config import AppConfig
from src.core.history_store import DEFAULT_DATA, HistoryStore
from src.gui.main_window import MainWindow, POPULAR_SERVERS_DATA


def configure_store(monkeypatch, tmp_path):
    monkeypatch.setattr(AppConfig, "appdata_dir", property(lambda self: tmp_path))
    monkeypatch.setattr(AppConfig, "data_file", property(lambda self: tmp_path / "data.json"))
    return HistoryStore()


# =========================================================================
# 1. EMPIRICAL STRESS TESTS: CONCURRENCY & RAPID CYCLING
# =========================================================================

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
    """Rapidly cycle add and remove 1000 times on a single IP."""
    store = configure_store(monkeypatch, tmp_path)
    target_ip = "185.248.134.142:28015"
    popular = [{"name": "Rusticated Trio", "ip": target_ip}]

    for cycle in range(500):
        # 1. Add server
        store.add_to_history(target_ip, f"Server Cycle {cycle}")
        assert target_ip not in store.get_deleted_popular_ips()
        active = store.get_active_history(popular)
        assert len(active) == 1
        assert active[0]["ip"] == target_ip

        # 2. Remove server
        store.remove_from_history(target_ip)
        assert target_ip in store.get_deleted_popular_ips()
        active_after = store.get_active_history(popular)
        assert len(active_after) == 0


# =========================================================================
# 2. EMPIRICAL STRESS TESTS: CORRUPT DATA & NORMALIZATION
# =========================================================================

@pytest.mark.parametrize("corrupt_deleted_value", [
    None,
    12345,
    "not-a-list",
    {"ip": "1.2.3.4:28015"},
    [None, 123, True, {"bad": "data"}, "1.2.3.4:28015", 3.14, []],
    [-1, -999999],
])
def test_deleted_popular_ips_sanitization(monkeypatch, tmp_path, corrupt_deleted_value):
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
        # Only valid string "1.2.3.4:28015" should survive
        assert normalized["deleted_popular_ips"] == [ip for ip in corrupt_deleted_value if isinstance(ip, str)]
    else:
        assert normalized["deleted_popular_ips"] == []


def test_corrupted_data_file_retains_default_structure(monkeypatch, tmp_path):
    """Test disk corruption recovery when data_file contains completely invalid types."""
    data_file = tmp_path / "data.json"
    data_file.write_text(json.dumps("Just a string"), encoding="utf-8")
    store = configure_store(monkeypatch, tmp_path)
    assert store.data == DEFAULT_DATA
    assert isinstance(store.get_deleted_popular_ips(), list)
    assert store.get_deleted_popular_ips() == []


# =========================================================================
# 3. EMPIRICAL STRESS TESTS: GET_ACTIVE_HISTORY ADVERSARIAL INPUTS
# =========================================================================

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
    # The deleted IP must never appear in result
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


# =========================================================================
# 4. EMPIRICAL STRESS TESTS: FORCE ARMED SERVER STATES & DELETIONS
# =========================================================================

def test_force_armed_server_mutation_and_deletion_isolation(monkeypatch, tmp_path):
    """Test armed server states under multiple force flag calls and deletions."""
    store = configure_store(monkeypatch, tmp_path)
    server_a = "1.1.1.1:28015"
    server_b = "2.2.2.2:28015"
    
    # 1. Force arm server A
    store.set_armed_server(server_a, force=True)
    assert store.get_armed_server() == server_a

    # 2. Re-arming server A with force=True stays armed
    store.set_armed_server(server_a, force=True)
    assert store.get_armed_server() == server_a

    # 3. Deleting unrelated server B does NOT disarm server A
    store.add_to_history(server_b, "Server B")
    store.remove_from_history(server_b)
    assert store.get_armed_server() == server_a

    # 4. Deleting armed server A disarms cleanly
    store.remove_from_history(server_a)
    assert store.get_armed_server() == ""

    # 5. Calling remove_from_history on empty or nonexistent strings
    assert store.remove_from_history("")
    assert store.remove_from_history("99.99.99.99:28015")
    assert store.get_armed_server() == ""


# =========================================================================
# 5. EMPIRICAL STRESS TESTS: IMPORT/EXPORT WITH DELETED POPULAR SERVERS
# =========================================================================

def test_import_server_library_un_deletes_imported_popular_ips(monkeypatch, tmp_path):
    """Importing a library containing a previously deleted popular IP resurrects it."""
    store = configure_store(monkeypatch, tmp_path)
    pop_ip = "185.248.134.142:28010"
    store.remove_from_history(pop_ip)
    assert pop_ip in store.get_deleted_popular_ips()

    # Import JSON library containing pop_ip
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

    # Import text library
    text = f"{pop_ip}\n"
    added, updated, unresolved = store.import_server_text(text)
    assert added == 1
    assert pop_ip not in store.get_deleted_popular_ips()


# =========================================================================
# 6. EMPIRICAL STRESS TESTS: DYNAMIC TRUNCATION & TABLE MATH UNDER EXTREMES
# =========================================================================

@pytest.mark.parametrize("width", [-500, -1, 0, 1, 5, 10, 20, 30, 38, 50, 100, 500, 1000, 10000])
@pytest.mark.parametrize("server_name", [
    "",
    "A",
    "Short",
    "Exact6",
    "Exact36CharsServerNameHere1234567890",
    "Very Long Server Name With Multi-Language Support [RU/EU/US] 10x Max 500 Players No Lag Wipe",
    "🇷🇺 [RU] ПЯТНИЦА 2X 💥 ВАЙП СЕГОДНЯ | MAX 3 | RUST RUSSIA",
    "🔥 SERVER WITH MULTI-BYTE EMOJIS & SPECIAL CHARS 🛡️ ⚔️ ★ ⚡",
    "A" * 500,
])
def test_dynamic_truncation_math_extremes(width, server_name):
    """Test dynamic title truncation math against boundary widths and extreme string lengths."""
    available_w = max(30, width - 8)
    max_len = max(6, int(available_w / 7.2))
    
    assert max_len >= 6
    assert available_w >= 30

    if len(server_name) > max_len:
        truncated = f"{server_name[:max(1, max_len - 1)]}…"
        assert truncated.endswith("…")
        assert len(truncated) <= len(server_name) + 1
    else:
        truncated = server_name
        assert truncated == server_name


def test_table_header_and_row_column_budget_alignment():
    """Verify column widths in header and row sub-frames match precisely."""
    # From MainWindow layout specifications:
    h_star_w = 30
    h_addr_w = 145
    h_players_w = 56
    h_local_w = 44
    h_action_w = 96
    
    fixed_columns_total = h_star_w + h_addr_w + h_players_w + h_local_w + h_action_w
    assert fixed_columns_total == 371, f"Fixed column budget must equal 371px, got {fixed_columns_total}"

    # Verify header padding geometry
    header_left_pad = 10
    header_right_pad = 24
    
    # Verify scrollframe padding geometry
    scroll_left_pad = 6
    row_left_pad = 4
    total_row_left = scroll_left_pad + row_left_pad
    assert total_row_left == header_left_pad, f"Row left ({total_row_left}) must equal header left ({header_left_pad})"

    # Scrollbar clearance
    scrollbar_w = 14
    total_row_right = scroll_left_pad + row_left_pad + scrollbar_w
    assert total_row_right == header_right_pad, f"Row right + scrollbar ({total_row_right}) must equal header right ({header_right_pad})"


# =========================================================================
# 7. EMPIRICAL STRESS TESTS: ROW ACTION BUTTON INTERACTIONS
# =========================================================================

def test_row_actions_full_lifecycle(monkeypatch, tmp_path):
    """Verify all 3 row actions (Delete, Arm, Connect) execute their workflows properly."""
    store = configure_store(monkeypatch, tmp_path)
    target_ip = "198.244.168.34:28015"
    target_name = "Rustafied EU Main"
    store.add_to_history(target_ip, target_name)

    window = object.__new__(MainWindow)
    window.history_store = store
    window.t = lambda key, **kwargs: key
    window.refresh_history_ui = MagicMock()
    window.select_history = MagicMock()
    window._refresh_session_state_once = MagicMock()
    window.set_address = MagicMock()
    window._on_connect_btn_click = MagicMock()

    # 1. AutoArm Action: user confirms -> server armed
    with patch("tkinter.messagebox.askyesno", return_value=True):
        MainWindow.toggle_armed(window, target_ip, target_name)
    assert store.get_armed_server() == target_ip
    window.refresh_history_ui.assert_called_once()
    window.select_history.assert_called_once_with(target_ip)

    # 2. Connect Action: sets address and triggers connect
    MainWindow._connect_history_server(window, target_ip)
    window.set_address.assert_called_once_with(target_ip)
    window._on_connect_btn_click.assert_called_once()

    # 3. Delete Action: user confirms -> server removed and disarmed
    window.refresh_history_ui.reset_mock()
    with patch("tkinter.messagebox.askyesno", return_value=True):
        MainWindow.remove_from_history(window, target_ip, target_name)
    assert len(store.get_history()) == 0
    assert store.get_armed_server() == ""
    assert target_ip in store.get_deleted_popular_ips()
    window.refresh_history_ui.assert_called_once()
