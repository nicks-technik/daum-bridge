from daum_bridge import config
from daum_bridge.config import (
    BLEConfig,
    BridgeConfig,
    Config,
    EmailConfig,
    LoggingConfig,
    SerialConfig,
    StravaConfig,
    WebConfig,
    get_env_overrides,
)
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


def test_strava_config_defaults():
    s = StravaConfig()
    assert s.auto_upload is False
    assert s.private is False
    assert s.token_file == "strava.tokens.json"
    assert s.poll_timeout == 120.0
    assert s.refresh_token == ""


def test_config_from_dict_strava():
    c = Config.from_dict({
        "strava": {
            "auto_upload": True,
            "private": True,
            "client_id": "123",
            "client_secret": "secret",
            "refresh_token": "refresh",
            "token_file": "custom.tokens.json",
            "poll_timeout": 30,
        }
    })
    assert c.strava.auto_upload is True
    assert c.strava.private is True
    assert c.strava.client_id == "123"
    assert c.strava.refresh_token == "refresh"
    assert c.strava.token_file == "custom.tokens.json"
    assert c.strava.poll_timeout == 30.0


def test_strava_env_overrides(monkeypatch):
    monkeypatch.setenv("STRAVA_CLIENT_ID", "env-id")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "env-secret")
    monkeypatch.setenv("STRAVA_REFRESH_TOKEN", "env-refresh")
    monkeypatch.setenv("STRAVA_TOKENS_FILE", "env-tokens.json")
    monkeypatch.setenv("STRAVA_AUTO_UPLOAD", "true")
    monkeypatch.setenv("STRAVA_PRIVATE", "1")

    c = get_env_overrides(Config())
    assert c.strava.client_id == "env-id"
    assert c.strava.client_secret == "env-secret"
    assert c.strava.refresh_token == "env-refresh"
    assert c.strava.token_file == "env-tokens.json"
    assert c.strava.auto_upload is True
    assert c.strava.private is True


def test_strava_auto_upload_requires_credentials(monkeypatch):
    monkeypatch.delenv("STRAVA_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("STRAVA_ACCESS_TOKEN", raising=False)
    c = Config()
    c.strava.auto_upload = True
    errs = c.validate()
    assert any("strava" in e.lower() for e in errs)

    c.strava.refresh_token = "refresh"
    assert not any("strava" in e.lower() for e in c.validate())


def test_email_config_defaults():
    e = EmailConfig()
    assert e.auto_send is False
    assert e.host == ""
    assert e.port == 587
    assert e.use_tls is True
    assert e.use_ssl is False
    assert e.subject_prefix == "Daum training"
    assert e.is_configured() is False


def test_config_from_dict_email():
    c = Config.from_dict({
        "email": {
            "auto_send": True,
            "host": "smtp.gmail.com",
            "port": 465,
            "username": "me@gmail.com",
            "password": "app-password",
            "from_addr": "me@gmail.com",
            "to_addr": "me@gmail.com",
            "use_tls": False,
            "use_ssl": True,
            "subject_prefix": "Ride",
        }
    })
    assert c.email.auto_send is True
    assert c.email.host == "smtp.gmail.com"
    assert c.email.port == 465
    assert c.email.username == "me@gmail.com"
    assert c.email.password == "app-password"
    assert c.email.from_addr == "me@gmail.com"
    assert c.email.to_addr == "me@gmail.com"
    assert c.email.use_tls is False
    assert c.email.use_ssl is True
    assert c.email.subject_prefix == "Ride"
    assert c.email.is_configured() is True


def test_email_env_overrides(monkeypatch):
    monkeypatch.setenv("DAUM_EMAIL_HOST", "smtp.env.test")
    monkeypatch.setenv("DAUM_EMAIL_PORT", "2525")
    monkeypatch.setenv("DAUM_EMAIL_USER", "env-user")
    monkeypatch.setenv("DAUM_EMAIL_PASSWORD", "env-pass")
    monkeypatch.setenv("DAUM_EMAIL_FROM", "from@env.test")
    monkeypatch.setenv("DAUM_EMAIL_TO", "to@env.test")
    monkeypatch.setenv("DAUM_EMAIL_AUTO_SEND", "yes")
    monkeypatch.setenv("DAUM_EMAIL_TLS", "false")
    monkeypatch.setenv("DAUM_EMAIL_SSL", "true")

    c = get_env_overrides(Config())

    assert c.email.host == "smtp.env.test"
    assert c.email.port == 2525
    assert c.email.username == "env-user"
    assert c.email.password == "env-pass"
    assert c.email.from_addr == "from@env.test"
    assert c.email.to_addr == "to@env.test"
    assert c.email.auto_send is True
    assert c.email.use_tls is False
    assert c.email.use_ssl is True


def test_email_auto_send_requires_settings(monkeypatch):
    monkeypatch.delenv("DAUM_EMAIL_HOST", raising=False)
    monkeypatch.delenv("DAUM_EMAIL_TO", raising=False)
    c = Config()
    c.email.auto_send = True
    errs = c.validate()
    assert any("email" in e.lower() for e in errs)

    c.email.host = "smtp.example.com"
    c.email.to_addr = "me@example.com"
    assert not any("email" in e.lower() for e in c.validate())


def test_email_tls_and_ssl_conflict():
    c = Config()
    c.email.use_tls = True
    c.email.use_ssl = True
    assert any("email" in e.lower() for e in c.validate())
