"""Recorded-ride routes: history, TCX download, email and finish/resume.

A ride is identified by the id of its JSON file in the rides directory. These
endpoints therefore never need the in-memory recorder except as a fallback for
history when the directory is empty.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from ..snapshot import ride_summary

log = logging.getLogger(__name__)


def register(app: FastAPI, bridge) -> None:
    """Register the recorded-ride routes on ``app``."""

    @app.get("/api/history")
    async def get_history():
        try:
            from ... import history

            rides = history.list_rides(limit=50)
            if not rides and bridge:
                rides = [
                    ride_summary(ride)
                    for ride in reversed(getattr(bridge, "_ride_history", [])[-50:])
                ]
            return JSONResponse({"rides": rides})
        except Exception:
            return JSONResponse({"rides": []})

    @app.get("/api/rides/{ride_id}/tcx")
    async def download_ride_tcx(ride_id: str):
        """Download a recorded ride as TCX (manual upload, no Strava API needed)."""
        try:
            from ... import history
            from ...integrations.tcx import build_tcx

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
            from ... import history

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
        summary = ride_summary(ride)
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
