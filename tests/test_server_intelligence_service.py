import json
import time
import urllib.error
from unittest.mock import MagicMock, patch

from src.services.server_intelligence_service import (
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
    payload = json.loads(request.call_args.args[0].data.decode("utf-8"))
    assert payload == {"endpoint": "example.test:28015", "active": False}


def test_snapshot_preserves_provider_status_without_treating_empty_as_offline():
    service = configured_service()
    with patch("urllib.request.urlopen", return_value=FakeResponse({
        "online": True, "players": 0, "max_players": 200,
        "checked_at": "2026-08-12T12:00:00Z", "fresh": True,
    })):
        snapshot = service.observe_endpoint("example.test:28015", active=True)

    assert snapshot.online is True
    assert snapshot.players == 0
    assert snapshot.max_players == 200
    assert snapshot.fresh is True


def test_force_refresh_bypasses_the_short_lived_client_cache():
    service = configured_service()
    with patch("urllib.request.urlopen", side_effect=[
        FakeResponse({"status": "refreshing"}),
        FakeResponse({"status": "ready", "players": 12}),
    ]) as request:
        first = service.observe_endpoint("example.test:28015", active=False)
        second = service.observe_endpoint("example.test:28015", active=False, force_refresh=True)

    assert first.status == "refreshing"
    assert second.status == "ready"
    assert second.players == 12
    assert request.call_count == 2


def test_snapshot_parses_safe_game_monitoring_card_fields_and_query_port():
    service = configured_service()
    with patch("urllib.request.urlopen", return_value=FakeResponse({
        "status": "ready", "server_id": 5446410, "query_port": 28015,
        "name": "Example", "players": 300, "max_players": 350,
        "map": "Custom Map", "seed": 1337, "map_size": 4750,
        "version": "2632", "description": "Public description", "website": "https://example.test",
        "checked_at": "2026-08-12T12:00:00Z", "fresh": True,
    })) as request:
        snapshot = service.observe_endpoint("203.0.113.10:28010", active=True, query_port=28015)

    assert snapshot.server_id == 5446410
    assert snapshot.query_port == 28015
    assert snapshot.players == 300
    assert snapshot.map_seed == 1337
    assert snapshot.website == "https://example.test"
    payload = json.loads(request.call_args.args[0].data.decode("utf-8"))
    assert payload["query_port"] == 28015


def test_snapshot_parses_discord_rules_and_rustmaps_fields():
    """These fields were added after the backend learned to parse bare-domain
    community links ("Discord: discord.gg/x") out of the server's own
    description, and to resolve a real per-seed RustMaps.com link - both were
    previously always empty on the client no matter what the backend sent."""
    service = configured_service()
    with patch("urllib.request.urlopen", return_value=FakeResponse({
        "status": "ready", "discord": "https://discord.gg/RealCommunity",
        "rules": "https://real-community.example/rules",
        "rustmaps_url": "https://rustmaps.com/map/abc123",
        "rustmaps_image_url": "https://data.rustmaps.com/maps/abc123/map.png",
    })):
        snapshot = service.observe_endpoint("203.0.113.11:28015", active=True)

    assert snapshot.discord == "https://discord.gg/RealCommunity"
    assert snapshot.rules == "https://real-community.example/rules"
    assert snapshot.rustmaps_url == "https://rustmaps.com/map/abc123"
    assert snapshot.rustmaps_image_url == "https://data.rustmaps.com/maps/abc123/map.png"


def test_share_deduplicates_and_limits_addresses():
    service = configured_service()
    endpoints = ["example.test:28015"] * 2 + [f"s{i}.test:28015" for i in range(30)]
    with patch("urllib.request.urlopen", return_value=FakeResponse({"accepted": True})) as request:
        assert service.share_saved_endpoints(endpoints)

    payload = json.loads(request.call_args.args[0].data.decode("utf-8"))
    assert payload["endpoints"][0] == "example.test:28015"
    assert len(payload["endpoints"]) == 20


def test_availability_report_sends_only_endpoint():
    service = configured_service()
    with patch("urllib.request.urlopen", return_value=FakeResponse({"accepted": True})) as request:
        service.report_available("example.test:28015")

    payload = json.loads(request.call_args.args[0].data.decode("utf-8"))
    assert payload == {"endpoint": "example.test:28015"}




