from daum_bridge.web.app import create_app
from daum_bridge.config import Config
from daum_bridge.bridge import DaumBridge
from fastapi.testclient import TestClient


def test_create_app():
    cfg = Config()
    bridge = DaumBridge(cfg)
    app = create_app(bridge)
    assert app is not None


def test_index_route():
    cfg = Config()
    bridge = DaumBridge(cfg)
    app = create_app(bridge)
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200


def test_config_route():
    cfg = Config()
    bridge = DaumBridge(cfg)
    app = create_app(bridge)
    client = TestClient(app)
    resp = client.get("/config")
    assert resp.status_code == 200


def test_api_state():
    cfg = Config()
    bridge = DaumBridge(cfg)
    app = create_app(bridge)
    client = TestClient(app)
    resp = client.get("/api/state")
    assert resp.status_code == 200
    data = resp.json()
    assert "connected" in data


def test_api_status():
    cfg = Config()
    bridge = DaumBridge(cfg)
    app = create_app(bridge)
    client = TestClient(app)
    resp = client.get("/api/status")
    assert resp.status_code == 200


def test_api_diagnostics():
    cfg = Config()
    bridge = DaumBridge(cfg)
    app = create_app(bridge)
    client = TestClient(app)
    resp = client.get("/api/diagnostics")
    assert resp.status_code == 200


def test_api_config_get():
    cfg = Config()
    bridge = DaumBridge(cfg)
    app = create_app(bridge)
    client = TestClient(app)
    resp = client.get("/api/config")
    assert resp.status_code == 200


def test_shift_up():
    cfg = Config()
    bridge = DaumBridge(cfg)
    app = create_app(bridge)
    client = TestClient(app)
    resp = client.post("/api/shift/up")
    assert resp.status_code == 200


def test_shift_down():
    cfg = Config()
    bridge = DaumBridge(cfg)
    app = create_app(bridge)
    client = TestClient(app)
    resp = client.post("/api/shift/down")
    assert resp.status_code == 200


def test_set_gear():
    cfg = Config()
    bridge = DaumBridge(cfg)
    app = create_app(bridge)
    client = TestClient(app)
    resp = client.post("/api/gear/5")
    assert resp.status_code == 200


def test_set_target_watt():
    cfg = Config()
    bridge = DaumBridge(cfg)
    app = create_app(bridge)
    client = TestClient(app)
    resp = client.post("/api/target/watt", json={"watts": 150})
    assert resp.status_code == 200
