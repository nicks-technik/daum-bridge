"""HTML page routes.

Every page is a thin wrapper around a Jinja template. Rendering is wrapped in
:func:`_render` so a broken template degrades to a minimal page instead of
taking the whole web UI (and with it the gear controls) down.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

log = logging.getLogger(__name__)


def _render(
    templates,
    request: Request,
    template: str,
    context: dict,
    fallback: str,
) -> HTMLResponse:
    """Render ``template`` with ``context``, or a minimal HTML page on error."""
    try:
        return templates.TemplateResponse(request, template, context)
    except Exception:
        log.exception("Could not render %s", template)
        return HTMLResponse(f"<html><body>{fallback}</body></html>")


def register(app: FastAPI, bridge, templates) -> None:
    """Register the page routes on ``app``."""

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return _render(
            templates,
            request,
            "index.html",
            {"state": bridge.state if bridge else None},
            "daum-bridge",
        )

    @app.get("/config", response_class=HTMLResponse)
    async def config_page(request: Request):
        return _render(templates, request, "config.html", {}, "config")

    @app.get("/logs", response_class=HTMLResponse)
    async def logs_page(request: Request):
        return _render(templates, request, "logs.html", {}, "logs")

    @app.get("/history", response_class=HTMLResponse)
    async def history_page(request: Request):
        return _render(templates, request, "history.html", {}, "history")

    @app.get("/downloads", response_class=HTMLResponse)
    async def downloads_page(request: Request):
        """List all recorded trainings, newest first, with TCX download links."""
        try:
            from ... import history

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
