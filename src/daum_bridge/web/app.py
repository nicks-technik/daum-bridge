from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from starlette.concurrency import run_in_threadpool

log = logging.getLogger(__name__)


def _fmt_datetime(value) -> str:
    """Format a UNIX timestamp for display in templates."""
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(value)))
    except (TypeError, ValueError, OSError):
        return "-"


def _fmt_duration(value) -> str:
    """Format a duration in seconds as ``1h 05m`` / ``12m 30s``."""
    try:
        total = max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        total = 0
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def create_app(bridge) -> FastAPI:
    app = FastAPI(title="daum-bridge", version="0.1.0")
    
    base_dir = Path(__file__).parent
    templates = Jinja2Templates(directory=str(base_dir / "templates"))
    templates.env.filters["dt"] = _fmt_datetime
    templates.env.filters["duration"] = _fmt_duration
    
    try:
        app.mount("/static", StaticFiles(directory=str(base_dir / "static")), name="static")
    except Exception:
        pass

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        try:
            state = bridge.state if bridge else None
            return templates.TemplateResponse(request, "index.html", {
                "state": state,
            })
        except Exception:
            return HTMLResponse("<html><body>daum-bridge</body></html>")

    @app.get("/config", response_class=HTMLResponse)
    async def config_page(request: Request):
        try:
            return templates.TemplateResponse(request, "config.html", {})
        except Exception:
            return HTMLResponse("<html><body>config</body></html>")

    @app.get("/logs", response_class=HTMLResponse)
    async def logs_page(request: Request):
        try:
            return templates.TemplateResponse(request, "logs.html", {})
        except Exception:
            return HTMLResponse("<html><body>logs</body></html>")

    @app.get("/history", response_class=HTMLResponse)
    async def history_page(request: Request):
        try:
            return templates.TemplateResponse(request, "history.html", {})
        except Exception:
            return HTMLResponse("<html><body>history</body></html>")

    @app.get("/downloads", response_class=HTMLResponse)
    async def downloads_page(request: Request):
        """List all recorded trainings, newest first, with TCX download links."""
        try:
            from .. import history
            rides = history.list_rides(limit=500)
            email_cfg = getattr(getattr(bridge, "config", None), "email", None)
            return templates.TemplateResponse(request, "downloads.html", {
                "rides": rides,
                "email_configured": bool(
                    email_cfg is not None and email_cfg.is_configured()
                ),
                "email_to": getattr(email_cfg, "to_addr", "") if email_cfg else "",
            })
        except Exception:
            log.exception("Could not render downloads page")
            return HTMLResponse("<html><body>downloads</body></html>")

    @app.get("/api/config")
    async def get_config():
        try:
            from ..config import Config
            cfg = Config.load()
            data = {
                "serial": {"port": cfg.serial.port, "baudrate": cfg.serial.baudrate},
                "ble": {"enabled": cfg.ble.enabled, "adapter": cfg.ble.adapter, "device_name": cfg.ble.device_name},
                "ant": {
                    "enabled": getattr(cfg.ant, 'enabled', False),
                    "device_id": getattr(cfg.ant, 'device_id', 0),
                    "network_key": getattr(cfg.ant, 'network_key', ""),
                },
                "strava": {
                    "auto_upload": getattr(cfg.strava, 'auto_upload', False),
                    "private": getattr(cfg.strava, 'private', False),
                    "client_id": getattr(cfg.strava, 'client_id', ""),
                    "token_file": getattr(cfg.strava, 'token_file', "strava.tokens.json"),
                    "configured": bool(
                        getattr(cfg.strava, 'refresh_token', "")
                        or getattr(cfg.strava, 'access_token', "")
                    ),
                },
                "web": {"enabled": cfg.web.enabled, "host": cfg.web.host, "port": cfg.web.port},
                "email": {
                    "host": getattr(cfg.email, 'host', ""),
                    "port": getattr(cfg.email, 'port', 587),
                    "username": getattr(cfg.email, 'username', ""),
                    "from_addr": getattr(cfg.email, 'from_addr', ""),
                    "to_addr": getattr(cfg.email, 'to_addr', ""),
                    "auto_send": getattr(cfg.email, 'auto_send', False),
                    "use_tls": getattr(cfg.email, 'use_tls', True),
                    "use_ssl": getattr(cfg.email, 'use_ssl', False),
                    "subject_prefix": getattr(cfg.email, 'subject_prefix', "Daum training"),
                    "configured": getattr(cfg.email, 'is_configured', lambda: False)(),
                },
                "logging": {"level": cfg.logging.level, "log_raw_frames": cfg.logging.log_raw_frames},
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
            from ..config import dump_yaml_file, load_yaml_file
            cfg_path = Path('config.yaml')
            if not cfg_path.exists():
                example = Path('config.example.yaml')
                if example.exists():
                    from shutil import copyfile
                    copyfile(example, cfg_path)
            cfg = load_yaml_file(cfg_path)
            if 'serial' in data:
                cfg.setdefault('serial', {})
                if 'port' in data['serial']:
                    cfg['serial']['port'] = data['serial']['port'] or None
                if 'baudrate' in data['serial']:
                    cfg['serial']['baudrate'] = int(data['serial']['baudrate'])
            if 'ble' in data:
                cfg.setdefault('ble', {})
                if 'device_name' in data['ble']:
                    cfg['ble']['device_name'] = data['ble']['device_name']
                if 'adapter' in data['ble']:
                    cfg['ble']['adapter'] = data['ble']['adapter']
                if 'enabled' in data['ble']:
                    cfg['ble']['enabled'] = bool(data['ble']['enabled'])
            if 'ant' in data:
                cfg.setdefault('ant', {})
                if 'enabled' in data['ant']:
                    cfg['ant']['enabled'] = bool(data['ant']['enabled'])
                if 'device_id' in data['ant']:
                    try:
                        cfg['ant']['device_id'] = int(data['ant']['device_id'] or 0)
                    except (TypeError, ValueError):
                        pass
                if 'network_key' in data['ant']:
                    cfg['ant']['network_key'] = data['ant']['network_key'] or ''
            if 'bridge' in data:
                cfg.setdefault('bridge', {})
                if 'max_gear' in data['bridge']:
                    try:
                        cfg['bridge']['max_gear'] = int(data['bridge']['max_gear'])
                    except (TypeError, ValueError):
                        pass
            if 'input' in data:
                cfg.setdefault('input', {})
                inp = data['input'] or {}
                for key in ('enabled', 'shift_clears_erg'):
                    if key in inp:
                        cfg['input'][key] = bool(inp[key])
                if 'backend' in inp:
                    cfg['input']['backend'] = str(inp['backend'] or 'both')
                for key in ('repeat_delay', 'repeat_interval'):
                    if key in inp:
                        try:
                            cfg['input'][key] = float(inp[key])
                        except (TypeError, ValueError):
                            pass
                if isinstance(inp.get('gpio'), dict):
                    gpio = cfg['input'].setdefault('gpio', {})
                    for key in ('up_pin', 'down_pin'):
                        if key in inp['gpio']:
                            try:
                                gpio[key] = int(inp['gpio'][key])
                            except (TypeError, ValueError):
                                pass
                    if 'bounce_time' in inp['gpio']:
                        try:
                            gpio['bounce_time'] = float(inp['gpio']['bounce_time'])
                        except (TypeError, ValueError):
                            pass
                    if 'active_low' in inp['gpio']:
                        gpio['active_low'] = bool(inp['gpio']['active_low'])
                if isinstance(inp.get('evdev'), dict):
                    evdev_cfg = cfg['input'].setdefault('evdev', {})
                    for key in ('device', 'up_key', 'down_key'):
                        if key in inp['evdev']:
                            evdev_cfg[key] = str(inp['evdev'][key] or '')
            if 'logging' in data:
                cfg.setdefault('logging', {})
                if 'log_raw_frames' in data['logging']:
                    cfg['logging']['log_raw_frames'] = bool(data['logging']['log_raw_frames'])
            if 'strava' in data:
                cfg.setdefault('strava', {})
                strava_data = data['strava'] or {}
                for key in ('client_id', 'client_secret', 'refresh_token', 'access_token', 'token_file'):
                    # Empty secret fields mean "keep the stored value".
                    if key in strava_data and strava_data[key]:
                        cfg['strava'][key] = strava_data[key]
                for key in ('auto_upload', 'private'):
                    if key in strava_data:
                        cfg['strava'][key] = bool(strava_data[key])
                if 'clear_credentials' in strava_data and strava_data['clear_credentials']:
                    for key in ('client_secret', 'refresh_token', 'access_token'):
                        cfg['strava'].pop(key, None)
            if 'email' in data:
                cfg.setdefault('email', {})
                email_data = data['email'] or {}
                for key in ('host', 'username', 'password', 'from_addr', 'to_addr', 'subject_prefix'):
                    # Empty secret/identity fields mean "keep the stored value".
                    if key in email_data and email_data[key]:
                        cfg['email'][key] = email_data[key]
                if 'port' in email_data and email_data['port']:
                    try:
                        cfg['email']['port'] = int(email_data['port'])
                    except (TypeError, ValueError):
                        pass
                for key in ('auto_send', 'use_tls', 'use_ssl'):
                    if key in email_data:
                        cfg['email'][key] = bool(email_data[key])
                if email_data.get('clear_password'):
                    cfg['email'].pop('password', None)
            dump_yaml_file(cfg_path, cfg)
            return JSONResponse({"ok": True})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @app.get("/api/state")
    async def api_state():
        if not bridge:
            return JSONResponse({"connected": False})
        s = bridge.state
        return JSONResponse({
            "connected": s.connected,
            "power": s.power,
            "cadence": s.cadence,
            "speed": s.speed,
            "gear": s.gear,
            "heart_rate": s.heart_rate,
            "program": s.program,
            "cockpit_address": s.cockpit_address,
            "distance": getattr(s, 'total_distance', 0.0),
            "total_distance": getattr(s, 'total_distance', 0.0),
            "elapsed_time": getattr(s, 'elapsed_time', 0),
            "resistance_level": getattr(s, 'resistance_level', 0),
            "target_watt": getattr(bridge, '_target_watt', 0),
            "erg_control_granted": getattr(bridge, '_erg_control_granted', False),
            "target_resistance_percent": getattr(bridge, '_target_resistance_pct', 0.0),
            "target_grade_percent": getattr(bridge, '_target_grade_pct', None),
            "app_connected": getattr(bridge, '_app_connected', False) or getattr(bridge, '_client_connected', False),
            "client_connected": getattr(bridge, '_client_connected', False),
            "virtual_shifting": getattr(bridge, '_virtual_shifting_enabled', True),
            "ride_paused": getattr(bridge, '_ride_paused', False),
            "input": bridge.input_status() if hasattr(bridge, "input_status") else {},
        })

    @app.get("/api/status")
    async def api_status():
        if not bridge:
            return JSONResponse({"connected": False})
        s = bridge.state
        return JSONResponse({
            "connected": s.connected,
            "power": s.power,
            "cadence": s.cadence,
            "speed": s.speed,
            "gear": s.gear,
            "heart_rate": s.heart_rate,
            "program": s.program,
            "cockpit_address": f"0x{s.cockpit_address:02X}" if getattr(s, 'cockpit_address', None) is not None else None,
            "distance": getattr(s, 'total_distance', 0.0),
            "elapsed_time": getattr(s, 'elapsed_time', 0),
            "target_watt": getattr(bridge, '_target_watt', 0),
        })

    @app.get("/api/diagnostics")
    async def diagnostics():
        if not bridge:
            return JSONResponse({"error": "no bridge"})
        now = time.time()
        uptime = now - getattr(bridge, '_start_time', now)
        serial_since = getattr(bridge, '_serial_connected_time')
        serial_since_sec = int(now - serial_since) if serial_since else None
        app_since = getattr(bridge, '_app_connected_time')
        if (getattr(bridge, '_app_connected', False) or getattr(bridge, '_client_connected', False)) and app_since is None:
            bridge._app_connected_time = now
            app_since = bridge._app_connected_time
        app_since_sec = int(now - app_since) if app_since else None
        s = bridge.state
        return JSONResponse({
            "serial_connected": getattr(bridge.protocol, '_address_found', False) if bridge.protocol else False,
            "ble_enabled": getattr(getattr(bridge.config, 'ble', None), 'enabled', False),
            "ble_backend_running": bridge._ble_backend is not None,
            "ant_enabled": getattr(getattr(bridge.config, 'ant', None), 'enabled', False),
            "ant_running": bool(
                getattr(bridge, '_ant_backend', None)
                and getattr(bridge._ant_backend, 'running', False)
            ),
            "ant_last_error": getattr(
                getattr(bridge, '_ant_backend', None), 'last_error', None
            ),
            "target_watt": getattr(bridge, '_target_watt', 0),
            "target_resistance_percent": getattr(bridge, '_target_resistance_pct', 0.0),
            "target_grade_percent": getattr(bridge, '_target_grade_pct', None),
            "erg_control_granted": getattr(bridge, '_erg_control_granted', False),
            "consecutive_errors": getattr(bridge, '_consecutive_errors', 0),
            "app_connected": getattr(bridge, '_app_connected', False) or getattr(bridge, '_client_connected', False),
            "virtual_shifting_enabled": getattr(bridge, '_virtual_shifting_enabled', True),
            "input": bridge.input_status() if hasattr(bridge, "input_status") else {},
            "uptime_seconds": int(uptime),
            "serial_connected_seconds": serial_since_sec,
            "app_connected_seconds": app_since_sec,
            "state": {
                "power": s.power,
                "cadence": s.cadence,
                "speed": s.speed,
                "gear": s.gear,
                "heart_rate": s.heart_rate,
                "program": s.program,
                "connected": s.connected,
                "distance": getattr(s, 'total_distance', 0.0),
                "elapsed_time": getattr(s, 'elapsed_time', 0),
            }
        })

    @app.get("/api/logs")
    async def get_logs():
        if not bridge:
            return JSONResponse({"logs": []})
        try:
            logs = getattr(bridge, '_logs', [])[-200:]
            return JSONResponse({"logs": logs})
        except Exception:
            return JSONResponse({"logs": []})

    @app.get("/api/history")
    async def get_history():
        try:
            from .. import history
            rides = history.list_rides(limit=50)
            if not rides and bridge:
                rides = [
                    {k: v for k, v in ride.items() if k != "samples"}
                    for ride in reversed(getattr(bridge, '_ride_history', [])[-50:])
                ]
            return JSONResponse({"rides": rides})
        except Exception:
            return JSONResponse({"rides": []})

    @app.get("/api/rides/{ride_id}/tcx")
    async def download_ride_tcx(ride_id: str):
        """Download a recorded ride as TCX (manual upload, no Strava API needed)."""
        try:
            from .. import history
            from ..integrations.tcx import build_tcx
            ride = history.load_ride(ride_id)
            if ride is None:
                return JSONResponse(
                    {"ok": False, "error": f"Ride '{ride_id}' not found"}, status_code=404
                )
            tcx = build_tcx(ride)
            return Response(
                content=tcx,
                media_type="application/vnd.garmin.tcx+xml",
                headers={
                    "Content-Disposition": f'attachment; filename="{ride_id}.tcx"'
                },
            )
        except Exception as e:
            log.exception("TCX export failed")
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @app.post("/api/rides/{ride_id}/email")
    async def email_ride(ride_id: str, payload: Optional[dict] = None):
        """Send a recorded ride's TCX file by email."""
        if not bridge:
            return JSONResponse({"ok": False, "error": "No bridge running"}, status_code=400)
        try:
            from .. import history
            ride = history.load_ride(ride_id)
            if ride is None:
                return JSONResponse(
                    {"ok": False, "error": f"Ride '{ride_id}' not found"}, status_code=404
                )
            body = payload or {}
            result = await run_in_threadpool(bridge.email_ride, ride, body.get("to"))
            return JSONResponse(result, status_code=200 if result.get("ok") else 400)
        except Exception as e:
            log.exception("Email endpoint failed")
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @app.get("/api/email/status")
    async def email_status():
        try:
            email_cfg = getattr(getattr(bridge, "config", None), "email", None)
            return JSONResponse({
                "configured": bool(email_cfg is not None and email_cfg.is_configured()),
                "auto_send": bool(getattr(email_cfg, "auto_send", False)),
                "to": getattr(email_cfg, "to_addr", ""),
                "last_result": getattr(bridge, "_last_email_result", None),
            })
        except Exception as e:
            return JSONResponse({"configured": False, "error": str(e)})

    @app.post("/api/ride/finish")
    async def finish_ride():
        """Finish the current workout now and write its TCX file."""
        if not bridge:
            return JSONResponse({"ok": False, "error": "No bridge running"}, status_code=400)
        try:
            ride = await run_in_threadpool(bridge.finish_current_ride)
        except Exception as e:
            log.exception("Finishing ride failed")
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
        if ride is None:
            return JSONResponse(
                {"ok": False, "error": "No ride in progress"}, status_code=400
            )
        summary = {k: v for k, v in ride.items() if k != "samples"}
        ride_id = summary.get("id")
        return JSONResponse({
            "ok": True,
            "ride": summary,
            "tcx_url": f"/api/rides/{ride_id}/tcx" if ride_id else None,
            "downloads_url": "/downloads",
        })

    @app.post("/api/ride/resume")
    async def resume_ride():
        """Resume ride recording after a manual finish."""
        if not bridge:
            return JSONResponse({"ok": False, "error": "No bridge running"}, status_code=400)
        bridge.resume_ride_recording()
        return JSONResponse({"ok": True, "recording": True})

    @app.get("/api/strava/status")
    async def strava_status():
        try:
            from ..integrations.strava import StravaClient
            strava_cfg = getattr(getattr(bridge, "config", None), "strava", None)
            configured = False
            if strava_cfg is not None:
                configured = StravaClient.from_config(strava_cfg).is_configured()
            return JSONResponse({
                "configured": configured,
                "auto_upload": bool(getattr(strava_cfg, "auto_upload", False)),
                "private": bool(getattr(strava_cfg, "private", False)),
                "last_result": getattr(bridge, "_last_strava_result", None),
            })
        except Exception as e:
            return JSONResponse({"configured": False, "error": str(e)})

    @app.post("/api/strava/upload")
    async def strava_upload(payload: Optional[dict] = None):
        if not bridge:
            return JSONResponse({"ok": False, "error": "No bridge running"}, status_code=400)
        body = payload or {}
        try:
            from .. import history
            ride = None
            ride_id = body.get("ride_id")
            if ride_id:
                ride = history.load_ride(str(ride_id))
                if ride is None:
                    return JSONResponse(
                        {"ok": False, "error": f"Ride '{ride_id}' not found"}, status_code=404
                    )
            else:
                ride = history.latest_ride(include_samples=True)
                if ride is None and getattr(bridge, "_ride_history", None):
                    ride = dict(bridge._ride_history[-1])
            if ride is None:
                return JSONResponse(
                    {"ok": False, "error": "No recorded ride available to upload"},
                    status_code=400,
                )
            result = await run_in_threadpool(
                bridge.upload_ride_to_strava,
                ride,
                body.get("name"),
                body.get("description"),
            )
            return JSONResponse(result, status_code=200 if result.get("ok") else 400)
        except Exception as e:
            log.exception("Strava upload endpoint failed")
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @app.post("/api/shift/up")
    async def shift_up():
        if bridge:
            bridge.shift_up()
        return JSONResponse({"ok": True})

    @app.post("/api/shift/down")
    async def shift_down():
        if bridge:
            bridge.shift_down()
        return JSONResponse({"ok": True})

    @app.post("/api/gear/{gear}")
    async def set_gear(gear: int):
        if bridge:
            bridge.set_gear(gear)
        return JSONResponse({"ok": True, "gear": gear})

    @app.post("/api/target/watt")
    async def set_target_watt(data: dict):
        watts = data.get("watts", 0)
        try:
            if bridge:
                bridge.set_target_watt(int(watts))
            return JSONResponse({"ok": True, "watts": int(watts)})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @app.post("/api/reconnect/serial")
    async def reconnect_serial():
        if not bridge:
            return JSONResponse({"ok": False, "error": "no bridge"})
        try:
            try:
                if bridge.serial_port and hasattr(bridge.serial_port, 'close'):
                    try:
                        bridge.serial_port.close()
                    except Exception:
                        pass
            except Exception:
                pass
            bridge.protocol = None
            bridge.serial_port = None
            try:
                bridge.connect()
                if bridge.protocol:
                    try:
                        bridge.protocol.request_address()
                    except Exception:
                        pass
                bridge._consecutive_errors = 0
                import time as _time
                bridge._last_reconnect = _time.time()
                return JSONResponse({"ok": True})
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    return app
