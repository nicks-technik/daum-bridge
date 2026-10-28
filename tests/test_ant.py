from daum_bridge.backends.ant_fe import ANTFEBackend
from daum_bridge.config import Config, ANTConfig
from daum_bridge.bridge import DaumBridge


def test_ant_config_defaults():
    a = ANTConfig()
    assert a.enabled is False
    assert a.device_path == ""
    assert a.network_key == ""


def test_ant_backend_init():
    cfg = Config()
    bridge = DaumBridge(cfg)
    b = ANTFEBackend(bridge, cfg)
    assert b.bridge is bridge
    assert b._running is False


def test_ant_backend_start_stop():
    cfg = Config()
    bridge = DaumBridge(cfg)
    b = ANTFEBackend(bridge, cfg)
    try:
        b.start()
        assert b._running is True
    finally:
        b.stop()
        assert b._running is False
