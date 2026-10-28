from daum_bridge.web.app import create_app
from daum_bridge.config import Config
from daum_bridge.bridge import DaumBridge
from fastapi.testclient import TestClient


def test_history_page():
    cfg = Config()
    bridge = DaumBridge(cfg)
    app = create_app(bridge)
    client = TestClient(app)
    resp = client.get("/history")
    assert resp.status_code == 200


def test_logs_page():
    cfg = Config()
    bridge = DaumBridge(cfg)
    app = create_app(bridge)
    client = TestClient(app)
    resp = client.get("/logs")
    assert resp.status_code == 200


def test_api_logs():
    cfg = Config()
    bridge = DaumBridge(cfg)
    app = create_app(bridge)
    client = TestClient(app)
    resp = client.get("/api/logs")
    assert resp.status_code == 200
    assert "logs" in resp.json()


def test_api_history():
    cfg = Config()
    bridge = DaumBridge(cfg)
    app = create_app(bridge)
    client = TestClient(app)
    resp = client.get("/api/history")
    assert resp.status_code == 200
    assert "rides" in resp.json()


def test_reconnect_serial():
    cfg = Config()
    bridge = DaumBridge(cfg)
    app = create_app(bridge)
    client = TestClient(app)
    resp = client.post("/api/reconnect/serial")
    assert resp.status_code in [200, 500]
