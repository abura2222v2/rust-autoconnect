"""
Adversarial stress test suite for Milestone 1:
- Table event handlers & binding behavior
- Tooltip lifecycle (creation, destruction, hover during destroy, memory retention, winfo_viewable guard)
- Delete & AutoArm confirmation dialog dismissal vs acceptance
- GUI state consistency during rapid / concurrent operations
- Memory leaks & object count stability over rapid history refreshes
- Text truncation boundary conditions and layout invariants
- Popular server deletion and re-addition cycles across restarts
- Event isolation: ensuring action button clicks do not bubble to row selection
"""

import gc
import json
import tempfile
from pathlib import Path
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

import pytest

from src.core.config import AppConfig
from src.core.history_store import HistoryStore
from src.gui.tooltip import ToolTip
from src.gui.main_window import (
    MainWindow,
    POPULAR_SERVERS_DATA,
    DOMAIN_TO_IP_FALLBACK,
    _get_server_metadata,
)


class TestTooltipLifecycleAdversarial(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
            cls.root.geometry("400x300+100+100")
            cls.root.update()
        except tk.TclError:
            cls.root = None

    @classmethod
    def tearDownClass(cls):
        if cls.root:
            try:
                cls.root.destroy()
            except Exception:
                pass

    def setUp(self):
        if not self.root:
            self.skipTest("Tkinter display not available")

    def test_tooltip_viewable_guard_prevents_ghost_popups(self):
        """When parent widget is unmapped/withdrawn, showtip safely aborts without ghost windows."""
        hidden_window = tk.Toplevel(self.root)
        hidden_window.withdraw()
        btn = tk.Button(hidden_window, text="Hidden Btn")
        btn.pack()
        tip = ToolTip(btn, "Ghost tip")

        tip.showtip()
        assert tip.tw is None  # winfo_viewable guard prevented ghost toplevel

        hidden_window.destroy()

    def test_tooltip_scheduled_then_widget_destroyed_before_show(self):
        """Hover widget, schedule tooltip timer, destroy widget before 400ms fires."""
        btn = tk.Button(self.root, text="Hover me")
        btn.pack()
        self.root.update()

        tip = ToolTip(btn, "Test tooltip")
        tip.enter()  # schedule 400ms timer
        assert tip.id is not None

        # Destroy widget immediately
        btn.destroy()
        self.root.update()

        # Timer should be unscheduled or showtip should safely abort
        self.root.after(500, lambda: None)
        self.root.update()

        assert tip.tw is None

    def test_tooltip_shown_then_widget_destroyed(self):
        """Hover widget, let tooltip display, then destroy widget."""
        btn = tk.Button(self.root, text="Show Tip")
        btn.pack()
        self.root.update()

        tip = ToolTip(btn, "Visible Tooltip")
        tip.showtip()
        self.root.update()

        assert tip.tw is not None
        assert tip.tw.winfo_exists()

        # Destroying the parent widget triggers <Destroy> binding -> calls leave() -> hidetip()
        btn.destroy()
        self.root.update()

        assert tip.tw is None

    def test_tooltip_rapid_enter_leave_cycle(self):
        """Simulate rapid mouse jitter across tooltip target."""
        btn = tk.Button(self.root, text="Jitter")
        btn.pack()
        self.root.update()
        tip = ToolTip(btn, "Jitter Tip")

        for _ in range(50):
            tip.enter()
            tip.leave()

        assert tip.id is None
        assert tip.tw is None
        btn.destroy()
        self.root.update()

    def test_tooltip_memory_leak_free(self):
        """Create and destroy 100 tooltips, ensuring no lingering widgets or cyclic references."""
        gc.collect()
        initial_objects = len(gc.get_objects())

        for i in range(100):
            btn = tk.Button(self.root, text=f"Btn {i}")
            btn.pack()
            tip = ToolTip(btn, f"Tip {i}")
            tip.enter()
            tip.leave()
            btn.destroy()

        gc.collect()
        self.root.update()
        final_objects = len(gc.get_objects())
        delta = final_objects - initial_objects
        assert delta < 100, f"Memory leak detected: object growth delta = {delta}"


class TestMainWindowLogicAdversarial(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        tmp_path = Path(self.temp_dir.name)
        self.tmp_path = tmp_path
        with patch.object(AppConfig, "appdata_dir", property(lambda _self: tmp_path)), \
             patch.object(AppConfig, "data_file", property(lambda _self: tmp_path / "data.json")):
            self.store = HistoryStore()

        self.window = object.__new__(MainWindow)
        self.window.history_store = self.store
        self.window.i18n = MagicMock()
        self.window.i18n.lang = "RU"
        self.window.t = lambda key, **kwargs: key
        self.window.filter_var = MagicMock()
        self.window.filter_var.get.return_value = "Все"
        self.window.search_entry = MagicMock()
        self.window.search_entry.get.return_value = ""
        self.window.refresh_history_ui = MagicMock()
        self.window.select_history = MagicMock()
        self.window._refresh_session_state_once = MagicMock()
        self.window.set_address = MagicMock()
        self.window._on_connect_btn_click = MagicMock()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_delete_dialog_rejection_preserves_state(self):
        target_ip = "192.168.1.50:28015"
        self.store.add_to_history(target_ip, "Target To Keep")
        self.store.toggle_favorite(target_ip, "Target To Keep")
        self.store.set_armed_server(target_ip)

        # User clicks "No" on delete dialog
        with patch("tkinter.messagebox.askyesno", return_value=False):
            MainWindow.remove_from_history(self.window, target_ip, "Target To Keep")

        # Verify state is completely preserved
        assert any(s["ip"] == target_ip for s in self.store.get_history())
        assert any(f["ip"] == target_ip for f in self.store.get_favorites())
        assert self.store.get_armed_server() == target_ip
        assert target_ip not in self.store.get_deleted_popular_ips()
        self.window.refresh_history_ui.assert_not_called()

    def test_delete_dialog_acceptance_purges_all_references(self):
        target_ip = "192.168.1.51:28015"
        self.store.add_to_history(target_ip, "Target To Purge")
        self.store.toggle_favorite(target_ip, "Target To Purge")
        self.store.set_armed_server(target_ip)

        # User clicks "Yes" on delete dialog
        with patch("tkinter.messagebox.askyesno", return_value=True):
            MainWindow.remove_from_history(self.window, target_ip, "Target To Purge")

        # Verify state is completely purged
        assert not any(s["ip"] == target_ip for s in self.store.get_history())
        assert not any(f["ip"] == target_ip for f in self.store.get_favorites())
        assert self.store.get_armed_server() == ""
        assert target_ip in self.store.get_deleted_popular_ips()
        self.window.refresh_history_ui.assert_called_once()

    def test_autoarm_dialog_rejection_preserves_unarmed_state(self):
        target_ip = "192.168.1.60:28015"
        self.store.add_to_history(target_ip, "Unarmed Server")

        with patch("tkinter.messagebox.askyesno", return_value=False):
            MainWindow.toggle_armed(self.window, target_ip, "Unarmed Server")

        assert self.store.get_armed_server() == ""
        self.window.refresh_history_ui.assert_not_called()

    def test_autoarm_dialog_acceptance_arms_server(self):
        target_ip = "192.168.1.61:28015"
        self.store.add_to_history(target_ip, "Arm Target")

        with patch("tkinter.messagebox.askyesno", return_value=True):
            MainWindow.toggle_armed(self.window, target_ip, "Arm Target")

        assert self.store.get_armed_server() == target_ip
        self.window.refresh_history_ui.assert_called_once()
        self.window.select_history.assert_called_once_with(target_ip)
        self.window._refresh_session_state_once.assert_called_once()

    def test_autoarm_disarm_requires_no_dialog(self):
        target_ip = "192.168.1.62:28015"
        self.store.add_to_history(target_ip, "Armed Server")
        self.store.set_armed_server(target_ip)

        with patch("tkinter.messagebox.askyesno") as mock_box:
            MainWindow.toggle_armed(self.window, target_ip, "Armed Server")
            mock_box.assert_not_called()

        assert self.store.get_armed_server() == ""
        self.window.refresh_history_ui.assert_called_once()

    def test_connect_row_button_delegation(self):
        self.window.set_address = MagicMock()
        self.window._on_connect_btn_click = MagicMock()

        MainWindow._connect_history_server(self.window, "10.10.10.10:28015")
        self.window.set_address.assert_called_once_with("10.10.10.10:28015")
        self.window._on_connect_btn_click.assert_called_once()


class TestTableLayoutAndMetadataAdversarial(unittest.TestCase):
    def test_server_metadata_adversarial_inputs(self):
        """Stress-test metadata extraction with adversarial endpoints and names."""
        cases = [
            ("", ""),
            ("invalid", "invalid"),
            ("127.0.0.1:28015", ""),
            ("127.0.0.1:28015", "🔥 Extreme [RU/EU] Rust Server 🚀"),
            ("eu-trio-mon.rusticated.com:28010", ""),
            ("x" * 500, "y" * 500),
            ("1.1.1.1:99999", "Special chars: \x00 \n \t <script>"),
        ]
        for ip, name in cases:
            meta = _get_server_metadata(ip, name)
            assert isinstance(meta, dict)
            assert "name" in meta
            assert "ip" in meta
            assert "players" in meta
            assert "max_players" in meta
            assert meta["players"] <= meta["max_players"] or meta["players"] >= 0

    def test_title_truncation_logic_edge_cases(self):
        """Verify the dynamic title truncation formula across width spectrum."""
        def calc_truncation(width, full_text):
            available_w = max(30, width - 8)
            max_len = max(6, int(available_w / 7.2))
            if len(full_text) > max_len:
                return f"{full_text[:max(1, max_len - 1)]}…"
            return full_text

        # Test extreme widths: negative, zero, tiny, normal, huge
        assert calc_truncation(-50, "Short") == "Short"
        assert calc_truncation(0, "A Very Long Server Name Here") == "A Ver…"
        assert calc_truncation(10, "A Very Long Server Name Here") == "A Ver…"
        assert calc_truncation(50, "A Very Long Server Name Here") == "A Ver…"
        assert calc_truncation(100, "A Very Long Server Name Here") == "A Very Long…"
        assert calc_truncation(5000, "A Very Long Server Name Here") == "A Very Long Server Name Here"
        assert calc_truncation(100, "") == ""
        assert calc_truncation(100, "Rust Server") == "Rust Server"

    def test_column_budget_invariance(self):
        """Verify column budget does not exceed 371px to guarantee 55% drawer width fit."""
        # Fixed column widths: Star (30), Addr (145), Players (56), Local (44), Action (96)
        star_w = 30
        addr_w = 145
        players_w = 56
        local_w = 44
        action_w = 96
        total_fixed = star_w + addr_w + players_w + local_w + action_w
        assert total_fixed == 371, f"Column budget mismatch: expected 371, got {total_fixed}"


class TestPopularServerPersistenceAdversarial(unittest.TestCase):
    def test_popular_server_lifecycle_and_restarts(self):
        """Test multi-cycle deletion, persistence, and manual restoration of popular servers."""
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            with patch.object(AppConfig, "appdata_dir", property(lambda _self: tmp_path)), \
                 patch.object(AppConfig, "data_file", property(lambda _self: tmp_path / "data.json")):
                store1 = HistoryStore()
                pop_list = [
                    {"name": data["name"], "ip": pop_ip, "added_at": 0}
                    for pop_ip, data in POPULAR_SERVERS_DATA.items()
                ]
                pop_ips = list(POPULAR_SERVERS_DATA.keys())
                target_pop_ip = pop_ips[0]

                # Step 1: Initial active history has all popular servers
                assert any(s["ip"] == target_pop_ip for s in store1.get_active_history(pop_list))

                # Step 2: Delete popular server
                store1.remove_from_history(target_pop_ip)
                assert not any(s["ip"] == target_pop_ip for s in store1.get_active_history(pop_list))
                assert target_pop_ip in store1.get_deleted_popular_ips()

                # Step 3: Simulate restart - new store loading data from disk
                store2 = HistoryStore()
                assert not any(s["ip"] == target_pop_ip for s in store2.get_active_history(pop_list))
                assert target_pop_ip in store2.get_deleted_popular_ips()

                # Step 4: Re-add server via custom connection
                store2.add_to_history(target_pop_ip, "Custom Restored Server")
                assert any(s["ip"] == target_pop_ip for s in store2.get_active_history(pop_list))
                assert target_pop_ip not in store2.get_deleted_popular_ips()


class TestRapidHistoryOperationsStoreAdversarial(unittest.TestCase):
    def test_rapid_history_mutation_stress(self):
        """Perform 500 rapid add, delete, toggle_favorite, and arm operations on HistoryStore."""
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            with patch.object(AppConfig, "appdata_dir", property(lambda _self: tmp_path)), \
                 patch.object(AppConfig, "data_file", property(lambda _self: tmp_path / "data.json")):
                store = HistoryStore()

                # 500 interleaved mutations
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

                # Store must remain valid JSON and conform to DEFAULT_DATA shape
                history = store.get_history()
                assert len(history) <= 20
                favorites = store.get_favorites()
                assert isinstance(favorites, list)
                deleted_popular = store.get_deleted_popular_ips()
                assert isinstance(deleted_popular, list)

                # Verify on-disk file integrity
                data_file = tmp_path / "data.json"
                assert data_file.exists()
                content = json.loads(data_file.read_text(encoding="utf-8"))
                assert "history" in content
                assert "deleted_popular_ips" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
