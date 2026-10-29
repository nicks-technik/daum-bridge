"""Routes for external services (currently Strava).

Uploading is deliberately explicit: a ride is uploaded because the rider asked
for it (or because ``strava.auto_upload`` is enabled), never as a side effect of
viewing a page.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

log = logging.getLogger(__name__)


def register(app: FastAPI, bridge) -> None:
    """Register the integration routes on ``app``."""

    @app.get("/api/strava/status")
    async def strava_status():
        try:
            from ...integrations.strava import StravaClient

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
            from ... import history

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
                    # Fall back to the in-memory summary (no samples) so a
                    # freshly finished ride can still be submitted.
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
