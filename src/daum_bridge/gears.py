"""Gear and resistance mapping for the Daum cockpit.

The Daum 8008 TRS is controlled either by an ERG target power or by a gear
(1..28). Training apps, however, speak FTMS/FE-C: they request a resistance
percentage or a road grade. The bridge therefore translates between the two
representations, and this module holds that translation.

Everything here is a pure function of its arguments — no protocol object, no
connection state — which is what makes the rounding behaviour easy to verify
(both ends of the range, the midpoint, and out-of-range input).
"""

from __future__ import annotations

from .numbers import as_float, as_int, clamp

#: Gears the Daum protocol accepts; 1 is the easiest, 28 the hardest.
GEAR_MIN = 1
GEAR_MAX = 28

#: Smallest *maximum* that still makes sense (a one-gear bike has no range).
MIN_MAX_GEAR = 2

#: Fallback when ``bridge.max_gear`` is missing or unusable.
DEFAULT_MAX_GEAR = 20


def clamp_max_gear(value) -> int:
    """Return the configured highest gear, clamped to the protocol range.

    A bike configured with 28 gears stops at 28, and a value of ``0`` (or a
    typo) falls back to :data:`DEFAULT_MAX_GEAR` instead of making every gear
    division-by-zero.
    """
    requested = as_int(value, DEFAULT_MAX_GEAR) or DEFAULT_MAX_GEAR
    return int(clamp(requested, MIN_MAX_GEAR, GEAR_MAX))


def gear_to_resistance_percent(gear: int, max_gear: int) -> float:
    """Map a Daum gear (1..``max_gear``) to a 0-100 % resistance level.

    Gear 1 is 0 % and ``max_gear`` is 100 %; the intermediate gears are spread
    evenly over the range. Gears outside the range are clamped, because sending
    an impossible gear to the cockpit silently does nothing.
    """
    gear_number = int(clamp(as_int(gear, GEAR_MIN), GEAR_MIN, max_gear))
    return round((gear_number - 1) / (max_gear - 1) * 100.0, 1)


def resistance_to_gear(percent: float, max_gear: int) -> int:
    """Map a 0-100 % resistance level to the nearest Daum gear.

    This is the inverse of :func:`gear_to_resistance_percent`. Unreadable input
    is treated as 0 %, matching the "no resistance requested" default.
    """
    level = clamp(as_float(percent, 0.0), 0.0, 100.0)
    gear = 1 + int(round(level / 100.0 * (max_gear - 1)))
    return int(clamp(gear, GEAR_MIN, max_gear))
