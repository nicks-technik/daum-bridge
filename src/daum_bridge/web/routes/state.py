"""Live state, diagnostics and log routes.

All values are built by :mod:`daum_bridge.web.snapshot`, so ``/api/state``,
``/api/status`` and ``/api/diagnostics`` cannot drift apart. The endpoints here
are strictly read-only: nothing about asking for the state may change it.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from ..snapshot import (
    bridge_snapshot,
    diagnostics_snapshot,
    format_cockpit_address,
    state_snapshot,
)


def register(app: FastAPI, bridge) -> None:
    """Register the live-state routes on ``app``."""

    @app.get("/api/state")
    async def api_state():
        if not bridge:
            return JSONResponse({"connected": False})
        # The full snapshot: cockpit values plus what the bridge is requesting.
        return JSONResponse({**state_snapshot(bridge), **bridge_snapshot(bridge)})

    @app.get("/api/status")
    async def api_status():
        if not bridge:
            return JSONResponse({"connected": False})
        state = state_snapshot(bridge)
        load = bridge_snapshot(bridge)
        return JSONResponse({
            "connected": state["connected"],
            "power": state["power"],
            "cadence": state["cadence"],
            "speed": state["speed"],
            "gear": state["gear"],
            "heart_rate": state["heart_rate"],
            "program": state["program"],
            # Human-readable here (e.g. "0x1A"); /api/state keeps the integer.
            "cockpit_address": format_cockpit_address(state["cockpit_address"]),
            "distance": state["distance"],
            "elapsed_time": state["elapsed_time"],
            "target_watt": load["target_watt"],
        })

    @app.get("/api/diagnostics")
    async def diagnostics():
        if not bridge:
            return JSONResponse({"error": "no bridge"})
        return JSONResponse(diagnostics_snapshot(bridge))

    @app.get("/api/logs")
    async def get_logs():
        if not bridge:
            return JSONResponse({"logs": []})
        try:
            logs = getattr(bridge, "_logs", [])[-200:]
            return JSONResponse({"logs": logs})
        except Exception:
            return JSONResponse({"logs": []})
