from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

try:
    from ruamel.yaml import YAML
    _yaml = YAML(typ='safe')
    _yaml_load = lambda f: _yaml.load(f) or {}

    def _yaml_dump(data, stream) -> None:
        YAML(typ='safe').dump(data, stream)
except Exception:
    try:
        import yaml as pyyaml
        _yaml_load = lambda f: pyyaml.safe_load(f) or {}

        def _yaml_dump(data, stream) -> None:
            pyyaml.safe_dump(data, stream, sort_keys=False)
    except Exception:
        _yaml_load = lambda f: {}

        def _yaml_dump(data, stream) -> None:
            raise RuntimeError("no YAML library available")


def load_yaml_file(path) -> dict:
    """Load a YAML mapping from ``path``; empty dict when missing/unreadable."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = _yaml_load(f)
    except Exception as e:
        log.debug("Could not read YAML file %s: %s", path, e)
        return {}
    return data if isinstance(data, dict) else {}


def dump_yaml_file(path, data: dict) -> None:
    """Write ``data`` to ``path`` as YAML (comments in the file are not kept)."""
    with open(path, "w", encoding="utf-8") as f:
        _yaml_dump(data, f)


def _cfg_int(value, default: int) -> int:
    """Best-effort int conversion that never aborts config parsing."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _cfg_float(value, default: float) -> float:
    """Best-effort float conversion that never aborts config parsing."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class SerialConfig:
    port: str = ""
    baudrate: int = 9600
    timeout: float = 1.0
    bytesize: int = 8
    parity: str = "N"
    stopbits: int = 1


@dataclass
class BridgeConfig:
    poll_interval: float = 0.5
    reconnect_delay: float = 2.0
    #: Highest gear used to translate FTMS/FE-C resistance into Daum gears.
    max_gear: int = 20


@dataclass
class BLEConfig:
    enabled: bool = True
    adapter: str = "hci0"
    device_name: str = "DAUM-8008-TRS"


@dataclass
class ANTConfig:
    """ANT+ FE-C trainer (device type 17) settings.

    ``device_id`` is the ANT device number (0 = let the software pick one).
    ``network_key`` is an optional hex override of the ANT+ public key.
    """
    enabled: bool = False
    device_id: int = 0
    network_key: str = ""



@dataclass
class StravaConfig:
    """Strava upload settings (see ``daum-bridge strava-auth``)."""
    auto_upload: bool = False
    client_id: str = ""
    client_secret: str = ""
    refresh_token: str = ""
    access_token: str = ""
    token_file: str = "strava.tokens.json"
    private: bool = False  # upload rides as private activities
    poll_timeout: float = 120.0


@dataclass
class WebConfig:
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8080


@dataclass
class EmailConfig:
    """Send finished rides as TCX attachments via SMTP."""
    auto_send: bool = False
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    from_addr: str = ""
    to_addr: str = ""
    use_tls: bool = True   # STARTTLS on port 587
    use_ssl: bool = False  # implicit TLS on port 465
    subject_prefix: str = "Daum training"
    timeout: float = 30.0

    def is_configured(self) -> bool:
        """True when enough settings exist to send an email."""
        return bool(self.host and self.from_addr and self.to_addr)


@dataclass
class GPIOInputConfig:
    """Wired shift buttons on the Raspberry Pi header."""

    up_pin: int = 17      # BCM17 = physical pin 11
    down_pin: int = 27    # BCM27 = physical pin 13
    bounce_time: float = 0.05
    #: Buttons wired to GND with the internal pull-up (recommended).
    active_low: bool = True


@dataclass
class EvdevInputConfig:
    """Bluetooth/USB HID buttons exposed as a Linux input device."""

    #: Path (/dev/input/...), "name:<substring>", or empty to auto-detect.
    device: str = ""
    up_key: str = "KEY_VOLUMEUP"
    down_key: str = "KEY_VOLUMEDOWN"


@dataclass
class InputConfig:
    """Physical gear-shift buttons (handlebar buttons)."""

    enabled: bool = False
    #: none | gpio | evdev | both
    backend: str = "both"
    #: Leave ERG mode when a button shifts, so the gear actually changes load.
    shift_clears_erg: bool = True
    repeat_delay: float = 0.45
    repeat_interval: float = 0.12
    min_interval: float = 0.10
    gpio: GPIOInputConfig = field(default_factory=GPIOInputConfig)
    evdev: EvdevInputConfig = field(default_factory=EvdevInputConfig)


@dataclass
class LoggingConfig:
    level: str = "INFO"
    log_raw_frames: bool = False


@dataclass
class Config:
    serial: SerialConfig = field(default_factory=SerialConfig)
    bridge: BridgeConfig = field(default_factory=BridgeConfig)
    ble: BLEConfig = field(default_factory=BLEConfig)
    ant: ANTConfig = field(default_factory=ANTConfig)
    strava: StravaConfig = field(default_factory=StravaConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    web: WebConfig = field(default_factory=WebConfig)
    input: InputConfig = field(default_factory=InputConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        cfg = cls()
        if not data:
            return cfg
        try:
            if "serial" in data and isinstance(data["serial"], dict):
                s = data["serial"]
                cfg.serial = SerialConfig(
                    port=str(s.get("port", "") or ""),
                    baudrate=int(s.get("baudrate", 9600)),
                    timeout=float(s.get("timeout", 1.0)),
                    bytesize=int(s.get("bytesize", 8)),
                    parity=str(s.get("parity", "N")),
                    stopbits=int(s.get("stopbits", 1)),
                )
            if "bridge" in data and isinstance(data["bridge"], dict):
                b = data["bridge"]
                cfg.bridge = BridgeConfig(
                    poll_interval=float(b.get("poll_interval", 0.5)),
                    reconnect_delay=float(b.get("reconnect_delay", 2.0)),
                    max_gear=int(b.get("max_gear", 20) or 20),
                )
            if "ble" in data and isinstance(data["ble"], dict):
                bl = data["ble"]
                cfg.ble = BLEConfig(
                    enabled=bool(bl.get("enabled", True)),
                    adapter=str(bl.get("adapter", "hci0")),
                    device_name=str(bl.get("device_name", "DAUM-8008-TRS")),
                )
            if "ant" in data and isinstance(data["ant"], dict):
                a = data["ant"]
                cfg.ant = ANTConfig(
                    enabled=bool(a.get("enabled", False)),
                    device_id=int(a.get("device_id", 0) or 0),
                    network_key=str(a.get("network_key", "") or ""),
                )
            if "strava" in data and isinstance(data["strava"], dict):
                st = data["strava"]
                cfg.strava = StravaConfig(
                    auto_upload=bool(st.get("auto_upload", False)),
                    client_id=str(st.get("client_id", "") or ""),
                    client_secret=str(st.get("client_secret", "") or ""),
                    refresh_token=str(st.get("refresh_token", "") or ""),
                    access_token=str(st.get("access_token", "") or ""),
                    token_file=str(st.get("token_file", "strava.tokens.json") or "strava.tokens.json"),
                    private=bool(st.get("private", False)),
                    poll_timeout=float(st.get("poll_timeout") or 120.0),
                )
            if "email" in data and isinstance(data["email"], dict):
                em = data["email"]
                cfg.email = EmailConfig(
                    auto_send=bool(em.get("auto_send", False)),
                    host=str(em.get("host", "") or ""),
                    port=int(em.get("port", 587) or 587),
                    username=str(em.get("username", "") or ""),
                    password=str(em.get("password", "") or ""),
                    from_addr=str(em.get("from_addr", "") or ""),
                    to_addr=str(em.get("to_addr", "") or ""),
                    use_tls=bool(em.get("use_tls", True)),
                    use_ssl=bool(em.get("use_ssl", False)),
                    subject_prefix=str(em.get("subject_prefix", "Daum training") or "Daum training"),
                    timeout=float(em.get("timeout", 30.0) or 30.0),
                )
            if "web" in data and isinstance(data["web"], dict):
                w = data["web"]
                cfg.web = WebConfig(
                    enabled=bool(w.get("enabled", True)),
                    host=str(w.get("host", "0.0.0.0")),
                    port=int(w.get("port", 8080)),
                )
            if "input" in data and isinstance(data["input"], dict):
                inp = data["input"]
                gpio = inp.get("gpio") if isinstance(inp.get("gpio"), dict) else {}
                evdev = inp.get("evdev") if isinstance(inp.get("evdev"), dict) else {}
                cfg.input = InputConfig(
                    enabled=bool(inp.get("enabled", False)),
                    backend=str(inp.get("backend", "both") or "both").strip().lower(),
                    shift_clears_erg=bool(inp.get("shift_clears_erg", True)),
                    repeat_delay=_cfg_float(inp.get("repeat_delay"), 0.45),
                    repeat_interval=_cfg_float(inp.get("repeat_interval"), 0.12),
                    min_interval=_cfg_float(inp.get("min_interval"), 0.10),
                    gpio=GPIOInputConfig(
                        up_pin=_cfg_int(gpio.get("up_pin"), 17),
                        down_pin=_cfg_int(gpio.get("down_pin"), 27),
                        bounce_time=_cfg_float(gpio.get("bounce_time"), 0.05),
                        active_low=bool(gpio.get("active_low", True)),
                    ),
                    evdev=EvdevInputConfig(
                        device=str(evdev.get("device", "") or ""),
                        up_key=str(evdev.get("up_key") or "KEY_VOLUMEUP"),
                        down_key=str(evdev.get("down_key") or "KEY_VOLUMEDOWN"),
                    ),
                )
            if "logging" in data and isinstance(data["logging"], dict):
                lg = data["logging"]
                cfg.logging = LoggingConfig(
                    level=str(lg.get("level", "INFO")),
                    log_raw_frames=bool(lg.get("log_raw_frames", False)),
                )
        except Exception as e:
            log.warning(f"Config parsing error, using defaults: {e}")
        return cfg

    def validate(self) -> list:
        errors = []
        try:
            if self.serial.baudrate not in [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]:
                errors.append(f"Invalid baudrate: {self.serial.baudrate}")
            if self.serial.port and not os.path.exists(self.serial.port) and not self.serial.port.startswith("COM"):
                # On Linux it should exist, on Windows COM ports might not exist as files
                pass
            if self.web.port < 1 or self.web.port > 65535:
                errors.append(f"Invalid web port: {self.web.port}")
            if self.bridge.poll_interval < 0.1 or self.bridge.poll_interval > 5.0:
                errors.append("poll_interval should be between 0.1 and 5.0")
            if self.bridge.max_gear < 2 or self.bridge.max_gear > 28:
                errors.append("bridge.max_gear should be between 2 and 28")
            if self.input.backend not in ("none", "gpio", "evdev", "both"):
                errors.append(
                    "input.backend must be one of none, gpio, evdev or both "
                    f"(got {self.input.backend!r})"
                )
            if self.input.enabled and self.input.backend == "none":
                errors.append("input.enabled is true but input.backend is 'none'")
            if self.input.gpio.up_pin == self.input.gpio.down_pin:
                errors.append("input.gpio.up_pin and input.gpio.down_pin must differ")
            for name, pin in (
                ("up_pin", self.input.gpio.up_pin),
                ("down_pin", self.input.gpio.down_pin),
            ):
                if not 0 <= pin <= 27:
                    errors.append(f"input.gpio.{name} should be a BCM pin between 0 and 27")
            if self.input.repeat_delay < 0:
                errors.append("input.repeat_delay must be >= 0 (0 disables hold-to-repeat)")
            if self.input.repeat_interval < 0 or 0 < self.input.repeat_interval < 0.02:
                errors.append("input.repeat_interval must be 0 (disabled) or >= 0.02")
            if self.input.min_interval < 0:
                errors.append("input.min_interval must be >= 0")
            if self.ant.device_id < 0 or self.ant.device_id > 0xFFFF:
                errors.append("ant.device_id should be between 0 and 65535")
            has_strava_credentials = bool(
                self.strava.refresh_token
                or self.strava.access_token
                or os.environ.get("STRAVA_REFRESH_TOKEN")
                or os.environ.get("STRAVA_ACCESS_TOKEN")
            )
            if self.strava.auto_upload and not has_strava_credentials:
                errors.append("strava.auto_upload is enabled but no Strava credentials are configured")
            if self.strava.poll_timeout < 5 or self.strava.poll_timeout > 600:
                errors.append("strava.poll_timeout should be between 5 and 600 seconds")
            if self.email.port < 1 or self.email.port > 65535:
                errors.append(f"Invalid email port: {self.email.port}")
            has_email_settings = bool(
                self.email.host
                or os.environ.get("DAUM_EMAIL_HOST")
            )
            has_email_recipient = bool(
                self.email.to_addr
                or os.environ.get("DAUM_EMAIL_TO")
            )
            if self.email.auto_send and not (has_email_settings and has_email_recipient):
                errors.append("email.auto_send is enabled but email host/to_addr are not configured")
            if self.email.use_tls and self.email.use_ssl:
                errors.append("email.use_tls and email.use_ssl cannot both be enabled")
        except Exception as e:
            errors.append(f"Validation error: {e}")
        return errors

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        if path is None:
            for p in [Path("config.yaml"), Path("config.yml")]:
                if p.exists():
                    path = p
                    break
        if path is None:
            cfg = cls()
            errs = cfg.validate()
            if errs:
                for e in errs:
                    log.warning(f"Config issue: {e}")
            return cfg
        p = Path(path)
        if not p.exists():
            log.warning(f"Config file {p} not found, using defaults")
            cfg = cls()
            return cfg
        try:
            with p.open("r", encoding="utf-8") as f:
                data = _yaml_load(f)
            if not isinstance(data, dict):
                data = {}
            cfg = cls.from_dict(data)
            errs = cfg.validate()
            if errs:
                for e in errs:
                    log.warning(f"Config issue: {e}")
            return cfg
        except Exception as e:
            log.error(f"Failed to load config: {e}, using defaults")
            return cls()


def _env_bool(name: str) -> bool | None:
    value = os.environ.get(name)
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_env_overrides(cfg: Config) -> Config:
    # simple env overrides
    if os.environ.get("DAUM_SERIAL_PORT"):
        cfg.serial.port = os.environ["DAUM_SERIAL_PORT"]
    if os.environ.get("DAUM_BLE_NAME"):
        cfg.ble.device_name = os.environ["DAUM_BLE_NAME"]
    if os.environ.get("DAUM_WEB_PORT"):
        try:
            cfg.web.port = int(os.environ["DAUM_WEB_PORT"])
        except ValueError:
            pass
    if os.environ.get("DAUM_MAX_GEAR"):
        try:
            cfg.bridge.max_gear = int(os.environ["DAUM_MAX_GEAR"])
        except ValueError:
            pass
    ant_enabled = _env_bool("DAUM_ANT_ENABLED")
    if ant_enabled is not None:
        cfg.ant.enabled = ant_enabled
    if os.environ.get("DAUM_ANT_DEVICE_ID"):
        try:
            cfg.ant.device_id = int(os.environ["DAUM_ANT_DEVICE_ID"])
        except ValueError:
            pass
    if os.environ.get("DAUM_ANT_NETWORK_KEY"):
        cfg.ant.network_key = os.environ["DAUM_ANT_NETWORK_KEY"]
    input_enabled = _env_bool("DAUM_INPUT_ENABLED")
    if input_enabled is not None:
        cfg.input.enabled = input_enabled
    if os.environ.get("DAUM_INPUT_BACKEND"):
        cfg.input.backend = os.environ["DAUM_INPUT_BACKEND"].strip().lower()
    if os.environ.get("DAUM_GPIO_UP_PIN"):
        cfg.input.gpio.up_pin = _cfg_int(os.environ["DAUM_GPIO_UP_PIN"], cfg.input.gpio.up_pin)
    if os.environ.get("DAUM_GPIO_DOWN_PIN"):
        cfg.input.gpio.down_pin = _cfg_int(
            os.environ["DAUM_GPIO_DOWN_PIN"], cfg.input.gpio.down_pin
        )
    if os.environ.get("DAUM_INPUT_DEVICE"):
        cfg.input.evdev.device = os.environ["DAUM_INPUT_DEVICE"]
    if os.environ.get("DAUM_INPUT_UP_KEY"):
        cfg.input.evdev.up_key = os.environ["DAUM_INPUT_UP_KEY"]
    if os.environ.get("DAUM_INPUT_DOWN_KEY"):
        cfg.input.evdev.down_key = os.environ["DAUM_INPUT_DOWN_KEY"]
    for env_name, attr in (
        ("STRAVA_CLIENT_ID", "client_id"),
        ("STRAVA_CLIENT_SECRET", "client_secret"),
        ("STRAVA_REFRESH_TOKEN", "refresh_token"),
        ("STRAVA_ACCESS_TOKEN", "access_token"),
        ("STRAVA_TOKENS_FILE", "token_file"),
    ):
        value = os.environ.get(env_name)
        if value:
            setattr(cfg.strava, attr, value)
    auto_upload = _env_bool("STRAVA_AUTO_UPLOAD")
    if auto_upload is not None:
        cfg.strava.auto_upload = auto_upload
    private = _env_bool("STRAVA_PRIVATE")
    if private is not None:
        cfg.strava.private = private

    for env_name, attr in (
        ("DAUM_EMAIL_HOST", "host"),
        ("DAUM_EMAIL_USER", "username"),
        ("DAUM_EMAIL_PASSWORD", "password"),
        ("DAUM_EMAIL_FROM", "from_addr"),
        ("DAUM_EMAIL_TO", "to_addr"),
        ("DAUM_EMAIL_SUBJECT_PREFIX", "subject_prefix"),
    ):
        value = os.environ.get(env_name)
        if value:
            setattr(cfg.email, attr, value)
    if os.environ.get("DAUM_EMAIL_PORT"):
        try:
            cfg.email.port = int(os.environ["DAUM_EMAIL_PORT"])
        except ValueError:
            pass
    for env_name, attr in (
        ("DAUM_EMAIL_AUTO_SEND", "auto_send"),
        ("DAUM_EMAIL_TLS", "use_tls"),
        ("DAUM_EMAIL_SSL", "use_ssl"),
    ):
        value = _env_bool(env_name)
        if value is not None:
            setattr(cfg.email, attr, value)
    return cfg
