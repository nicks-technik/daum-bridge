"""HTTP route groups for the web UI and the JSON API.

Each module registers one coherent group of endpoints: pages, live state,
recorded rides, external integrations, load control and configuration.
:func:`create_app` only calls :func:`register_routes`, so adding an endpoint
touches one small module instead of a 600-line function, and a reader can find
"the ride download" without scrolling past the configuration form.
"""

from __future__ import annotations

from . import config, control, integrations, pages, rides, state


def register_routes(app, bridge, templates) -> None:
    """Attach every route group to ``app``.

    ``bridge`` may be ``None`` (the UI is then read-only and reports
    "disconnected"); ``templates`` is the shared Jinja environment created by
    :func:`daum_bridge.web.app.create_app`.
    """
    pages.register(app, bridge, templates)
    state.register(app, bridge)
    rides.register(app, bridge)
    integrations.register(app, bridge)
    control.register(app, bridge)
    config.register(app)
