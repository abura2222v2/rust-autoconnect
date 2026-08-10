import json
from unittest.mock import patch

from src.services.server_intelligence_service import ServerIntelligenceService


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
