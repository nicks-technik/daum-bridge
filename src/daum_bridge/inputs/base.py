"""Shared plumbing for physical gear-shift buttons.

A shift input turns a button press into ``bridge.shift(+1)`` / ``bridge.shift(-1)``.
Backends (GPIO, Bluetooth HID over evdev) only report button transitions; the
debouncing, hold-to-repeat and rate limiting live here so that every backend
behaves the same way and the Daum serial link is never flooded.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

log = logging.getLogger(__name__)

#: Shift direction: one gear harder / easier.
SHIFT_UP = 1
SHIFT_DOWN = -1


class InputUnavailable(RuntimeError):
    """Raised when a backend's dependency, permission or hardware is missing."""


class ShiftInput:
    """Base class for a shift-button backend.

    Subclasses implement :meth:`start` and :meth:`stop`, then call
    :meth:`_begin` / :meth:`_end` around their event source and
    :meth:`press` / :meth:`release` when a button changes state.
    """

    name = "input"

    def __init__(
        self,
        on_shift: Callable[[int, str], None],
        *,
        repeat_delay: float = 0.45,
        repeat_interval: float = 0.12,
        min_interval: float = 0.10,
    ):
        self._on_shift = on_shift
        self.repeat_delay = max(0.0, float(repeat_delay))
        self.repeat_interval = max(0.02, float(repeat_interval))
        self.min_interval = max(0.0, float(min_interval))
        self._lock = threading.Lock()
        self._running = False
        self._held: int | None = None
        self._next_repeat = 0.0
        self._last_emit = 0.0
        self._repeat_thread: threading.Thread | None = None
        self.last_shift_at: float = 0.0
        self.last_delta: int = 0
        self.error: str | None = None

    # -- lifecycle -----------------------------------------------------
    def start(self) -> None:
        """Open the hardware and begin delivering shifts."""
        raise NotImplementedError

    def stop(self) -> None:
        """Release the hardware and stop the repeat worker."""
        raise NotImplementedError

    def describe(self) -> str:
        """Short human-readable description for logs and the CLI."""
        return self.name

    # -- helpers for subclasses ---------------------------------------
    def _begin(self) -> None:
        """Mark the input as running and start the hold-to-repeat worker."""
        self._running = True
        if self.repeat_delay > 0 and self.repeat_interval > 0:
            self._repeat_thread = threading.Thread(
                target=self._repeat_loop,
                name=f"{self.name}-repeat",
                daemon=True,
            )
            self._repeat_thread.start()

    def _end(self) -> None:
        """Stop the repeat worker (safe to call twice)."""
        self._running = False
        with self._lock:
            self._held = None
        thread = self._repeat_thread
        self._repeat_thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    # -- event plumbing -------------------------------------------------
    def press(self, delta: int) -> None:
        """Handle a button-down event for ``delta`` (+1 up, -1 down)."""
        now = time.time()
        with self._lock:
            self._held = int(delta)
            self._next_repeat = now + self.repeat_delay
            if now - self._last_emit < self.min_interval:
                # Too soon after the last shift: keep the hold state so
                # hold-to-repeat still works, but do not emit a second shift.
                return
            self._last_emit = now
        self._emit(delta)

    def release(self, delta: int) -> None:
        """Handle a button-up event, cancelling hold-to-repeat."""
        with self._lock:
            if self._held == int(delta):
                self._held = None

    def _emit(self, delta: int) -> None:
        self.last_shift_at = time.time()
        self.last_delta = int(delta)
        try:
            self._on_shift(int(delta), self.name)
        except Exception as e:  # never let a callback kill the input thread
            log.warning("%s: shift callback failed: %s", self.name, e)

    def _repeat_loop(self) -> None:
        while self._running:
            time.sleep(0.02)
            now = time.time()
            with self._lock:
                if self._held is None or now < self._next_repeat:
                    continue
                delta = self._held
                self._next_repeat = now + self.repeat_interval
                self._last_emit = now
            self._emit(delta)

    # -- status ----------------------------------------------------------
    def status(self) -> dict:
        """Snapshot for the web UI and ``daum-bridge inputs status``."""
        return {
            "backend": self.name,
            "description": self.describe(),
            "running": self._running,
            "error": self.error,
            "last_shift_at": self.last_shift_at or None,
            "last_delta": self.last_delta,
        }
