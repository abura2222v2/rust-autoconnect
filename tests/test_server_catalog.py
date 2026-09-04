"""Tests for src/services/server_catalog.py (moved out of the legacy Tkinter
GUI module during its removal - this data/lookup logic has no GUI
dependency, so it's tested standalone here)."""
from src.services.server_catalog import POPULAR_SERVERS_DATA, get_server_metadata


def test_catalog_no_longer_carries_fabricated_community_links():
    """website/discord/rules/rustmaps_url used to be hand-typed guesses here
    (verified 2026-09-04: several were simply wrong, e.g. a Discord invite
    for the official Facepunch server that doesn't exist). Real, per-server
    values now come only from server_intelligence_service - this catalog
    must not offer fields that look like real data but aren't."""
    for ip, data in POPULAR_SERVERS_DATA.items():
        for key in ("website", "discord", "rules", "rustmaps_url"):
            assert key not in data, f"{ip} still carries a guessed '{key}'"

    meta = get_server_metadata("203.0.113.99:28015", "Some Unlisted Server")
    for key in ("website", "discord", "rules", "rustmaps_url"):
        assert key not in meta, f"unlisted-server fallback still fabricates '{key}'"


def test_server_metadata_adversarial_inputs():
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
        meta = get_server_metadata(ip, name)
        assert isinstance(meta, dict)
        assert "name" in meta
        assert "ip" in meta
        assert "players" in meta
        assert "max_players" in meta
        assert meta["players"] <= meta["max_players"] or meta["players"] >= 0
