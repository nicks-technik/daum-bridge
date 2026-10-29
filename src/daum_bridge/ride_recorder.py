"""Statistics and trackpoints for the ride currently being recorded.

The Daum cockpit only reports instantaneous values (power, cadence, speed,
heart rate, odometer). "A ride" is therefore something the bridge has to build
itself: accumulate those values while the cockpit is connected, remember one
point per second, and finally assemble the dict that is stored in ``rides/`` and
converted to TCX.

That work used to live inside ``DaumBridge`` together with the serial connection,
the BLE/ANT backends and the gear logic. It now lives here, so ``DaumBridge`` can
stay focused on the connection and this class can be tested without a cockpit.
"""

from __future__ import annotations

import logging
from typing import Optional

from .numbers import as_float

log = logging.getLogger(__name__)


class RideRecorder:
    """Collect the statistics of one ride and turn them into a ride dict.

    Lifecycle::

        recorder.start(now)
        recorder.update(state, now)      # once per poll, while connected
        ride = recorder.build_ride(now)  # None when nothing is being recorded

    ``build_ride`` returns the finished dict and resets the counters. Persisting
    it (JSON/TCX) and uploading it are deliberately *not* done here: those are
    bridge concerns and would drag file system and network code into a class
    whose only job is arithmetic.
    """

    #: Seconds between recorded trackpoints (used for Strava/TCX export).
    SAMPLE_INTERVAL = 1.0
    #: Hard limit for in-memory samples (~27 h at 1 Hz).
    MAX_SAMPLES = 100_000
    #: Number of finished-ride summaries kept in memory for the web UI.
    MAX_HISTORY = 200

    def __init__(self):
        #: Summaries of finished rides, newest last (no samples, for the UI).
        self.history: list[dict] = []
        #: True while a ride was finished manually and must not restart yet.
        self.paused = False
        self.reset()

    def reset(self) -> None:
        """Clear all per-ride counters, keeping ``history`` and ``paused``.

        ``paused`` is intentionally preserved: resetting the counters happens
        *inside* a manual finish, immediately before the ride is marked paused.
        """
        #: Start timestamp of the current ride, or ``None`` when idle.
        self.current_ride: Optional[float] = None
        self.work: float = 0.0
        self.last_power_time: Optional[float] = None
        self.max_power: float = 0.0
        self.avg_power: float = 0.0
        self.power_sum: float = 0.0
        self.power_count: int = 0
        self.samples: list[dict] = []
        self.last_sample_time: float = 0.0
        self.heart_rate_sum: float = 0.0
        self.heart_rate_count: int = 0
        self.max_heart_rate: float = 0.0
        self.cadence_sum: float = 0.0
        self.cadence_count: int = 0
        self.distance: float = 0.0
        self.last_odometer: Optional[float] = None

    # -- lifecycle ---------------------------------------------------------

    def start(self, now: float) -> None:
        """Begin a new ride at ``now``, discarding any previous counters."""
        self.reset()
        self.current_ride = now
        self.last_power_time = now
        log.info("Ride recording started")

    def update(self, state, now: float) -> None:
        """Accumulate one poll of ``state`` into the current ride.

        Power, heart rate and cadence only contribute to their averages while
        they are non-zero: a coasting minute should not drag the average power
        down, and a disconnected heart-rate strap reports ``0`` rather than
        "no data".
        """
        # Elapsed time since the previous poll, used for work and distance.
        dt = (now - self.last_power_time) if self.last_power_time else 0.0

        power = max(0.0, as_float(getattr(state, "power", 0)))
        if power > 0 and 0 < dt < 5:
            # Watts x seconds / 3600 -> watt-hours; the ride dict calls it kJ.
            self.work += power * dt / 3600.0
        self.last_power_time = now
        self.max_power = max(self.max_power, power)
        self.power_sum += power
        self.power_count += 1
        self.avg_power = self.power_sum / self.power_count

        heart_rate = max(0.0, as_float(getattr(state, "heart_rate", 0)))
        if heart_rate > 0:
            self.heart_rate_sum += heart_rate
            self.heart_rate_count += 1
            self.max_heart_rate = max(self.max_heart_rate, heart_rate)

        cadence = max(0.0, as_float(getattr(state, "cadence", 0)))
        if cadence > 0:
            self.cadence_sum += cadence
            self.cadence_count += 1

        self.update_distance(state, dt)
        self.record_sample(state, now, power, cadence, heart_rate)

    def update_distance(self, state, dt: float) -> float:
        """Track distance in km from the cockpit odometer, else from speed.

        The odometer has 0.1 km resolution, so only small forward deltas are
        trusted; a larger jump means the cockpit was reset or a stale frame
        arrived and would otherwise inflate the ride by hundreds of kilometres.
        """
        total = as_float(getattr(state, "total_distance", 0))
        if total > 0:
            if self.last_odometer is None:
                self.last_odometer = total
            else:
                delta = total - self.last_odometer
                if 0 <= delta <= 2.0:
                    self.distance += delta
                self.last_odometer = total
        else:
            speed = as_float(getattr(state, "speed", 0))
            if 0 < speed < 120 and 0 < dt < 60:
                self.distance += speed * dt / 3600.0
        return self.distance

    def record_sample(self, state, now: float, power: float, cadence: float, heart_rate: float) -> None:
        """Append one trackpoint if the sample interval has elapsed."""
        if self.last_sample_time and now - self.last_sample_time < self.SAMPLE_INTERVAL:
            return
        self.last_sample_time = now
        if len(self.samples) >= self.MAX_SAMPLES:
            # Drop the oldest thousand points instead of refusing new ones, so
            # an extremely long ride keeps its recent history.
            del self.samples[:1000]
        self.samples.append({
            "t": round(now - (self.current_ride or now), 3),
            "power": round(power, 1),
            "cadence": round(cadence, 1),
            "speed": round(as_float(getattr(state, "speed", 0)), 1),
            "heart_rate": int(heart_rate),
            "distance": round(self.distance, 3),
        })

    # -- finishing ---------------------------------------------------------

    def build_ride(self, now: float) -> Optional[dict]:
        """Assemble the finished ride dict and reset the counters.

        Returns ``None`` when no ride is in progress, which is what makes
        ``finish_ride()`` safe to call on shutdown or on every disconnect.
        The returned dict still contains its ``samples``; the summary used by
        the web UI is derived from it by :meth:`remember`.
        """
        if self.current_ride is None:
            return None
        start = self.current_ride
        ride = {
            "start": start,
            "end": now,
            "duration": max(0.0, now - start),
            "distance": round(self.distance, 2),
            "work_kj": round(self.work, 2),
            "avg_power": round(self.avg_power, 1),
            "max_power": round(self.max_power, 1),
            "avg_heart_rate": (
                round(self.heart_rate_sum / self.heart_rate_count, 1)
                if self.heart_rate_count
                else 0
            ),
            "max_heart_rate": round(self.max_heart_rate, 1),
            "avg_cadence": (
                round(self.cadence_sum / self.cadence_count, 1)
                if self.cadence_count
                else 0
            ),
            "samples": self.samples,
        }
        self.reset()
        return ride

    def remember(self, summary: dict) -> None:
        """Keep a finished-ride summary for the web UI, newest last."""
        self.history.append(summary)
        if len(self.history) > self.MAX_HISTORY:
            del self.history[:-self.MAX_HISTORY]
