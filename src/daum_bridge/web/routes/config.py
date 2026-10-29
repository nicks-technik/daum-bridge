"""Configuration routes: read ``config.yaml`` and apply form updates.

The UI edits the YAML file in place. Two rules make that safe for secrets:

* an empty secret field means "keep the stored value" (a browser that renders an
  empty password box must not erase the password on save);
* an explicit ``clear_password`` / ``clear_credentials`` flag removes it.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse


def register(app: FastAPI) -> None:
    """Register the configuration routes on ``app``."""

    @app.get("/api/config")
    async def get_config():
        try:
            from ...config import Config

            cfg = Config.load()
            data = {
                "serial": {"port": cfg.serial.port, "baudrate": cfg.serial.baudrate},
                "ble": {
                    "enabled": cfg.ble.enabled,
                    "adapter": cfg.ble.adapter,
                    "device_name": cfg.ble.device_name,
                },
                "ant": {
                    "enabled": getattr(cfg.ant, "enabled", False),
                    "device_id": getattr(cfg.ant, "device_id", 0),
                    "network_key": getattr(cfg.ant, "network_key", ""),
                },
                "strava": {
                    "auto_upload": getattr(cfg.strava, "auto_upload", False),
                    "private": getattr(cfg.strava, "private", False),
                    "client_id": getattr(cfg.strava, "client_id", ""),
                    "token_file": getattr(cfg.strava, "token_file", "strava.tokens.json"),
                    "configured": bool(
                        getattr(cfg.strava, "refresh_token", "")
                        or getattr(cfg.strava, "access_token", "")
                    ),
                },
                "web": {
                    "enabled": cfg.web.enabled,
                    "host": cfg.web.host,
                    "port": cfg.web.port,
                },
                "email": {
                    "host": getattr(cfg.email, "host", ""),
                    "port": getattr(cfg.email, "port", 587),
                    "username": getattr(cfg.email, "username", ""),
                    "from_addr": getattr(cfg.email, "from_addr", ""),
                    "to_addr": getattr(cfg.email, "to_addr", ""),
                    "auto_send": getattr(cfg.email, "auto_send", False),
                    "use_tls": getattr(cfg.email, "use_tls", True),
                    "use_ssl": getattr(cfg.email, "use_ssl", False),
                    "subject_prefix": getattr(cfg.email, "subject_prefix", "Daum training"),
                    "configured": getattr(cfg.email, "is_configured", lambda: False)(),
                },
                "logging": {
                    "level": cfg.logging.level,
                    "log_raw_frames": cfg.logging.log_raw_frames,
                },
                "bridge": {
                    "poll_interval": cfg.bridge.poll_interval,
                    "max_gear": getattr(cfg.bridge, "max_gear", 20),
                },
                "input": {
                    "enabled": getattr(cfg.input, "enabled", False),
                    "backend": getattr(cfg.input, "backend", "both"),
                    "shift_clears_erg": getattr(cfg.input, "shift_clears_erg", True),
                    "repeat_delay": getattr(cfg.input, "repeat_delay", 0.45),
                    "repeat_interval": getattr(cfg.input, "repeat_interval", 0.12),
                    "gpio": {
                        "up_pin": getattr(cfg.input.gpio, "up_pin", 17),
                        "down_pin": getattr(cfg.input.gpio, "down_pin", 27),
                        "bounce_time": getattr(cfg.input.gpio, "bounce_time", 0.05),
                        "active_low": getattr(cfg.input.gpio, "active_low", True),
                    },
                    "evdev": {
                        "device": getattr(cfg.input.evdev, "device", ""),
                        "up_key": getattr(cfg.input.evdev, "up_key", "KEY_VOLUMEUP"),
                        "down_key": getattr(cfg.input.evdev, "down_key", "KEY_VOLUMEDOWN"),
                    },
                },
            }
            return JSONResponse(data)
        except Exception as e:
            return JSONResponse({"error": str(e)})

    @app.post("/api/config")
    async def post_config(data: dict):
        try:
            from ...config import dump_yaml_file, load_yaml_file

            cfg_path = Path("config.yaml")
            if not cfg_path.exists():
                example = Path("config.example.yaml")
                if example.exists():
                    from shutil import copyfile

                    copyfile(example, cfg_path)
            cfg = load_yaml_file(cfg_path)

            if "serial" in data:
                cfg.setdefault("serial", {})
                if "port" in data["serial"]:
                    cfg["serial"]["port"] = data["serial"]["port"] or None
                if "baudrate" in data["serial"]:
                    cfg["serial"]["baudrate"] = int(data["serial"]["baudrate"])
            if "ble" in data:
                cfg.setdefault("ble", {})
                if "device_name" in data["ble"]:
                    cfg["ble"]["device_name"] = data["ble"]["device_name"]
                if "adapter" in data["ble"]:
                    cfg["ble"]["adapter"] = data["ble"]["adapter"]
                if "enabled" in data["ble"]:
                    cfg["ble"]["enabled"] = bool(data["ble"]["enabled"])
            if "ant" in data:
                cfg.setdefault("ant", {})
                if "enabled" in data["ant"]:
                    cfg["ant"]["enabled"] = bool(data["ant"]["enabled"])
                if "device_id" in data["ant"]:
                    try:
                        cfg["ant"]["device_id"] = int(data["ant"]["device_id"] or 0)
                    except (TypeError, ValueError):
                        pass
                if "network_key" in data["ant"]:
                    cfg["ant"]["network_key"] = data["ant"]["network_key"] or ""
            if "bridge" in data:
                cfg.setdefault("bridge", {})
                if "max_gear" in data["bridge"]:
                    try:
                        cfg["bridge"]["max_gear"] = int(data["bridge"]["max_gear"])
                    except (TypeError, ValueError):
                        pass
            if "input" in data:
                cfg.setdefault("input", {})
                inp = data["input"] or {}
                for key in ("enabled", "shift_clears_erg"):
                    if key in inp:
                        cfg["input"][key] = bool(inp[key])
                if "backend" in inp:
                    cfg["input"]["backend"] = str(inp["backend"] or "both")
                for key in ("repeat_delay", "repeat_interval"):
                    if key in inp:
                        try:
                            cfg["input"][key] = float(inp[key])
                        except (TypeError, ValueError):
                            pass
                if isinstance(inp.get("gpio"), dict):
                    gpio = cfg["input"].setdefault("gpio", {})
                    for key in ("up_pin", "down_pin"):
                        if key in inp["gpio"]:
                            try:
                                gpio[key] = int(inp["gpio"][key])
                            except (TypeError, ValueError):
                                pass
                    if "bounce_time" in inp["gpio"]:
                        try:
                            gpio["bounce_time"] = float(inp["gpio"]["bounce_time"])
                        except (TypeError, ValueError):
                            pass
                    if "active_low" in inp["gpio"]:
                        gpio["active_low"] = bool(inp["gpio"]["active_low"])
                if isinstance(inp.get("evdev"), dict):
                    evdev_cfg = cfg["input"].setdefault("evdev", {})
                    for key in ("device", "up_key", "down_key"):
                        if key in inp["evdev"]:
                            evdev_cfg[key] = str(inp["evdev"][key] or "")
            if "logging" in data:
                cfg.setdefault("logging", {})
                if "log_raw_frames" in data["logging"]:
                    cfg["logging"]["log_raw_frames"] = bool(
                        data["logging"]["log_raw_frames"]
                    )
            if "strava" in data:
                cfg.setdefault("strava", {})
                strava_data = data["strava"] or {}
                for key in (
                    "client_id",
                    "client_secret",
                    "refresh_token",
                    "access_token",
                    "token_file",
                ):
                    # Empty secret fields mean "keep the stored value".
                    if key in strava_data and strava_data[key]:
                        cfg["strava"][key] = strava_data[key]
                for key in ("auto_upload", "private"):
                    if key in strava_data:
                        cfg["strava"][key] = bool(strava_data[key])
                if strava_data.get("clear_credentials"):
                    for key in ("client_secret", "refresh_token", "access_token"):
                        cfg["strava"].pop(key, None)
            if "email" in data:
                cfg.setdefault("email", {})
                email_data = data["email"] or {}
                for key in (
                    "host",
                    "username",
                    "password",
                    "from_addr",
                    "to_addr",
                    "subject_prefix",
                ):
                    # Empty secret/identity fields mean "keep the stored value".
                    if key in email_data and email_data[key]:
                        cfg["email"][key] = email_data[key]
                if "port" in email_data and email_data["port"]:
                    try:
                        cfg["email"]["port"] = int(email_data["port"])
                    except (TypeError, ValueError):
                        pass
                for key in ("auto_send", "use_tls", "use_ssl"):
                    if key in email_data:
                        cfg["email"][key] = bool(email_data[key])
                if email_data.get("clear_password"):
                    cfg["email"].pop("password", None)

            dump_yaml_file(cfg_path, cfg)
            return JSONResponse({"ok": True})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
