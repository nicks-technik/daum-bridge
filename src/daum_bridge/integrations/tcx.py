"""Build TCX activity files from recorded ride data.

Strava (and most other training platforms) accept TCX uploads. The Daum
protocol does not provide GPS data, so rides are represented as indoor
activities with power/cadence/heart-rate and a distance derived from the
cockpit's odometer or speed.

The generated document follows the Garmin Training Center Database v2
schema (``http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2``).
"""
from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from ..numbers import as_float

log = logging.getLogger(__name__)

TCX_NS = "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"
ACTIVITY_EXT_NS = "http://www.garmin.com/xmlschemas/ActivityExtension/v2"

ET.register_namespace("", TCX_NS)
ET.register_namespace("garmin", ACTIVITY_EXT_NS)

#: Default title used when a ride has no name.
DEFAULT_NAME = "Daum 8008 TRS Ride"


def _fmt_time(timestamp: float) -> str:
    """Format a UNIX timestamp as an ISO-8601 UTC string for TCX."""
    return datetime.fromtimestamp(float(timestamp), tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _element(parent: ET.Element, tag: str, text: Any = None, ns: str = TCX_NS) -> ET.Element:
    el = ET.SubElement(parent, f"{{{ns}}}{tag}")
    if text is not None:
        el.text = str(text)
    return el


def _normalize_samples(ride: dict, samples: Optional[Iterable[dict]]) -> list[dict]:
    """Return samples sorted by elapsed time with numeric, validated fields."""
    if samples is None:
        samples = ride.get("samples") or []
    ride_start = as_float(ride.get("start"), time.time())
    points: list[dict] = []
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        if sample.get("t") is not None:
            t = as_float(sample.get("t"), -1.0)
        elif sample.get("timestamp") is not None:
            t = as_float(sample.get("timestamp")) - ride_start
        else:
            continue
        if t < 0:
            continue
        point = {"t": t}
        for key in ("power", "cadence", "speed", "heart_rate"):
            value = sample.get(key)
            if value is not None:
                point[key] = as_float(value)
        if sample.get("distance") is not None:
            point["distance"] = as_float(sample.get("distance"))  # km, cumulative
        points.append(point)
    points.sort(key=lambda p: p["t"])
    return points


def _fallback_samples(ride: dict) -> list[dict]:
    """Synthesize start/end points when no samples were recorded."""
    duration = max(0.0, as_float(ride.get("duration")))
    point = {
        "power": as_float(ride.get("avg_power")),
        "cadence": as_float(ride.get("avg_cadence")),
        "heart_rate": as_float(ride.get("avg_heart_rate")),
        "speed": 0.0,
        "distance": 0.0,
    }
    end = dict(point)
    end["distance"] = as_float(ride.get("distance"))
    return [dict(point, t=0.0), dict(end, t=duration)]


def _trackpoints(ride: dict, points: list[dict]) -> list[dict]:
    """Attach absolute times and cumulative distance (meters) to points."""
    ride_start = as_float(ride.get("start"), time.time())
    start_time = ride_start or time.time()
    track: list[dict] = []
    distance_m = 0.0
    prev_t: Optional[float] = None
    for point in points:
        elapsed = point["t"]
        # Prefer a cumulative distance supplied by the cockpit odometer.
        if "distance" in point:
            distance_m = max(distance_m, point["distance"] * 1000.0)
        elif prev_t is not None:
            distance_m += max(0.0, point.get("speed", 0.0)) * (elapsed - prev_t) / 3.6
        prev_t = elapsed
        track.append({
            "time": start_time + elapsed,
            "elapsed": elapsed,
            "distance_m": distance_m,
            **{k: v for k, v in point.items() if k in ("power", "cadence", "speed", "heart_rate")},
        })
    return track


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def build_tcx(ride: dict, samples: Optional[Iterable[dict]] = None) -> str:
    """Build a TCX document for ``ride`` and return it as a string.

    ``ride`` is the summary dict persisted by the bridge (``start``,
    ``duration``, ``distance`` in km, ``avg_power``, ``max_power``,
    ``work_kj`` ...). ``samples`` is a list of per-second dicts with ``t``
    (seconds since ride start) plus optional ``power``, ``cadence``,
    ``speed`` (km/h), ``heart_rate`` and cumulative ``distance`` (km).
    """
    points = _normalize_samples(ride, samples)
    if not points:
        points = _fallback_samples(ride)
    track = _trackpoints(ride, points)

    start = as_float(ride.get("start"), time.time())
    duration = max(as_float(ride.get("duration")), track[-1]["elapsed"] if track else 0.0)
    total_distance_m = track[-1]["distance_m"] if track else as_float(ride.get("distance")) * 1000.0

    powers = [p["power"] for p in track if "power" in p]
    heart_rates = [p["heart_rate"] for p in track if p.get("heart_rate", 0) > 0]
    cadences = [p["cadence"] for p in track if p.get("cadence", 0) > 0]
    speeds = [p["speed"] for p in track if p.get("speed", 0) > 0]

    avg_power = as_float(ride.get("avg_power"), _avg(powers))
    max_power = as_float(ride.get("max_power"), max(powers) if powers else 0.0)
    avg_hr = as_float(ride.get("avg_heart_rate"), _avg(heart_rates))
    max_hr = as_float(ride.get("max_heart_rate"), max(heart_rates) if heart_rates else 0.0)
    avg_cadence = as_float(ride.get("avg_cadence"), _avg(cadences))
    max_speed_ms = max(speeds) / 3.6 if speeds else 0.0
    work_kj = as_float(ride.get("work_kj"))

    root = ET.Element(f"{{{TCX_NS}}}TrainingCenterDatabase")
    activities = _element(root, "Activities")
    activity = _element(activities, "Activity")
    activity.set("Sport", "Biking")
    _element(activity, "Id", _fmt_time(start))

    lap = _element(activity, "Lap")
    lap.set("StartTime", _fmt_time(start))
    _element(lap, "TotalTimeSeconds", f"{duration:.1f}")
    _element(lap, "DistanceMeters", f"{total_distance_m:.1f}")
    if max_speed_ms > 0:
        _element(lap, "MaximumSpeed", f"{max_speed_ms:.3f}")
    if work_kj > 0:
        # Mechanical work in kJ is roughly equal to kcal burned.
        _element(lap, "Calories", int(round(work_kj)))
    if avg_hr > 0:
        avg_hr_el = _element(lap, "AverageHeartRateBpm")
        _element(avg_hr_el, "Value", int(round(avg_hr)))
    if max_hr > 0:
        max_hr_el = _element(lap, "MaximumHeartRateBpm")
        _element(max_hr_el, "Value", int(round(max_hr)))
    _element(lap, "Intensity", "Active")
    if avg_cadence > 0:
        _element(lap, "Cadence", int(round(avg_cadence)))
    _element(lap, "TriggerMethod", "Manual")

    track_el = _element(lap, "Track")
    for point in track:
        tp = _element(track_el, "Trackpoint")
        _element(tp, "Time", _fmt_time(point["time"]))
        if point["distance_m"] > 0:
            _element(tp, "DistanceMeters", f"{point['distance_m']:.1f}")
        if point.get("heart_rate", 0) > 0:
            hr_el = _element(tp, "HeartRateBpm")
            _element(hr_el, "Value", int(round(point["heart_rate"])))
        if point.get("cadence", 0) > 0:
            _element(tp, "Cadence", int(round(point["cadence"])))
        if point.get("power") is not None or point.get("speed", 0) > 0:
            extensions = _element(tp, "Extensions")
            tpx = _element(extensions, "TPX", ns=ACTIVITY_EXT_NS)
            if point.get("speed", 0) > 0:
                _element(tpx, "Speed", f"{point['speed'] / 3.6:.3f}", ns=ACTIVITY_EXT_NS)
            if point.get("power") is not None:
                _element(tpx, "Watts", int(round(point["power"])), ns=ACTIVITY_EXT_NS)

    creator = _element(activity, "Creator")
    _element(creator, "Name", "daum-bridge")
    _element(creator, "UnitId", 0)
    _element(creator, "ProductID", 0)
    version = _element(creator, "Version")
    _element(version, "VersionMajor", 1)
    _element(version, "VersionMinor", 0)

    # Keep the aggregate available to callers that want to log it.
    log.debug(
        "TCX built: %d trackpoints, %.1f s, %.1f m, avg %.0f W (max %.0f W)",
        len(track), duration, total_distance_m, avg_power, max_power,
    )

    return ET.tostring(root, encoding="unicode", xml_declaration=True)
