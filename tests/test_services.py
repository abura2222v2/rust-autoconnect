import os
import unittest
from unittest.mock import patch, MagicMock
import subprocess

from src.services.leaderboard_service import LeaderboardService
from src.services.hardware_service import HardwareService
from src.services.swarm_service import SwarmService
from src.services.log_watcher import LogWatcher
from src.services.process_monitor import ProcessMonitor


class TestLeaderboardService(unittest.TestCase):
    def test_key_property(self):
        service = LeaderboardService()
        with patch.dict(os.environ, {"SUPABASE_KEY": "test_env_key"}):
            self.assertEqual(service.key, "test_env_key")
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(service.key, "")

    @patch("urllib.request.urlopen")
    def test_http_request_executor(self, mock_urlopen):
        mock_res = MagicMock()
        mock_res.getcode.return_value = 200
        mock_res.read.return_value = b'[{"username": "user1", "total_time": 10.5}]'
        mock_urlopen.return_value.__enter__.return_value = mock_res

        service = LeaderboardService()
        result = service.fetch_leaderboard()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["username"], "user1")


class TestHardwareService(unittest.TestCase):
    @patch("subprocess.check_output")
    def test_run_ps_timeout_handling(self, mock_check_output):
        mock_check_output.side_effect = subprocess.TimeoutExpired(cmd="powershell", timeout=5.0)
        hw = HardwareService()

        with patch("os.name", "nt"):
            res = hw._run_ps("Get-CPU")
            self.assertEqual(res, "Unknown")
            mock_check_output.assert_called_once()
            args, kwargs = mock_check_output.call_args
            self.assertEqual(kwargs.get("timeout"), 5.0)


class TestSwarmService(unittest.TestCase):
    def test_stop_disables_and_closes(self):
        swarm = SwarmService()
        swarm.is_enabled = True
        mock_ws = MagicMock()
        swarm.ws = mock_ws

        swarm.stop()
        self.assertFalse(swarm.is_enabled)
        mock_ws.close.assert_called_once()

    def test_secret_from_env(self):
        with patch.dict(os.environ, {"SWARM_SECRET": "custom_secret"}):
            swarm = SwarmService()
            self.assertEqual(swarm._secret, b"custom_secret")

    def test_heartbeat_loop_breaks_on_stale_ws(self):
        swarm = SwarmService()
        swarm.is_connected = True
        mock_ws1 = MagicMock()
        mock_ws2 = MagicMock()
        swarm.ws = mock_ws2

        # _on_open starts heartbeat thread
        with patch("threading.Thread") as mock_thread_cls:
            swarm._on_open(mock_ws1)
            # Find the heartbeat loop function passed to Thread
            call_args = mock_thread_cls.call_args
            self.assertIsNotNone(call_args)
            hb_func = call_args[1].get("target")
            current_ws = call_args[1].get("args")[0]
            self.assertEqual(current_ws, mock_ws1)

            mock_ws1.reset_mock()
            # Invoking hb_func when swarm.ws is mock_ws2 should break immediately without looping
            hb_func(mock_ws1)
            mock_ws1.send.assert_not_called()


class TestProcessMonitor(unittest.TestCase):
    @patch("subprocess.run")
    def test_force_kill_rust_timeout(self, mock_run):
        pm = ProcessMonitor()
        pm.force_kill_rust()
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        self.assertEqual(kwargs.get("timeout"), 5.0)


if __name__ == "__main__":
    unittest.main()
