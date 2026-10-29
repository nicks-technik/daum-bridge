"""Configuration model and YAML loading.

The bridge is configured from ``config.yaml`` (optionally overridden by
``DAUM_*`` environment variables). Parsing has to be forgiving: a rider editing
the file by hand will eventually write a string where a number belongs, leave a
section empty, or mistype one field. The bridge must still start and must still
use every setting it *could* understand.

Each ``config.yaml`` section therefore has its own ``_parse_*`` function below.
Keeping them separate (instead of one long ``from_dict``) has two effects:
a broken value only resets its own section, and the mapping between YAML keys
and dataclass fields is readable without counting ``if`` blocks.
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .numbers import as_float, as_int

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


def _cfg_str(value, default: str = "") -> str:
    """Return ``value`` as a string, falling back to ``default`` when empty.

    ``None`` and the empty string both mean "not configured"; treating them the
    same way keeps the defaults written here in one place instead of repeating
    ``or "fallback"`` at every call site.
    """
    if value is None:
        return default
    text = str(value)
    return text if text else default


def _cfg_bool(value, default: bool = False) -> bool:
    """Return ``value`` as a bool, accepting the usual textual spellings.

    YAML already turns ``true``/``false`` into booleans, but values can also
    arrive as strings from a JSON payload or ``"0"``/``"no"`` in a hand-edited
    file. Plain ``bool("false")`` would be ``True``, which is never what the
    rider meant, so the textual forms are interpreted explicitly.
    """
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _section(data: dict, name: str) -> dict:
    """Return the mapping stored under ``name``, or an empty dict.

    A section that is missing, ``null`` or accidentally a scalar is treated as
    empty, so the caller keeps its defaults instead of raising.
    """
    value = data.get(name)
    return value if isinstance(value, dict) else {}



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


# ---------------------------------------------------------------------------
# Section parsers
#
# One function per ``config.yaml`` section. Each one starts from a default
# instance and only overwrites the keys that are actually present, so the
# defaults live in the dataclass and are never repeated here. Every conversion
# is guarded: a bad value (``baudrate: fast``, ``port: null``) falls back to the
# default for that single field instead of raising.
# ---------------------------------------------------------------------------


def _parse_serial(section: dict) -> SerialConfig:
    """Build :class:`SerialConfig` from the ``serial`` section."""
    config = SerialConfig()
    config.port = _cfg_str(section.get("port"), config.port)
    config.baudrate = as_int(section.get("baudrate"), config.baudrate)
    config.timeout = as_float(section.get("timeout"), config.timeout)
    config.bytesize = as_int(section.get("bytesize"), config.bytesize)
    config.parity = _cfg_str(section.get("parity"), config.parity)
    config.stopbits = as_int(section.get("stopbits"), config.stopbits)
    return config


def _parse_bridge(section: dict) -> BridgeConfig:
    """Build :class:`BridgeConfig` from the ``bridge`` section."""
    config = BridgeConfig()
    config.poll_interval = as_float(section.get("poll_interval"), config.poll_interval)
    config.reconnect_delay = as_float(section.get("reconnect_delay"), config.reconnect_delay)
    # ``or`` keeps the historical behaviour: max_gear of 0 means "unset".
    config.max_gear = as_int(section.get("max_gear") or config.max_gear, config.max_gear)
    return config


def _parse_ble(section: dict) -> BLEConfig:
    """Build :class:`BLEConfig` from the ``ble`` section."""
    config = BLEConfig()
    config.enabled = _cfg_bool(section.get("enabled"), config.enabled)
    config.adapter = _cfg_str(section.get("adapter"), config.adapter)
    config.device_name = _cfg_str(section.get("device_name"), config.device_name)
    return config


def _parse_ant(section: dict) -> ANTConfig:
    """Build :class:`ANTConfig` from the ``ant`` section."""
    config = ANTConfig()
    config.enabled = _cfg_bool(section.get("enabled"), config.enabled)
    config.device_id = as_int(section.get("device_id"), config.device_id)
    config.network_key = _cfg_str(section.get("network_key"), config.network_key)
    return config


def _parse_strava(section: dict) -> StravaConfig:
    """Build :class:`StravaConfig` from the ``strava`` section."""
    config = StravaConfig()
    config.auto_upload = _cfg_bool(section.get("auto_upload"), config.auto_upload)
    config.client_id = _cfg_str(section.get("client_id"), config.client_id)
    config.client_secret = _cfg_str(section.get("client_secret"), config.client_secret)
    config.refresh_token = _cfg_str(section.get("refresh_token"), config.refresh_token)
    config.access_token = _cfg_str(section.get("access_token"), config.access_token)
    config.token_file = _cfg_str(section.get("token_file"), config.token_file)
    config.private = _cfg_bool(section.get("private"), config.private)
    config.poll_timeout = as_float(section.get("poll_timeout"), config.poll_timeout)
    return config


def _parse_email(section: dict) -> EmailConfig:
    """Build :class:`EmailConfig` from the ``email`` section."""
    config = EmailConfig()
    config.auto_send = _cfg_bool(section.get("auto_send"), config.auto_send)
    config.host = _cfg_str(section.get("host"), config.host)
    config.port = as_int(section.get("port"), config.port)
    config.username = _cfg_str(section.get("username"), config.username)
    config.password = _cfg_str(section.get("password"), config.password)
    config.from_addr = _cfg_str(section.get("from_addr"), config.from_addr)
    config.to_addr = _cfg_str(section.get("to_addr"), config.to_addr)
    config.use_tls = _cfg_bool(section.get("use_tls"), config.use_tls)
    config.use_ssl = _cfg_bool(section.get("use_ssl"), config.use_ssl)
    config.subject_prefix = _cfg_str(section.get("subject_prefix"), config.subject_prefix)
    config.timeout = as_float(section.get("timeout"), config.timeout)
    return config


def _parse_web(section: dict) -> WebConfig:
    """Build :class:`WebConfig` from the ``web`` section."""
    config = WebConfig()
    config.enabled = _cfg_bool(section.get("enabled"), config.enabled)
    config.host = _cfg_str(section.get("host"), config.host)
    config.port = as_int(section.get("port"), config.port)
    return config


def _parse_gpio_input(section: dict) -> GPIOInputConfig:
    """Build :class:`GPIOInputConfig` from the ``input.gpio`` sub-section."""
    config = GPIOInputConfig()
    config.up_pin = as_int(section.get("up_pin"), config.up_pin)
    config.down_pin = as_int(section.get("down_pin"), config.down_pin)
    config.bounce_time = as_float(section.get("bounce_time"), config.bounce_time)
    config.active_low = _cfg_bool(section.get("active_low"), config.active_low)
    return config


def _parse_evdev_input(section: dict) -> EvdevInputConfig:
    """Build :class:`EvdevInputConfig` from the ``input.evdev`` sub-section."""
    config = EvdevInputConfig()
    config.device = _cfg_str(section.get("device"), config.device)
    config.up_key = _cfg_str(section.get("up_key"), config.up_key)
    config.down_key = _cfg_str(section.get("down_key"), config.down_key)
    return config


def _parse_input(section: dict) -> InputConfig:
    """Build :class:`InputConfig` from the ``input`` section.

    ``gpio`` and ``evdev`` are nested sections; both are optional and each is
    parsed independently so a typo in one does not discard the other.
    """
    config = InputConfig()
    config.enabled = _cfg_bool(section.get("enabled"), config.enabled)
    config.backend = _cfg_str(section.get("backend"), config.backend).strip().lower()
    config.shift_clears_erg = _cfg_bool(section.get("shift_clears_erg"), config.shift_clears_erg)
    config.repeat_delay = as_float(section.get("repeat_delay"), config.repeat_delay)
    config.repeat_interval = as_float(section.get("repeat_interval"), config.repeat_interval)
    config.min_interval = as_float(section.get("min_interval"), config.min_interval)
    config.gpio = _parse_gpio_input(_section(section, "gpio"))
    config.evdev = _parse_evdev_input(_section(section, "evdev"))
    return config


def _parse_logging(section: dict) -> LoggingConfig:
    """Build :class:`LoggingConfig` from the ``logging`` section."""
    config = LoggingConfig()
    config.level = _cfg_str(section.get("level"), config.level)
    config.log_raw_frames = _cfg_bool(section.get("log_raw_frames"), config.log_raw_frames)
    return config



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
        """Build a :class:`Config` from a parsed YAML/JSON mapping.

        Every section is optional and is parsed independently. A value that
        cannot be converted only resets the field it belongs to: a broken
        ``serial.baudrate`` no longer discards the ``ble``, ``ant``, ``strava``,
        ``email`` and ``input`` sections that follow it in the file.
        """
        cfg = cls()
        if not data:
            return cfg

        serial = _section(data, "serial")
        if serial:
            cfg.serial = _parse_serial(serial)
        bridge = _section(data, "bridge")
        if bridge:
            cfg.bridge = _parse_bridge(bridge)
        ble = _section(data, "ble")
        if ble:
            cfg.ble = _parse_ble(ble)
        ant = _section(data, "ant")
        if ant:
            cfg.ant = _parse_ant(ant)
        strava = _section(data, "strava")
        if strava:
            cfg.strava = _parse_strava(strava)
        email = _section(data, "email")
        if email:
            cfg.email = _parse_email(email)
        web = _section(data, "web")
        if web:
            cfg.web = _parse_web(web)
        input_section = _section(data, "input")
        if input_section:
            cfg.input = _parse_input(input_section)
        logging_section = _section(data, "logging")
        if logging_section:
            cfg.logging = _parse_logging(logging_section)
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
        cfg.input.gpio.up_pin = as_int(
            os.environ["DAUM_GPIO_UP_PIN"], cfg.input.gpio.up_pin
        )
    if os.environ.get("DAUM_GPIO_DOWN_PIN"):
        cfg.input.gpio.down_pin = as_int(
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
