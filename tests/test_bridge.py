from daum_bridge.bridge import DaumBridge
from daum_bridge.config import Config
from unittest.mock import Mock, patch


def test_bridge_init():
    cfg = Config()
    bridge = DaumBridge(cfg)
    assert bridge.config is cfg
    assert not bridge._running


def test_set_target_watt():
    cfg = Config()
    bridge = DaumBridge(cfg)
    bridge.protocol = Mock()
    bridge.protocol._address_found = True
    bridge.set_target_watt(250)
    bridge.protocol.set_watt.assert_called_once_with(250)
