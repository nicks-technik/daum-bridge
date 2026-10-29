"""Physical gear-shift buttons for the Daum bridge.

Two interchangeable backends turn a button press into a gear change:

* ``gpio``  - buttons wired to Raspberry Pi GPIO pins (``gpiozero``).
* ``evdev`` - Bluetooth/USB HID buttons paired with the OS, read through
  ``python-evdev``.

Both are optional dependencies; the bridge keeps running without them and
reports the problem instead of failing to start.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from .base import SHIFT_DOWN, SHIFT_UP, InputUnavailable, ShiftInput

log = logging.getLogger(__name__)

#: Accepted values for ``input.backend``.
BACKENDS = ("none", "gpio", "evdev", "both")

__all__ = [
    "BACKENDS",
    "SHIFT_DOWN",
    "SHIFT_UP",
    "InputUnavailable",
    "ShiftInput",
    "build_inputs",
]


def build_inputs(
    config, on_shift: Callable[[int, str], None]
) -> tuple[list[ShiftInput], list[str]]:
    """Start the shift inputs configured in ``config.input``.

    Returns ``(inputs, problems)``: the inputs that start successfully and one
    human-readable message per backend that could not start. A missing optional
    dependency, an unknown pin or an unpaired button is reported but never
    stops the bridge.
    """
    input_cfg = getattr(config, "input", None)
    if input_cfg is None or not getattr(input_cfg, "enabled", False):
        return [], []

    backend = str(getattr(input_cfg, "backend", "") or "").strip().lower()
    if backend == "none":
        return [], []
    if backend not in BACKENDS:
        return [], [f"unknown input.backend {backend!r} (expected one of {', '.join(BACKENDS)})"]

    common = {
        "repeat_delay": getattr(input_cfg, "repeat_delay", 0.45),
        "repeat_interval": getattr(input_cfg, "repeat_interval", 0.12),
        "min_interval": getattr(input_cfg, "min_interval", 0.10),
    }

    candidates: list[ShiftInput] = []
    if backend in ("gpio", "both"):
        from .gpio_buttons import GpioShiftInput

        gpio_cfg = getattr(input_cfg, "gpio", None)
        candidates.append(
            GpioShiftInput(
                on_shift,
                up_pin=getattr(gpio_cfg, "up_pin", 17),
                down_pin=getattr(gpio_cfg, "down_pin", 27),
                bounce_time=getattr(gpio_cfg, "bounce_time", 0.05),
                active_low=getattr(gpio_cfg, "active_low", True),
                **common,
            )
        )
    if backend in ("evdev", "both"):
        from .evdev_buttons import EvdevShiftInput

        evdev_cfg = getattr(input_cfg, "evdev", None)
        candidates.append(
            EvdevShiftInput(
                on_shift,
                device=getattr(evdev_cfg, "device", ""),
                up_key=getattr(evdev_cfg, "up_key", "KEY_VOLUMEUP"),
                down_key=getattr(evdev_cfg, "down_key", "KEY_VOLUMEDOWN"),
                **common,
            )
        )

    started: list[ShiftInput] = []
    problems: list[str] = []
    for candidate in candidates:
        try:
            candidate.start()
        except InputUnavailable as e:
            problems.append(f"{candidate.name}: {e}")
            log.warning("Shift input unavailable: %s", e)
            continue
        except Exception as e:
            problems.append(f"{candidate.name}: {e}")
            log.warning("Shift input failed to start: %s", e)
            continue
        started.append(candidate)
        log.info("Shift input active: %s", candidate.describe())

    return started, problems
