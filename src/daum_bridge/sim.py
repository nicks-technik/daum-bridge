"""Power simulation for FTMS/FE-C "SIM" (free ride) mode.

The Daum 8008 TRS brake only understands one thing: a target power. The
cockpit holds that power by loading the eddy-current brake and reports it back
in the run data. That is ERG mode, and it works well for workouts.

Free-riding apps (MyWhoosh, Zwift, ...) do not send a target power. They send a
road *grade* (FTMS opcode ``0x11`` / FE-C track simulation) and expect the
trainer to make the ride harder on a climb and easier on a descent. The Daum
has no incline motor, so the bridge has to do the translation itself:

1. the cockpit reports the rider's speed (rpm x gear);
2. the bridge turns speed + grade into the power a rider would need to hold
   that speed on that grade;
3. that power is sent to the cockpit as an ERG target.

Because the gear changes the speed the cockpit reports, gearing the bike up
raises the calculated power and therefore the brake load - which is exactly how
a virtual gear feels on a smart trainer.

The model is the classic cycling power equation (gravity + rolling resistance +
aerodynamic drag), ported from ``daumSIM.js`` in weinzmi/daumUSB2BLE. Every
function here is pure: no protocol object, no connection state, so the numbers
are trivial to verify in tests.
"""

from __future__ import annotations

import math

from .numbers import as_float, as_int, clamp

#: Acceleration due to gravity in m/s^2.
GRAVITY = 9.8067
#: Air density in kg/m^3 at 15 degrees Celsius and sea level.
AIR_DENSITY = 1.225
#: Drivetrain efficiency (chain/belt losses).
DRIVE_EFFICIENCY = 0.97
#: km/h -> m/s.
KMH_TO_MS = 1.0 / 3.6

#: The cockpit never reports less than 25 W and the protocol caps the brake at
#: 800 W, so simulated power is clamped into that window.
MIN_POWER_WATT = 25.0
MAX_POWER_WATT = 800.0


def simulated_power(
    speed_kmh: float,
    grade_percent: float = 0.0,
    *,
    rider_mass_kg: float = 80.0,
    bike_mass_kg: float = 9.0,
    crr: float = 0.004,
    cw: float = 0.51,
    max_grade_percent: float = 16.0,
    wind_mps: float = 0.0,
) -> float:
    """Return the power (W) needed to ride ``speed_kmh`` up ``grade_percent``.

    ``crr`` is the coefficient of rolling resistance and ``cw`` the drag area
    (``Cd * A``) in m^2. ``grade_percent`` is clamped to
    ``+/- max_grade_percent`` so a descent does not produce negative load and a
    wall in the app does not demand a brake power the bike cannot hold.

    The result is *not* clamped to the brake range; :func:`clamp_power` does
    that, so callers can still tell "too easy to be real" from "25 W".
    """
    speed_kmh = max(0.0, as_float(speed_kmh))
    if speed_kmh <= 0.0:
        return 0.0

    grade = clamp(as_float(grade_percent), -max_grade_percent, max_grade_percent)
    speed_ms = speed_kmh * KMH_TO_MS
    mass = max(0.0, as_float(rider_mass_kg)) + max(0.0, as_float(bike_mass_kg))
    # The exact trigonometry costs nothing and keeps the gravity term honest on
    # steep grades, where sin(atan(g)) differs noticeably from g.
    angle = math.atan(grade / 100.0)

    force_gravity = GRAVITY * math.sin(angle) * mass
    force_rolling = GRAVITY * math.cos(angle) * mass * max(0.0, as_float(crr))
    force_air = 0.5 * max(0.0, as_float(cw)) * AIR_DENSITY * (speed_ms + as_float(wind_mps)) ** 2

    # A steep descent can make the net force negative; the brake cannot push,
    # so the floor is zero load (clamp_power turns that into 25 W).
    return max(0.0, (force_gravity + force_rolling + force_air) * speed_ms / DRIVE_EFFICIENCY)


def clamp_power(watts: float) -> int:
    """Clamp a simulated power to what the Daum brake accepts.

    The cockpit never reports less than 25 W and rejects anything above 800 W,
    so the bridge sends a value inside that window instead of a number the
    firmware would silently ignore.
    """
    return int(round(clamp(as_float(watts), MIN_POWER_WATT, MAX_POWER_WATT)))


def speed_for_gear(rpm: float, gear: int) -> float:
    """Return the speed (km/h) the cockpit reports for ``rpm`` in ``gear``.

    Only used by tests and diagnostics: the cockpit computes this itself and
    sends it in the run data, so the bridge never has to.
    """
    ratios = (
        1.36, 1.48, 1.62, 1.79, 2.00, 2.17, 2.38, 2.63, 2.94, 3.33,
        3.57, 3.85, 4.17, 4.55,
    )
    index = int(clamp(as_int(gear, 1), 1, len(ratios))) - 1
    # ratio * wheel circumference (211.5 cm) * rpm * 0.0006 -> km/h
    return max(0.0, as_float(rpm)) * ratios[index] * 211.5 * 0.0006
