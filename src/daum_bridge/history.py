"""Persistence for recorded rides.

Each finished ride is stored as a JSON file in the ``rides/`` directory
(override with ``DAUM_RIDES_DIR``). The on-disk copy is what makes it
possible to upload a ride to Strava later, e.g. after restarting the
bridge or from the command line.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def rides_dir() -> Path:
    """Return (and create) the directory used to store ride JSON files."""
    path = Path(os.environ.get("DAUM_RIDES_DIR", "rides"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_id(ride_id: str) -> str:
    cleaned = "".join(c for c in str(ride_id) if c.isalnum() or c in "-_.").strip(".")
    return cleaned or f"ride-{int(time.time())}"


def make_ride_id(ride: dict) -> str:
    """Derive a filesystem-safe, human readable id from a ride."""
    if ride.get("id"):
        return _safe_id(str(ride["id"]))
    start = ride.get("start")
    if start:
        try:
            return time.strftime("%Y-%m-%dT%H-%M-%S", time.localtime(float(start)))
        except (TypeError, ValueError, OSError):
            pass
    return f"ride-{int(time.time())}"


def save_ride(ride: dict, directory: Optional[Path | str] = None) -> str:
    """Persist ``ride`` and return its id. Writes atomically."""
    directory = Path(directory) if directory else rides_dir()
    directory.mkdir(parents=True, exist_ok=True)
    data = dict(ride)
    data["id"] = make_ride_id(data)

    target = directory / f"{data['id']}.json"
    suffix = 1
    while target.exists():
        # Do not silently overwrite an earlier ride recorded in the same second.
        suffix += 1
        target = directory / f"{data['id']}-{suffix}.json"
    data["id"] = target.stem

    tmp = target.with_suffix(".json.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f)
        tmp.replace(target)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
    log.info("Saved ride %s (%d samples)", data["id"], len(data.get("samples") or []))
    return data["id"]


def _read_ride(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        log.debug("Cannot read ride %s: %s", path, e)
        return None
    if not isinstance(data, dict):
        return None
    data.setdefault("id", path.stem)
    return data


def load_ride(ride_id: str, directory: Optional[Path | str] = None) -> Optional[dict]:
    """Load a single ride by id. Returns ``None`` for unknown/invalid ids."""
    if not ride_id or not _ID_RE.match(str(ride_id)):
        return None
    directory = Path(directory) if directory else rides_dir()
    path = directory / f"{ride_id}.json"
    if not path.exists():
        return None
    return _read_ride(path)


def list_rides(
    limit: int = 50,
    directory: Optional[Path | str] = None,
    include_samples: bool = False,
) -> list[dict]:
    """Return rides newest first.

    Samples are replaced by ``has_samples``/``sample_count`` unless
    ``include_samples`` is true, keeping API responses small.
    """
    directory = Path(directory) if directory else rides_dir()
    if not directory.exists():
        return []
    rides: list[dict] = []
    for path in directory.glob("*.json"):
        ride = _read_ride(path)
        if ride is None:
            continue
        if not include_samples:
            samples = ride.pop("samples", None) or []
            ride["has_samples"] = bool(samples)
            ride["sample_count"] = len(samples)
        rides.append(ride)
    rides.sort(key=lambda r: float(r.get("start") or 0), reverse=True)
    return rides[: max(0, int(limit))]


def latest_ride(directory: Optional[Path | str] = None, include_samples: bool = True) -> Optional[dict]:
    rides = list_rides(limit=1, directory=directory, include_samples=include_samples)
    return rides[0] if rides else None
