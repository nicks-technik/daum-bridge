from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from ruamel.yaml import YAML
    _yaml = YAML(typ='safe')
    _yaml_load = lambda f: _yaml.load(f) or {}
except Exception:
    try:
        import yaml as pyyaml
        _yaml_load = lambda f: pyyaml.safe_load(f) or {}
    except Exception:
        _yaml_load = lambda f: {}


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


@dataclass
class BLEConfig:
    enabled: bool = True
    adapter: str = "hci0"
    device_name: str = "DAUM-8008-TRS"


@dataclass
class WebConfig:
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8080


@dataclass
class LoggingConfig:
    level: str = "INFO"
    log_raw_frames: bool = False


@dataclass
class Config:
    serial: SerialConfig = field(default_factory=SerialConfig)
    bridge: BridgeConfig = field(default_factory=BridgeConfig)
    ble: BLEConfig = field(default_factory=BLEConfig)
    web: WebConfig = field(default_factory=WebConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        cfg = cls()
        if not data:
            return cfg
        if "serial" in data and isinstance(data["serial"], dict):
            s = data["serial"]
            cfg.serial = SerialConfig(
                port=s.get("port", "") or "",
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
            )
        if "ble" in data and isinstance(data["ble"], dict):
            bl = data["ble"]
            cfg.ble = BLEConfig(
                enabled=bool(bl.get("enabled", True)),
                adapter=str(bl.get("adapter", "hci0")),
                device_name=str(bl.get("device_name", "DAUM-8008-TRS")),
            )
        if "web" in data and isinstance(data["web"], dict):
            w = data["web"]
            cfg.web = WebConfig(
                enabled=bool(w.get("enabled", True)),
                host=str(w.get("host", "0.0.0.0")),
                port=int(w.get("port", 8080)),
            )
        if "logging" in data and isinstance(data["logging"], dict):
            lg = data["logging"]
            cfg.logging = LoggingConfig(
                level=str(lg.get("level", "INFO")),
                log_raw_frames=bool(lg.get("log_raw_frames", False)),
            )
        return cfg

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        if path is None:
            for p in [Path("config.yaml"), Path("config.yml")]:
                if p.exists():
                    path = p
                    break
        if path is None:
            return cls()
        p = Path(path)
        if not p.exists():
            return cls()
        try:
            with p.open("r", encoding="utf-8") as f:
                data = _yaml_load(f)
            if not isinstance(data, dict):
                data = {}
            return cls.from_dict(data)
        except Exception:
            return cls()


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
    return cfg
