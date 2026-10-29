"""Load-control routes: shifting, target power and serial reconnect.

These are the endpoints behind the buttons in the UI. They are intentionally
stateless wrappers around :class:`~daum_bridge.bridge.DaumBridge` methods, so the
web UI, the CLI and the wired buttons all take the same code path.
"""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)


def register(app: FastAPI, bridge) -> None:
    """Register the load-control routes on ``app``."""

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
        """Close and reopen the serial port without stopping the bridge."""
        if not bridge:
            return JSONResponse({"ok": False, "error": "no bridge"})
        try:
            if bridge.serial_port and hasattr(bridge.serial_port, "close"):
                try:
                    bridge.serial_port.close()
                except Exception:
                    pass
            bridge.protocol = None
            bridge.serial_port = None
            bridge.connect()
            if bridge.protocol:
                try:
                    bridge.protocol.request_address()
                except Exception:
                    pass
            bridge._consecutive_errors = 0
            bridge._last_reconnect = time.time()
            return JSONResponse({"ok": True})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
