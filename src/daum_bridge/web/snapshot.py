"""Serialisable snapshots of the bridge state.

Several JSON endpoints expose the same handful of values: ``/api/state`` for the
live UI, ``/api/status`` for simple clients and ``/api/diagnostics`` for health
checks. Building those dicts here, once, keeps the contract identical everywhere
and means a new field only has to be added in one place.

There is one intentional difference: ``/api/status`` renders the cockpit address
as hex for humans, while ``/api/state`` returns the raw integer for clients that
parse it. Both start from :func:`state_snapshot`.
"""

from __future__ import annotations

import time
from typing import Optional


def state_snapshot(bridge) -> dict:
    """Return the cockpit values reported by the last protocol frame."""
    state = bridge.state
    total_distance = getattr(state, "total_distance", 0.0)
    return {
        "connected": state.connected,
        "power": state.power,
        "cadence": state.cadence,
        "speed": state.speed,
        "gear": state.gear,
        "heart_rate": state.heart_rate,
        "program": state.program,
        "cockpit_address": state.cockpit_address,
        "distance": total_distance,
        "total_distance": total_distance,
        "elapsed_time": getattr(state, "elapsed_time", 0),
        "resistance_level": getattr(state, "resistance_level", 0),
    }


def bridge_snapshot(bridge) -> dict:
    """Return the load-control and connection values owned by the bridge."""
    return {
        "target_watt": getattr(bridge, "_target_watt", 0),
        "erg_control_granted": getattr(bridge, "_erg_control_granted", False),
        "target_resistance_percent": getattr(bridge, "_target_resistance_pct", 0.0),
        "target_grade_percent": getattr(bridge, "_target_grade_pct", None),
        "app_connected": getattr(bridge, "_app_connected", False),
        # Kept for API compatibility with older clients; both keys now describe
        # the single "is an FTMS client attached" flag.
        "client_connected": getattr(bridge, "_app_connected", False),
        "virtual_shifting": getattr(bridge, "_virtual_shifting_enabled", True),
        "ride_paused": getattr(bridge, "_ride_paused", False),
        "input": bridge.input_status() if hasattr(bridge, "input_status") else {},
    }


def format_cockpit_address(address) -> Optional[str]:
    """Render the cockpit address as ``0x1A``; ``None`` when unknown."""
    if address is None:
        return None
    try:
        return f"0x{int(address):02X}"
    except (TypeError, ValueError):
        return None


def diagnostics_snapshot(bridge) -> dict:
    """Return connection health, uptimes and a compact state summary.

    This is a *read-only* view. The connection timestamps are recorded when the
    connection is established (see ``DaumBridge._app_connected``), so polling
    diagnostics can no longer restart the "app connected for" timer.
    """
    now = time.time()
    uptime = now - getattr(bridge, "_start_time", now)
    serial_since = getattr(bridge, "_serial_connected_time")
    app_since = getattr(bridge, "_app_connected_time")
    state = state_snapshot(bridge)
    ant_backend = getattr(bridge, "_ant_backend", None)
    return {
        "serial_connected": (
            getattr(bridge.protocol, "_address_found", False) if bridge.protocol else False
        ),
        "ble_enabled": getattr(getattr(bridge.config, "ble", None), "enabled", False),
        "ble_backend_running": bridge._ble_backend is not None,
        "ant_enabled": getattr(getattr(bridge.config, "ant", None), "enabled", False),
        "ant_running": bool(
            ant_backend is not None and getattr(ant_backend, "running", False)
        ),
        "ant_last_error": getattr(ant_backend, "last_error", None),
        "target_watt": getattr(bridge, "_target_watt", 0),
        "target_resistance_percent": getattr(bridge, "_target_resistance_pct", 0.0),
        "target_grade_percent": getattr(bridge, "_target_grade_pct", None),
        "erg_control_granted": getattr(bridge, "_erg_control_granted", False),
        "consecutive_errors": getattr(bridge, "_consecutive_errors", 0),
        "app_connected": getattr(bridge, "_app_connected", False),
        "virtual_shifting_enabled": getattr(bridge, "_virtual_shifting_enabled", True),
        "input": bridge.input_status() if hasattr(bridge, "input_status") else {},
        "uptime_seconds": int(uptime),
        "serial_connected_seconds": int(now - serial_since) if serial_since else None,
        "app_connected_seconds": int(now - app_since) if app_since else None,
        "state": {
            "power": state["power"],
            "cadence": state["cadence"],
            "speed": state["speed"],
            "gear": state["gear"],
            "heart_rate": state["heart_rate"],
            "program": state["program"],
            "connected": state["connected"],
            "distance": state["distance"],
            "elapsed_time": state["elapsed_time"],
        },
    }


def ride_summary(ride: dict) -> dict:
    """Drop the trackpoints from a ride dict for API responses."""
    return {key: value for key, value in ride.items() if key != "samples"}
