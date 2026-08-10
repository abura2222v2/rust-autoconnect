import json
import time
import urllib.error
from unittest.mock import MagicMock, patch

from src.services.server_intelligence_service import (
    BattleMetricsAPIClient,
    ServerIntelligenceWorker,
    ServerIntelligenceService,
)


class FakeResponse:
    def __init__(self, body):
        self._body = body

    def read(self):
        return json.dumps(self._body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def configured_service():
    service = ServerIntelligenceService()
    service.api_url = "https://example.invalid/functions/v1"
    service.public_key = "sb_publishable_test"
    return service


def test_schedule_is_read_once_then_cached():
    service = configured_service()
    with patch("urllib.request.urlopen", return_value=FakeResponse({"wipe_at": 1_800_000_000, "source": "provider", "confidence": "high"})) as request:
        first = service.get_schedule("example.test:28015")
        second = service.get_schedule("example.test:28015")

    assert first.wipe_at == 1_800_000_000
    assert first.source == "provider"
    assert second == first
    assert request.call_count == 1


def test_availability_report_sends_only_endpoint():
    service = configured_service()
    with patch("urllib.request.urlopen", return_value=FakeResponse({"accepted": True})) as request:
        service.report_available("example.test:28015")

    payload = json.loads(request.call_args.args[0].data.decode("utf-8"))
    assert payload == {"endpoint": "example.test:28015"}


def test_battlemetrics_api_client_without_token():
    client = BattleMetricsAPIClient()
    mock_payload = {
        "data": [
            {
                "attributes": {
                    "players": 42,
                    "maxPlayers": 100,
                    "status": "online",
                    "details": {
                        "rust_wipe_time": "2026-08-01T18:00:00.000Z"
                    }
                }
            }
        ]
    }
    with patch("urllib.request.urlopen", return_value=FakeResponse(mock_payload)) as mock_urlopen:
        result = client.get_server_info("192.168.1.1:28015")

    assert result is not None
    assert result["players"] == 42
    assert result["maxPlayers"] == 100
    assert result["status"] == "online"
    assert result["rust_wipe_time"] == "2026-08-01T18:00:00.000Z"

    req = mock_urlopen.call_args[0][0]
    assert "Authorization" not in req.headers
    assert req.full_url == "https://api.battlemetrics.com/servers?filter[search]=192.168.1.1:28015&game=rust"


def test_battlemetrics_api_client_with_token():
    client = BattleMetricsAPIClient(api_token="my_secret_token")
    mock_payload = {
        "data": [
            {
                "attributes": {
                    "players": 10,
                    "maxPlayers": 50,
                    "status": "online",
                    "details": {
                        "rust_wipe_time": "2026-08-05T12:00:00.000Z"
                    }
                }
            }
        ]
    }
    with patch("urllib.request.urlopen", return_value=FakeResponse(mock_payload)) as mock_urlopen:
        result = client.get_server_info("10.0.0.1", port=28015)

    assert result is not None
    assert result["players"] == 10
    assert result["maxPlayers"] == 50

    req = mock_urlopen.call_args[0][0]
    assert req.headers.get("Authorization") == "Bearer my_secret_token"
    assert "10.0.0.1:28015" in req.full_url


def test_battlemetrics_api_client_http_errors():
    client = BattleMetricsAPIClient()

    # 403 Forbidden
    err_403 = urllib.error.HTTPError("https://api.battlemetrics.com", 403, "Forbidden", {}, None)
    with patch("urllib.request.urlopen", side_effect=err_403):
        res = client.get_server_info("192.168.1.1:28015")
        assert res is None

    # 429 Rate Limit
    err_429 = urllib.error.HTTPError("https://api.battlemetrics.com", 429, "Too Many Requests", {}, None)
    with patch("urllib.request.urlopen", side_effect=err_429):
        res = client.get_server_info("192.168.1.1:28015")
        assert res is None

    # Timeout error
    err_timeout = urllib.error.URLError("timed out")
    with patch("urllib.request.urlopen", side_effect=err_timeout):
        res = client.get_server_info("192.168.1.1:28015")
        assert res is None


def test_battlemetrics_api_client_empty_response():
    client = BattleMetricsAPIClient()
    with patch("urllib.request.urlopen", return_value=FakeResponse({"data": []})):
        res = client.get_server_info("192.168.1.1:28015")
        assert res is None


def test_server_intelligence_worker_polling_and_thread_safety():
    mock_api = MagicMock(spec=BattleMetricsAPIClient)
    mock_api.get_server_info.return_value = {
        "players": 75,
        "maxPlayers": 100,
        "status": "online",
        "rust_wipe_time": "2026-08-10T12:00:00Z",
    }

    worker = ServerIntelligenceWorker("192.168.1.1:28015", api_client=mock_api, poll_interval=0.05)
    assert worker.latest_status == {}

    worker.start()
    time.sleep(0.15)
    status = worker.latest_status

    assert status["players"] == 75
    assert status["maxPlayers"] == 100
    assert status["status"] == "online"

    # Test thread safety / copy immutability
    status["players"] = 999
    assert worker.latest_status["players"] == 75

    worker.stop()
    worker.join(timeout=2.0)
    assert not worker.is_alive()

