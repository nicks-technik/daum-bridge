from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

log = logging.getLogger(__name__)


def create_app(bridge) -> FastAPI:
    app = FastAPI(title="daum-bridge", version="0.1.0")
    
    base_dir = Path(__file__).parent
    templates = Jinja2Templates(directory=str(base_dir / "templates"))
    
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

    @app.get("/api/config")
    async def get_config():
        try:
            from ..config import Config
            cfg = Config.load()
            data = {
                "serial": {"port": cfg.serial.port, "baudrate": cfg.serial.baudrate},
                "ble": {"enabled": cfg.ble.enabled, "adapter": cfg.ble.adapter, "device_name": cfg.ble.device_name},
                "ant": {"enabled": getattr(cfg.ant, 'enabled', False), "device_path": getattr(cfg.ant, 'device_path', "")},
                "web": {"enabled": cfg.web.enabled, "host": cfg.web.host, "port": cfg.web.port},
                "logging": {"level": cfg.logging.level, "log_raw_frames": cfg.logging.log_raw_frames},
                "bridge": {"poll_interval": cfg.bridge.poll_interval}
            }
            return JSONResponse(data)
        except Exception as e:
            return JSONResponse({"error": str(e)})

    @app.post("/api/config")
    async def post_config(data: dict):
        try:
            import yaml
            cfg_path = Path('config.yaml')
            if not cfg_path.exists():
                from shutil import copyfile
                copyfile('config.example.yaml', 'config.yaml')
            with open(cfg_path) as f:
                cfg = yaml.safe_load(f) or {}
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
                if 'device_path' in data['ant']:
                    cfg['ant']['device_path'] = data['ant']['device_path'] or ''
            if 'logging' in data:
                cfg.setdefault('logging', {})
                if 'log_raw_frames' in data['logging']:
                    cfg['logging']['log_raw_frames'] = bool(data['logging']['log_raw_frames'])
            with open(cfg_path, 'w') as f:
                yaml.safe_dump(cfg, f, sort_keys=False)
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
            "app_connected": getattr(bridge, '_app_connected', False) or getattr(bridge, '_client_connected', False),
            "client_connected": getattr(bridge, '_client_connected', False),
            "virtual_shifting": getattr(bridge, '_virtual_shifting_enabled', True),
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
            "target_watt": getattr(bridge, '_target_watt', 0),
            "erg_control_granted": getattr(bridge, '_erg_control_granted', False),
            "consecutive_errors": getattr(bridge, '_consecutive_errors', 0),
            "app_connected": getattr(bridge, '_app_connected', False) or getattr(bridge, '_client_connected', False),
            "virtual_shifting_enabled": getattr(bridge, '_virtual_shifting_enabled', True),
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
