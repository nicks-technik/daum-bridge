"""Small numeric helpers shared across the bridge.

Values reach the bridge from three untrusted places: a YAML configuration file
(strings, ``null`` and typos), a JSON ride file written by an older version, and
BLE/FTMS frames that carry floats where an integer is required. Converting those
values must never abort a ride, so every helper here falls back to a default
instead of raising.

Keeping the conversions in one module also means the "how do we treat a broken
value" decision is made exactly once instead of being re-implemented (and
occasionally forgotten) in each caller.
"""

from __future__ import annotations


def as_float(value, default: float = 0.0) -> float:
    """Return ``value`` as a float, or ``default`` when it cannot be converted.

    ``None``, an empty string and arbitrary objects all yield ``default``; that
    is deliberate, because "missing" and "invalid" are handled identically by
    every caller (use the fallback value).
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value, default: int = 0) -> int:
    """Return ``value`` as an int, or ``default`` when it cannot be converted.

    Floats are truncated the way :class:`int` does it; callers that need proper
    rounding (for example a gear number) round explicitly before calling this.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def maybe_float(value):
    """Return ``value`` as a float, or ``None`` when it is not a number.

    Used by commands that arrive from an external app: an unreadable resistance
    or target power should be ignored, not applied as zero, so these callers
    need to distinguish "invalid" from a real ``0``.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def maybe_int(value):
    """Return ``value`` as an int, or ``None`` when it is not a number.

    The integer counterpart of :func:`maybe_float`; a BLE control point frame
    with a truncated payload must be dropped rather than treated as gear 0.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def clamp(value: float, low: float, high: float) -> float:
    """Constrain ``value`` to the inclusive range ``low`` .. ``high``.

    The Daum protocol silently rejects out-of-range gears and resistances, so
    clamping at the boundary is always better than sending a value the cockpit
    will ignore.
    """
    return max(low, min(high, value))
