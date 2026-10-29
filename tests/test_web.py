from daum_bridge.web.app import create_app
from daum_bridge.config import Config
from daum_bridge.bridge import DaumBridge
from fastapi.testclient import TestClient

import json

import pytest

from daum_bridge import history
from daum_bridge.integrations.strava import StravaClient


@pytest.fixture
def bridge():
    """A bridge with default configuration; no serial port is opened."""
    return DaumBridge(Config())


@pytest.fixture
def client(bridge):
    """A test client bound to a fresh bridge (and therefore a fresh app)."""
    return TestClient(create_app(bridge))


def test_create_app(bridge):
    app = create_app(bridge)
    assert app is not None


def test_index_route(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_config_route(client):
    resp = client.get("/config")
    assert resp.status_code == 200


def test_api_state(client):
    resp = client.get("/api/state")
    assert resp.status_code == 200
    data = resp.json()
    assert "connected" in data


def test_api_status(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200


def test_api_diagnostics(client):
    resp = client.get("/api/diagnostics")
    assert resp.status_code == 200


def test_api_config_get(client):
    resp = client.get("/api/config")
    assert resp.status_code == 200


def test_api_config_round_trips_ant_and_max_gear(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text(
        "bridge:\n"
        "  max_gear: 24\n"
        "ant:\n"
        "  enabled: false\n"
        "  device_id: 0\n"
        "  network_key: ''\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    app = create_app(DaumBridge(Config()))
    client = TestClient(app)

    data = client.get("/api/config").json()
    assert data["bridge"]["max_gear"] == 24
    assert data["ant"] == {"enabled": False, "device_id": 0, "network_key": ""}

    resp = client.post(
        "/api/config",
        json={"ant": {"enabled": True, "device_id": 1234, "network_key": "B9 A5 21 FB BD 72 C3 45"},
              "bridge": {"max_gear": 12}},
    )
    assert resp.status_code == 200

    saved = Config.load(tmp_path / "config.yaml")
    assert saved.ant.enabled is True
    assert saved.ant.device_id == 1234
    assert saved.ant.network_key == "B9 A5 21 FB BD 72 C3 45"
    assert saved.bridge.max_gear == 12


def test_shift_up(client):
    resp = client.post("/api/shift/up")
    assert resp.status_code == 200


def test_shift_down(client):
    resp = client.post("/api/shift/down")
    assert resp.status_code == 200


def test_set_gear(client):
    resp = client.post("/api/gear/5")
    assert resp.status_code == 200


def test_set_target_watt(client):
    resp = client.post("/api/target/watt", json={"watts": 150})
    assert resp.status_code == 200


def test_api_strava_status():
    cfg = Config()
    cfg.strava.token_file = "daum-bridge-test-missing-tokens.json"
    bridge = DaumBridge(cfg)
    app = create_app(bridge)
    client = TestClient(app)
    resp = client.get("/api/strava/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "configured" in data
    assert "auto_upload" in data


def test_strava_upload_unknown_ride(client):
    resp = client.post("/api/strava/upload", json={"ride_id": "no-such-ride"})
    assert resp.status_code == 404


def test_download_ride_tcx(tmp_path, monkeypatch, client):
    monkeypatch.setenv("DAUM_RIDES_DIR", str(tmp_path))
    ride_id = history.save_ride(
        {
            "start": 1761732000.0,
            "duration": 60.0,
            "distance": 0.5,
            "avg_power": 200.0,
            "samples": [
                {"t": 0, "power": 100, "cadence": 80, "speed": 30, "distance": 0},
                {"t": 60, "power": 200, "cadence": 90, "speed": 35, "distance": 0.5},
            ],
        },
        directory=tmp_path,
    )

    resp = client.get(f"/api/rides/{ride_id}/tcx")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/vnd.garmin.tcx+xml")
    assert f'filename="{ride_id}.tcx"' in resp.headers["content-disposition"]
    body = resp.content.decode("utf-8")
    assert "<TrainingCenterDatabase" in body
    assert "garmin:Watts" in body


def test_download_ride_tcx_unknown(tmp_path, monkeypatch, client):
    monkeypatch.setenv("DAUM_RIDES_DIR", str(tmp_path))
    resp = client.get("/api/rides/does-not-exist/tcx")
    assert resp.status_code == 404


def test_downloads_page_lists_rides_newest_first(tmp_path, monkeypatch, client):
    monkeypatch.setenv("DAUM_RIDES_DIR", str(tmp_path))
    older = history.save_ride(
        {
            "start": 1761732000.0,
            "duration": 1200.0,
            "distance": 8.4,
            "avg_power": 180.0,
            "max_power": 320.0,
            "work_kj": 60.0,
            "samples": [{"t": 0, "power": 150, "cadence": 80, "speed": 25, "distance": 0}],
        },
        directory=tmp_path,
    )
    newer = history.save_ride(
        {
            "start": 1761735600.0,
            "duration": 2400.0,
            "distance": 20.1,
            "avg_power": 210.0,
            "max_power": 410.0,
            "work_kj": 140.0,
            "samples": [{"t": 0, "power": 200, "cadence": 90, "speed": 30, "distance": 0}],
        },
        directory=tmp_path,
    )

    resp = client.get("/downloads")
    assert resp.status_code == 200
    body = resp.text
    assert f"/api/rides/{older}/tcx" in body
    assert f"/api/rides/{newer}/tcx" in body
    # Newest training must be listed first.
    assert body.index(f"/api/rides/{newer}/tcx") < body.index(f"/api/rides/{older}/tcx")


def test_downloads_page_without_rides(tmp_path, monkeypatch, client):
    monkeypatch.setenv("DAUM_RIDES_DIR", str(tmp_path))
    resp = client.get("/downloads")
    assert resp.status_code == 200
    assert "No trainings recorded yet" in resp.text


def test_finish_ride_endpoint_writes_tcx(tmp_path, monkeypatch, bridge, client):
    monkeypatch.setenv("DAUM_RIDES_DIR", str(tmp_path))
    bridge.state.connected = True
    bridge.state.power = 200
    bridge._update_ride_stats()

    resp = client.post("/api/ride/finish")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    ride_id = data["ride"]["id"]
    assert data["tcx_url"] == f"/api/rides/{ride_id}/tcx"
    assert (tmp_path / f"{ride_id}.tcx").exists()
    assert bridge._current_ride is None
    assert client.get("/api/state").json()["ride_paused"] is True

    assert client.post("/api/ride/finish").status_code == 400

    resp = client.post("/api/ride/resume")
    assert resp.status_code == 200
    assert bridge._current_ride is not None
    assert client.get("/api/state").json()["ride_paused"] is False


def test_email_status_default(tmp_path, monkeypatch, client):
    monkeypatch.setenv("DAUM_RIDES_DIR", str(tmp_path))
    for name in (
        "DAUM_EMAIL_HOST",
        "DAUM_EMAIL_TO",
        "DAUM_EMAIL_FROM",
    ):
        monkeypatch.delenv(name, raising=False)
    resp = client.get("/api/email/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is False
    assert data["auto_send"] is False


def test_email_ride_endpoint(tmp_path, monkeypatch, bridge, client):
    monkeypatch.setenv("DAUM_RIDES_DIR", str(tmp_path))
    ride_id = history.save_ride(
        {
            "start": 1761732000.0,
            "duration": 60.0,
            "distance": 0.5,
            "samples": [{"t": 0, "power": 100, "cadence": 80, "speed": 30, "distance": 0}],
        },
        directory=tmp_path,
    )
    calls = {}

    def fake_email(ride, to=None):
        calls["ride"] = ride
        calls["to"] = to
        return {"ok": True, "to": to or "me@example.com"}

    bridge.email_ride = fake_email

    resp = client.post(f"/api/rides/{ride_id}/email", json={})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert calls["ride"]["id"] == ride_id
    assert calls["to"] is None

    resp = client.post(f"/api/rides/{ride_id}/email", json={"to": "other@example.com"})
    assert resp.status_code == 200
    assert calls["to"] == "other@example.com"


def test_email_ride_endpoint_unknown_ride(tmp_path, monkeypatch, client):
    monkeypatch.setenv("DAUM_RIDES_DIR", str(tmp_path))
    resp = client.post("/api/rides/does-not-exist/email")
    assert resp.status_code == 404
    assert resp.json()["ok"] is False


def test_strava_upload_without_config(monkeypatch):
    for name in (
        "STRAVA_ACCESS_TOKEN",
        "STRAVA_REFRESH_TOKEN",
        "STRAVA_CLIENT_ID",
        "STRAVA_CLIENT_SECRET",
        "STRAVA_TOKENS_FILE",
    ):
        monkeypatch.delenv(name, raising=False)
    cfg = Config()
    cfg.strava.token_file = "daum-bridge-test-missing-tokens.json"
    bridge = DaumBridge(cfg)
    app = create_app(bridge)
    client = TestClient(app)

    from daum_bridge import history

    monkeypatch.setattr(
        history,
        "latest_ride",
        lambda **kwargs: {"id": "ride-1", "start": 1761732000.0, "duration": 60.0},
    )
    resp = client.post("/api/strava/upload", json={})
    assert resp.status_code == 400
    assert resp.json()["ok"] is False
    assert "not configured" in resp.json()["error"]


def test_strava_upload_endpoint_sends_tcx(tmp_path, monkeypatch):
    monkeypatch.setenv("DAUM_RIDES_DIR", str(tmp_path))
    cfg = Config()
    cfg.strava.access_token = "test-token"
    cfg.strava.token_file = "daum-bridge-test-missing-tokens.json"
    bridge = DaumBridge(cfg)

    ride_id = history.save_ride(
        {
            "start": 1761732000.0,
            "duration": 60.0,
            "distance": 0.5,
            "avg_power": 200.0,
            "samples": [
                {"t": 0, "power": 100, "cadence": 80, "speed": 30, "distance": 0},
                {"t": 60, "power": 200, "cadence": 90, "speed": 35, "distance": 0.5},
            ],
        },
        directory=tmp_path,
    )

    calls = []

    def fake_request(self, method, url, data=None, headers=None, timeout=None):
        calls.append({"method": method, "url": url, "data": data, "headers": headers})
        return 200, json.dumps({"id": 1, "activity_id": 123, "status": "ready"}).encode()

    monkeypatch.setattr(StravaClient, "_request", fake_request)

    app = create_app(bridge)
    client = TestClient(app)
    resp = client.post("/api/strava/upload", json={})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["activity_id"] == 123

    assert len(calls) == 1
    assert calls[0]["url"].endswith("/uploads")
    assert calls[0]["headers"]["Authorization"] == "Bearer test-token"
    assert b"garmin:Watts" in calls[0]["data"]
    assert f"daum-{ride_id}".encode() in calls[0]["data"]
