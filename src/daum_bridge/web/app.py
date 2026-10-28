from __future__ import annotations

import logging
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
        state = bridge.state if bridge else None
        return templates.TemplateResponse("index.html", {
            "request": request,
            "state": state,
        })

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
        if bridge:
            bridge.set_target_watt(int(watts))
        return JSONResponse({"ok": True, "watts": watts})

    return app
