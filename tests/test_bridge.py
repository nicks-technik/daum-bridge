from daum_bridge.bridge import DaumBridge
from daum_bridge.config import Config
from unittest.mock import Mock, patch


def test_bridge_init():
    cfg = Config()
    b = DaumBridge(cfg)
    assert b.config is cfg
    assert b._running is False
    assert b._target_watt == 0
    assert b._target_gear == 1


def test_bridge_callbacks():
    cfg = Config()
    b = DaumBridge(cfg)
    called = []
    def cb(s):
        called.append(s)
    b.add_state_callback(cb)
    assert cb in b._callbacks


def test_bridge_notify():
    cfg = Config()
    b = DaumBridge(cfg)
    called = []
    b.add_state_callback(lambda s: called.append(True))
    b._notify()
    assert len(called) >= 1


def test_bridge_set_target_watt():
    cfg = Config()
    b = DaumBridge(cfg)
    b.protocol = Mock()
    b.protocol._address_found = True
    b.set_target_watt(200)
    assert b._target_watt == 200


def test_bridge_set_target_watt_clamped():
    cfg = Config()
    b = DaumBridge(cfg)
    b.protocol = Mock()
    b.protocol._address_found = True
    b.set_target_watt(1000)
    assert b._target_watt == 800
    b.set_target_watt(-10)
    assert b._target_watt == 0


def test_bridge_shift_up():
    cfg = Config()
    b = DaumBridge(cfg)
    b.protocol = Mock()
    b.protocol._address_found = True
    b._target_gear = 1
    b.shift_up()
    assert b._target_gear == 2


def test_bridge_shift_down():
    cfg = Config()
    b = DaumBridge(cfg)
    b.protocol = Mock()
    b.protocol._address_found = True
    b._target_gear = 5
    b.shift_down()
    assert b._target_gear == 4


def test_bridge_set_gear():
    cfg = Config()
    b = DaumBridge(cfg)
    b.protocol = Mock()
    b.protocol._address_found = True
    b.set_gear(10)
    assert b._target_gear == 10
