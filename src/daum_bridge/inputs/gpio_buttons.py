"""Wired shift buttons on Raspberry Pi GPIO pins (``gpiozero``)."""

from __future__ import annotations

import logging
from collections.abc import Callable

from .base import SHIFT_DOWN, SHIFT_UP, InputUnavailable, ShiftInput

log = logging.getLogger(__name__)


class GpioShiftInput(ShiftInput):
    """Two momentary buttons wired to GND on the Pi's 3.3 V GPIO header.

    With ``active_low`` (the default) the internal pull-up keeps the pin high
    and pressing the button pulls it to ground, which is the safest wiring:
    a broken wire reads as "not pressed" instead of "held down".
    """

    name = "gpio"

    def __init__(
        self,
        on_shift: Callable[[int, str], None],
        *,
        up_pin: int = 17,
        down_pin: int = 27,
        bounce_time: float = 0.05,
        active_low: bool = True,
        **kwargs,
    ):
        super().__init__(on_shift, **kwargs)
        self.up_pin = int(up_pin)
        self.down_pin = int(down_pin)
        self.bounce_time = max(0.0, float(bounce_time))
        self.active_low = bool(active_low)
        self._up = None
        self._down = None

    def describe(self) -> str:
        return f"gpio (BCM{self.up_pin}/BCM{self.down_pin}, active_low={self.active_low})"

    def start(self) -> None:
        try:
            from gpiozero import Button
        except Exception as e:  # ImportError, or no pin factory on non-Pi hosts
            raise InputUnavailable(
                f"gpiozero is not usable on this host ({e}); "
                "install with 'uv sync --extra gpio'"
            ) from e

        if self.up_pin == self.down_pin:
            raise InputUnavailable("gpio: up_pin and down_pin must be different")

        bounce = self.bounce_time or None
        try:
            self._up = Button(self.up_pin, pull_up=self.active_low, bounce_time=bounce)
            self._down = Button(self.down_pin, pull_up=self.active_low, bounce_time=bounce)
        except Exception as e:
            self._close_buttons()
            raise InputUnavailable(f"gpio: could not open BCM{self.up_pin}/BCM{self.down_pin}: {e}") from e

        self._up.when_pressed = lambda: self.press(SHIFT_UP)
        self._up.when_released = lambda: self.release(SHIFT_UP)
        self._down.when_pressed = lambda: self.press(SHIFT_DOWN)
        self._down.when_released = lambda: self.release(SHIFT_DOWN)
        self._begin()

    def stop(self) -> None:
        self._end()
        self._close_buttons()

    def _close_buttons(self) -> None:
        for button in (self._up, self._down):
            try:
                if button is not None:
                    button.close()
            except Exception:
                pass
        self._up: object | None = None
        self._down: object | None = None
