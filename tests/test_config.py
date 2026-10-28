from daum_bridge import config
from daum_bridge.config import Config, SerialConfig, BridgeConfig, BLEConfig, WebConfig, LoggingConfig, get_env_overrides
import os
import tempfile
from pathlib import Path


def test_serial_config_defaults():
    s = SerialConfig()
    assert s.port == ""
    assert s.baudrate == 9600
    assert s.timeout == 1.0


def test_bridge_config_defaults():
    b = BridgeConfig()
    assert b.poll_interval == 0.5
    assert b.reconnect_delay == 2.0


def test_ble_config_defaults():
    bl = BLEConfig()
    assert bl.enabled is True
    assert bl.adapter == "hci0"
    assert bl.device_name == "DAUM-8008-TRS"


def test_web_config_defaults():
    w = WebConfig()
    assert w.enabled is True
    assert w.host == "0.0.0.0"
    assert w.port == 8080


def test_logging_config_defaults():
    l = LoggingConfig()
    assert l.level == "INFO"
    assert l.log_raw_frames is False


def test_config_from_dict_empty():
    c = Config.from_dict({})
    assert isinstance(c, Config)
    assert c.serial.baudrate == 9600


def test_config_from_dict_full():
    data = {
        "serial": {"port": "/dev/ttyUSB0", "baudrate": 19200, "timeout": 2.0, "bytesize": 8, "parity": "N", "stopbits": 1},
        "bridge": {"poll_interval": 0.25, "reconnect_delay": 1.0},
        "ble": {"enabled": False, "adapter": "hci1", "device_name": "TEST"},
        "web": {"enabled": True, "host": "127.0.0.1", "port": 9090},
        "logging": {"level": "DEBUG", "log_raw_frames": True},
    }
    c = Config.from_dict(data)
    assert c.serial.port == "/dev/ttyUSB0"
    assert c.serial.baudrate == 19200
    assert c.bridge.poll_interval == 0.25
    assert c.ble.enabled is False
    assert c.ble.adapter == "hci1"
    assert c.web.port == 9090
    assert c.logging.log_raw_frames is True


def test_config_from_dict_partial():
    data = {"serial": {"baudrate": 115200}}
    c = Config.from_dict(data)
    assert c.serial.baudrate == 115200


def test_config_validate():
    c = Config()
    errs = c.validate()
    assert isinstance(errs, list)


def test_config_validate_bad_baud():
    c = Config()
    c.serial.baudrate = 12345
    errs = c.validate()
    assert any("baudrate" in e.lower() for e in errs)


def test_config_validate_bad_port():
    c = Config()
    c.web.port = 70000
    errs = c.validate()
    assert any("port" in e.lower() for e in errs)


def test_config_load_defaults():
    c = Config.load("/nonexistent/path/config.yaml")
    assert isinstance(c, Config)


def test_config_load_from_file():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write("serial:\n  port: /dev/ttyS0\n  baudrate: 9600\nble:\n  enabled: true\n  device_name: MYDAUM\n")
        fname = f.name
    try:
        c = Config.load(fname)
        assert c.serial.port == "/dev/ttyS0"
        assert c.ble.device_name == "MYDAUM"
    finally:
        os.unlink(fname)


def test_get_env_overrides():
    c = Config()
    old = os.environ.copy()
    try:
        os.environ["DAUM_SERIAL_PORT"] = "/dev/ttyACM0"
        os.environ["DAUM_BLE_NAME"] = "ENVDAUM"
        os.environ["DAUM_WEB_PORT"] = "8000"
        c2 = get_env_overrides(c)
        assert c2.serial.port == "/dev/ttyACM0"
        assert c2.ble.device_name == "ENVDAUM"
        assert c2.web.port == 8000
    finally:
        os.environ.clear()
        os.environ.update(old)
