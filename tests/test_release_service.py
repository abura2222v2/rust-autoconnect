import json
from unittest.mock import patch

from src.services.release_service import ReleaseService, is_newer_version


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class InvalidJsonResponse(FakeResponse):
    def read(self):
        return b"not-json"


def test_fetch_latest_version_reads_github_tag():
    with patch("urllib.request.urlopen", return_value=FakeResponse({"tag_name": "v2.0.0"})) as urlopen:
        assert ReleaseService().fetch_latest_version() == "v2.0.0"
    assert urlopen.call_args.kwargs["timeout"] == 3.0


def test_fetch_latest_version_returns_none_for_network_error():
    with patch("urllib.request.urlopen", side_effect=OSError("offline")):
        assert ReleaseService().fetch_latest_version() is None


def test_fetch_latest_version_returns_none_for_invalid_payload():
    with patch("urllib.request.urlopen", return_value=FakeResponse({"name": "release"})):
        assert ReleaseService().fetch_latest_version() is None


def test_fetch_latest_version_returns_none_for_malformed_json():
    with patch("urllib.request.urlopen", return_value=InvalidJsonResponse({})):
        assert ReleaseService().fetch_latest_version() is None


def test_is_newer_version_normalizes_v_prefix_and_missing_segments():
    assert is_newer_version("v1.4.0", "1.3.9")
    assert is_newer_version("1.3.1", "v1.3")
    assert not is_newer_version("v1.3.0", "1.3.0")
    assert not is_newer_version("release-2", "v1.3.0")
