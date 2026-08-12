from unittest.mock import patch

from src.services.telegram_service import TelegramService


def test_link_uses_edge_function_and_persists_only_returned_notification_token(tmp_path):
    service = TelegramService()
    service.data_file = tmp_path / "telegram.json"
    service.client_id = "00000000-0000-4000-8000-000000000001"

    with patch.object(service, "_request", return_value={"accepted": True, "notification_token": "local-token"}) as request:
        code = service.generate_link_code("RU")

    assert code and len(code) == 8
    assert service.notification_token == "local-token"
    assert request.call_args.args[0] == "link"
    assert request.call_args.args[1]["locale"] == "RU"
    assert service.data_file.exists()


def test_notifications_use_named_event_not_raw_message(tmp_path):
    service = TelegramService()
    service.data_file = tmp_path / "telegram.json"
    service.client_id = "00000000-0000-4000-8000-000000000001"
    service.notification_token = "local-token"

    with patch.object(service, "_request", return_value={"accepted": True}) as request:
        assert service.notify_queue(4, "127.0.0.1:28015")

    path, payload = request.call_args.args
    assert path == "notify"
    assert payload["event"] == "queue"
    assert "message" not in payload


def test_queue_notification_carries_a_single_crossed_level_and_session(tmp_path):
    service = TelegramService()
    service.data_file = tmp_path / "telegram.json"
    service.client_id = "00000000-0000-4000-8000-000000000001"
    service.notification_token = "local-token"

    with patch.object(service, "_request", return_value={"accepted": True}) as request:
        assert service.notify_queue(28, "127.0.0.1:28015", level=30, queue_session_id="a" * 32)

    details = request.call_args.args[1]["details"]
    assert details == {"position": 28, "level": 30, "queue_session_id": "a" * 32}


def test_unknown_notification_event_is_rejected_without_network_call():
    service = TelegramService()
    service.client_id = "client"
    service.notification_token = "token"
    with patch.object(service, "_request") as request:
        assert not service.notify("unknown", "server:28015")
    request.assert_not_called()


def test_link_status_persists_display_name_and_clears_expired_pairing_code(tmp_path):
    service = TelegramService()
    service.data_file = tmp_path / "telegram.json"
    service.client_id = "00000000-0000-4000-8000-000000000001"
    service.notification_token = "local-token"
    service.link_code = "ABC12345"

    with patch.object(service, "_request", return_value={"linked": True, "display_name": "@player"}) as request:
        status = service.get_link_status()

    assert status == {"linked": True, "display_name": "@player"}
    assert service.display_name == "@player"
    assert service.is_linked is True
    assert service.link_code is None
    assert request.call_args.args[0] == "status"
    assert '"display_name": "@player"' in service.data_file.read_text(encoding="utf-8")


def test_link_status_without_local_token_does_not_call_network():
    service = TelegramService()
    service.client_id = "00000000-0000-4000-8000-000000000001"
    service.notification_token = None

    with patch.object(service, "_request") as request:
        assert service.get_link_status() == {"linked": False, "display_name": None}

    request.assert_not_called()


def test_unlink_clears_the_local_pairing_state_after_server_accepts(tmp_path):
    service = TelegramService()
    service.data_file = tmp_path / "telegram.json"
    service.client_id = "00000000-0000-4000-8000-000000000001"
    service.notification_token = "local-token"
    service.display_name = "@player"
    service.is_linked = True

    with patch.object(service, "_request", return_value={"accepted": True}) as request:
        assert service.unlink()

    assert service.notification_token is None
    assert service.display_name is None
    assert service.is_linked is False
    assert request.call_args.args == ("unlink", {"client_id": service.client_id, "notification_token": "local-token"})


def test_locale_update_is_saved_and_sent_only_for_a_linked_installation(tmp_path):
    service = TelegramService()
    service.data_file = tmp_path / "telegram.json"
    service.client_id = "00000000-0000-4000-8000-000000000001"
    service.notification_token = "local-token"

    with patch.object(service, "_request", return_value={"accepted": True}) as request:
        assert service.update_locale("RU")

    assert service.locale == "RU"
    assert request.call_args.args == ("locale", {"client_id": service.client_id, "notification_token": "local-token", "locale": "RU"})
