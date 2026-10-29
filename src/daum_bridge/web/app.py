"""Web UI and JSON API for the daum-bridge.

The UI has two jobs: show what the cockpit and the trainer connection are doing,
and let the rider change something (gear, target power, configuration) without
touching the CLI.

This module only assembles the application: it creates the shared template
environment and asks :mod:`daum_bridge.web.routes` to attach the endpoints. The
routes themselves live in one module per concern (pages, state, rides,
integrations, control, config), so adding an endpoint does not mean editing a
600-line function.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import __version__
from ..formatting import format_datetime, format_duration
from .routes import register_routes

log = logging.getLogger(__name__)


def create_app(bridge) -> FastAPI:
    """Build the FastAPI application for ``bridge``.

    ``bridge`` may be ``None``, in which case every route answers with an
    empty/"disconnected" payload instead of failing; that keeps the UI usable
    for a quick look at the recorded rides even without a running bridge.
    """
    app = FastAPI(title="daum-bridge", version=__version__)

    base_dir = Path(__file__).parent
    templates = Jinja2Templates(directory=str(base_dir / "templates"))
    # Ride timestamps and durations are formatted by the shared helpers so the
    # web UI and the email export render them identically.
    templates.env.filters["dt"] = format_datetime
    templates.env.filters["duration"] = format_duration

    register_routes(app, bridge, templates)

    try:
        app.mount(
            "/static",
            StaticFiles(directory=str(base_dir / "static")),
            name="static",
        )
    except Exception:
        log.debug("Static directory not mounted")

    return app
