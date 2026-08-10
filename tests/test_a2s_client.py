from types import SimpleNamespace
from unittest.mock import patch

from src.core.a2s_client import A2SClient


def test_returns_first_valid_offset_and_caches_it():
    client = A2SClient(timeout=0.01, offsets=(0, 15))

    def query(address, timeout):
        if address[1] == 28030:
            return SimpleNamespace(server_name="Rust Test", max_players=100)
        raise OSError("offline")

    with patch("a2s.info", side_effect=query) as info:
        assert client.check_server_alive("127.0.0.1", 28015) == (True, "Rust Test", 100, 28030)
        assert client.check_server_alive("127.0.0.1", 28015) == (True, "Rust Test", 100, 28030)
    assert info.call_args_list[-1].args[0][1] == 28030


def test_stopped_probe_does_not_call_network():
    import threading

    stop_event = threading.Event()
    stop_event.set()
    with patch("a2s.info") as info:
        assert A2SClient().check_server_alive("127.0.0.1", 28015, stop_event) == (False, "", 0, 28015)
    info.assert_not_called()


def test_invalid_base_port_returns_offline():
    assert A2SClient().check_server_alive("127.0.0.1", 0) == (False, "", 0, 0)


def test_status_exposes_capacity_without_breaking_legacy_tuple():
    client = A2SClient(timeout=0.01, offsets=(0,))

    class Info:
        server_name = "Rust Test"
        map_name = "Procedural Map"
        player_count = 99
        max_players = 100

    with patch("a2s.info", return_value=Info()):
        status = client.get_server_status("127.0.0.1", 28015)
        assert status.alive and status.has_join_capacity
        assert status.map_name == "Procedural Map"
        assert client.check_server_alive("127.0.0.1", 28015) == (True, "Rust Test", 100, 28015)
