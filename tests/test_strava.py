import json
import time

import pytest

from daum_bridge.integrations.strava import (
    StravaClient,
    StravaError,
    _encode_multipart,
)

RIDE = {
    "id": "2026-01-02T10-00-00",
    "start": 1767348000.0,
    "duration": 60.0,
    "distance": 0.5,
    "avg_power": 200.0,
    "max_power": 300.0,
    "work_kj": 20.0,
    "samples": [
        {"t": 0, "power": 100, "cadence": 80, "speed": 30, "heart_rate": 130, "distance": 0.0},
        {"t": 60, "power": 200, "cadence": 90, "speed": 35, "heart_rate": 140, "distance": 0.5},
    ],
}

# A path that is never written by the tests, so no cached user tokens leak in.
NO_TOKENS = "daum-bridge-test-missing-tokens.json"


class FakeClient(StravaClient):
    def __init__(self, responses, **kwargs):
        kwargs.setdefault("access_token", "test-token")
        kwargs.setdefault("poll_interval", 0.0)
        super().__init__(**kwargs)
        self.responses = list(responses)
        self.calls = []

    def _request(self, method, url, data=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "data": data, "headers": headers or {}})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        status, payload = response
        if isinstance(payload, dict):
            payload = json.dumps(payload).encode("utf-8")
        return status, payload


def _json_response(payload):
    return 200, payload


def test_encode_multipart():
    body, boundary = _encode_multipart(
        {"data_type": "tcx", "trainer": "1"},
        {"file": ("ride.tcx", b"<xml/>", "application/vnd.garmin.tcx+xml")},
    )
    assert body.startswith(f"--{boundary}\r\n".encode())
    assert body.endswith(f"--{boundary}--\r\n".encode())
    assert b'name="data_type"\r\n\r\ntcx' in body
    assert b'filename="ride.tcx"' in body
    assert b"<xml/>" in body


def test_is_configured_variants():
    assert StravaClient(token_file=NO_TOKENS).is_configured() is False
    assert StravaClient(access_token="abc", token_file=NO_TOKENS).is_configured() is True
    assert StravaClient(refresh_token="ref", token_file=NO_TOKENS).is_configured() is False
    assert (
        StravaClient(
            client_id="id",
            client_secret="secret",
            refresh_token="ref",
            token_file=NO_TOKENS,
        ).is_configured()
        is True
    )


def test_upload_immediate_success(tmp_path):
    client = FakeClient(
        [_json_response({"id": 11, "activity_id": 4242, "status": "ready"})],
        token_file=str(tmp_path / "tokens.json"),
    )
    result = client.upload_ride(RIDE)
    assert result["ok"] is True
    assert result["activity_id"] == 4242

    upload_call = client.calls[0]
    assert upload_call["url"].endswith("/uploads")
    assert upload_call["headers"]["Authorization"] == "Bearer test-token"
    assert b'name="data_type"\r\n\r\ntcx' in upload_call["data"]
    assert b'name="external_id"\r\n\r\ndaum-2026-01-02T10-00-00' in upload_call["data"]
    assert b'name="trainer"\r\n\r\n1' in upload_call["data"]


def test_upload_polls_until_processed(tmp_path):
    client = FakeClient(
        [
            _json_response({"id": 7, "activity_id": None, "status": "processing"}),
            _json_response({"id": 7, "activity_id": None, "status": "processing"}),
            _json_response({"id": 7, "activity_id": 99, "status": "ready"}),
        ],
        token_file=str(tmp_path / "tokens.json"),
    )
    result = client.upload_ride(RIDE)
    assert result["ok"] is True
    assert result["activity_id"] == 99
    assert len(client.calls) == 3
    assert client.calls[1]["url"].endswith("/uploads/7")


def test_upload_timeout(tmp_path):
    client = FakeClient(
        [
            _json_response({"id": 7, "activity_id": None}),
            _json_response({"id": 7, "activity_id": None}),
        ],
        token_file=str(tmp_path / "tokens.json"),
        poll_timeout=0,
    )
    result = client.upload_ride(RIDE)
    assert result["ok"] is False
    assert "Timed out" in result["error"]


