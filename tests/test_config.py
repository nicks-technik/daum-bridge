from daum_bridge.config import Config, get_env_overrides
from pathlib import Path
import tempfile
import os


def test_default_config():
    cfg = Config()
    assert cfg.serial.baudrate == 9600
    assert cfg.ble.device_name == "DAUM-8008-TRS"
    assert cfg.web.port == 8080


def test_load_from_yaml():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write("""
serial:
  port: /dev/ttyUSB0
  baudrate: 9600
ble:
  device_name: TEST-BIKE
web:
  port: 9090
""")
        f.flush()
        cfg = Config.load(f.name)
        assert cfg.serial.port == "/dev/ttyUSB0"
        assert cfg.ble.device_name == "TEST-BIKE"
        assert cfg.web.port == 9090
    os.unlink(f.name)


def test_env_overrides():
    cfg = Config()
    os.environ['DAUM_SERIAL_PORT'] = '/dev/ttyACM0'
    os.environ['DAUM_BLE_NAME'] = 'ENV-BIKE'
    os.environ['DAUM_WEB_PORT'] = '8888'
    cfg = get_env_overrides(cfg)
    assert cfg.serial.port == '/dev/ttyACM0'
    assert cfg.ble.device_name == 'ENV-BIKE'
    assert cfg.web.port == 8888
    # cleanup
    for k in ['DAUM_SERIAL_PORT', 'DAUM_BLE_NAME', 'DAUM_WEB_PORT']:
        os.environ.pop(k, None)
