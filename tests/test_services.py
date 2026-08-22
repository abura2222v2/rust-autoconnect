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
    def test_api_configuration_does_not_use_supabase_key(self):
        service = LeaderboardService()
        with patch.dict(os.environ, {"BENCHMARK_API_URL": "https://example.invalid"}):
            self.assertEqual(service.api_url, "https://example.invalid")
            self.assertTrue(service.is_configured)
        with patch.dict(os.environ, {}, clear=True):
            # Bundled public configuration remains available without an env
            # file; the service must not require or expose a Supabase secret.
            self.assertNotIn("SUPABASE_KEY", service.api_url)
            self.assertNotIn("sb_secret", service.api_url)

    @patch("urllib.request.urlopen")
    def test_http_request_executor(self, mock_urlopen):
        mock_res = MagicMock()
        mock_res.getcode.return_value = 200
        mock_res.read.return_value = b'{"items": [{"configuration_key": "a", "median_total_time": 10.5}]}'
        mock_urlopen.return_value.__enter__.return_value = mock_res

        service = LeaderboardService()
        with patch.dict(os.environ, {"BENCHMARK_API_URL": "https://example.invalid"}):
            result = service.fetch_configurations()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["configuration_key"], "a")

    @patch("urllib.request.urlopen")
    def test_run_submission_omits_local_sync_state(self, mock_urlopen):
        mock_res = MagicMock()
        mock_res.getcode.return_value = 201
        mock_res.read.return_value = b""
        mock_urlopen.return_value.__enter__.return_value = mock_res

        service = LeaderboardService()
        run = {
            "id": "run", "installation_id": "local", "configuration_key": "configuration",
            "cpu": "CPU Model", "storage": "Disk Model", "storage_bus": "NVMe",
            "benchmark_version": "v1", "time_to_menu": 5.0, "demo_load_time": 5.5,
            "total_time": 10.5, "created_at": 1, "sync_state": "pending", "serial": "do-not-send",
        }
        with patch.dict(os.environ, {"BENCHMARK_API_URL": "https://example.invalid"}):
            assert service.submit_run(run)

        payload = mock_urlopen.call_args.args[0].data.decode("utf-8")
        self.assertNotIn("sync_state", payload)
        self.assertNotIn("serial", payload)
        self.assertNotIn("SUPABASE_KEY", payload)


class TestHardwareService(unittest.TestCase):
    @patch("subprocess.check_output")
    def test_run_ps_timeout_handling(self, mock_check_output):
        mock_check_output.side_effect = subprocess.TimeoutExpired(cmd="powershell", timeout=5.0)
        hw = HardwareService(auto_start=False)

        with patch("os.name", "nt"):
            res = hw._run_ps("Get-CPU")
            self.assertEqual(res, "Unknown")
            mock_check_output.assert_called_once()
            args, kwargs = mock_check_output.call_args
            self.assertEqual(kwargs.get("timeout"), 5.0)

    def test_benchmark_storage_uses_the_rust_drive(self):
        hw = HardwareService()
        with patch("os.name", "nt"), patch.object(hw, "_run_ps", return_value='{"model":"External SSD","bus":"USB"}') as run_ps:
            assert hw.get_benchmark_storage("E:\\Steam\\Rust") == ("External SSD", "USB")
        self.assertIn("DriveLetter 'E'", run_ps.call_args.args[0])


class TestSwarmService(unittest.TestCase):
    def test_stop_disables_and_closes(self):
        swarm = SwarmService()
        swarm.is_enabled = True
        mock_ws = MagicMock()
        swarm.ws = mock_ws

        swarm.stop()
        self.assertFalse(swarm.is_enabled)
        mock_ws.close.assert_called_once()

    def test_shared_secret_is_not_part_of_client_configuration(self):
        with patch.dict(os.environ, {"SWARM_SECRET": "custom_secret"}):
            swarm = SwarmService()
        self.assertFalse(hasattr(swarm, "_secret"))

    def test_status_reports_missing_configuration(self):
        swarm = SwarmService()
        swarm.supabase_key = ""
        statuses = []
        swarm.on_status = statuses.append
        swarm.is_enabled = True

        swarm.start()

        self.assertEqual(statuses, ["not_configured"])

    def test_personal_access_token_is_rejected_for_realtime_client(self):
        swarm = SwarmService()
        swarm.supabase_key = "sbp_example"
        statuses = []
        swarm.on_status = statuses.append
        swarm.is_enabled = True

        swarm.start()

        self.assertFalse(swarm.is_configured)
        self.assertEqual(statuses, ["invalid_key"])

    def test_legacy_service_role_jwt_is_rejected_for_realtime_client(self):
        # The payload is deliberately unsigned: this test only exercises the
        # local role guard, not JWT verification.
        service_role_jwt = "eyJhbGciOiJub25lIn0.eyJyb2xlIjoic2VydmljZV9yb2xlIn0."
        self.assertFalse(SwarmService._is_public_supabase_key(service_role_jwt))

    def test_heartbeat_loop_breaks_on_stale_ws(self):
        swarm = SwarmService()
        swarm.is_connected = True
        mock_ws1 = MagicMock()
        mock_ws2 = MagicMock()
        swarm.ws = mock_ws2

        # A late callback from the old socket must not affect the current socket.
        with patch("threading.Thread") as mock_thread_cls:
            swarm._on_open(mock_ws1)
            mock_thread_cls.assert_not_called()
            self.assertTrue(swarm.is_connected)

    def test_stale_endpoint_is_never_broadcast_into_new_room(self):
        swarm = SwarmService()
        swarm.is_enabled = True
        swarm.is_connected = True
        swarm.current_ip_port = "203.0.113.20:28015"
        swarm.current_room = "realtime:room_203_0_113_20_28015"
        swarm.ws = MagicMock()

        swarm.broadcast_success("203.0.113.10:28015")

        swarm.ws.send.assert_not_called()


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