def test_upload_api_error_is_returned(tmp_path):
    client = FakeClient(
        [StravaError("Strava API error (400): bad file")],
        token_file=str(tmp_path / "tokens.json"),
    )
    result = client.upload_ride(RIDE)
    assert result["ok"] is False
    assert "bad file" in result["error"]


def test_upload_rejected_status_error(tmp_path):
    client = FakeClient(
        [
            _json_response({"id": 7, "activity_id": None}),
            _json_response({"id": 7, "error": "duplicate of activity 1"}),
        ],
        token_file=str(tmp_path / "tokens.json"),
    )
    result = client.upload_ride(RIDE)
    assert result["ok"] is False
    assert "duplicate" in result["error"]


def test_upload_when_not_configured(tmp_path):
    client = StravaClient(token_file=str(tmp_path / "tokens.json"))
    result = client.upload_ride(RIDE)
    assert result["ok"] is False
    assert "not configured" in result["error"]


def test_refresh_token_flow(tmp_path):
    token_file = tmp_path / "tokens.json"
    client = FakeClient(
        [
            _json_response(
                {
                    "access_token": "fresh-token",
                    "refresh_token": "fresh-refresh",
                    "expires_at": time.time() + 3600,
                }
            ),
            _json_response({"id": 1, "activity_id": 2, "status": "ready"}),
        ],
        client_id="client",
        client_secret="secret",
        refresh_token="old-refresh",
        access_token="",
        token_file=str(token_file),
    )
    result = client.upload_ride(RIDE)
    assert result["ok"] is True
    assert client.refresh_token == "fresh-refresh"

    token_call = client.calls[0]
    assert token_call["url"].endswith("/oauth/token")
    assert b"grant_type=refresh_token" in token_call["data"]
    assert b"refresh_token=old-refresh" in token_call["data"]
    assert client.calls[1]["headers"]["Authorization"] == "Bearer fresh-token"

    cached = json.loads(token_file.read_text())
    assert cached["access_token"] == "fresh-token"
    assert cached["refresh_token"] == "fresh-refresh"


def test_cached_tokens_are_reused(tmp_path):
    token_file = tmp_path / "tokens.json"
    token_file.write_text(
        json.dumps(
            {
                "access_token": "cached-token",
                "refresh_token": "cached-refresh",
                "expires_at": time.time() + 3600,
            }
        )
    )
    client = StravaClient(
        client_id="id",
        client_secret="secret",
        refresh_token="cached-refresh",
        token_file=str(token_file),
    )
    assert client.access_token == "cached-token"
    assert client.refresh_access_token() == "cached-token"


def test_refresh_without_credentials_raises(tmp_path):
    client = StravaClient(refresh_token="ref", token_file=NO_TOKENS)
    with pytest.raises(StravaError):
        client.refresh_access_token()


def test_exchange_code_saves_tokens(tmp_path):
    token_file = tmp_path / "tokens.json"
    client = FakeClient(
        [
            _json_response(
                {
                    "access_token": "new-access",
                    "refresh_token": "new-refresh",
                    "expires_at": time.time() + 3600,
                }
            )
        ],
        client_id="id",
        client_secret="secret",
        token_file=str(token_file),
    )
    client.exchange_code("auth-code", redirect_uri="http://localhost")
    assert client.refresh_token == "new-refresh"
    assert json.loads(token_file.read_text())["refresh_token"] == "new-refresh"
    assert b"grant_type=authorization_code" in client.calls[0]["data"]


def test_authorization_url():
    client = StravaClient(client_id="123", token_file=NO_TOKENS)
    url = client.authorization_url(redirect_uri="http://localhost", scope="activity:write")
    assert url.startswith("https://www.strava.com/oauth/authorize?")
    assert "client_id=123" in url
    assert "response_type=code" in url
    assert "scope=activity%3Awrite" in url


def test_from_config():
    class Cfg:
        client_id = "id"
        client_secret = "secret"
        refresh_token = "refresh"
        access_token = ""
        token_file = NO_TOKENS
        poll_timeout = 60

    client = StravaClient.from_config(Cfg())
    assert client.client_id == "id"
    assert client.poll_timeout == 60
    assert client.is_configured()
