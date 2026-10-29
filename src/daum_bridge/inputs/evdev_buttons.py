"""Bluetooth (and USB) HID buttons read through Linux evdev.

A BLE button that speaks HID-over-GATT is paired with BlueZ once; the kernel
then exposes it as ``/dev/input/eventN`` and every button press arrives as a
normal key event. Reading that device keeps all Bluetooth work in the OS, so it
does not compete with the FTMS peripheral for the adapter and needs no custom
BLE protocol implementation.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from .base import SHIFT_DOWN, SHIFT_UP, InputUnavailable, ShiftInput

log = logging.getLogger(__name__)


def resolve_key_code(ecodes, name) -> int:
    """Resolve a key name like ``KEY_VOLUMEUP`` to its numeric evdev code."""
    if isinstance(name, int):
        return int(name)
    text = str(name or "").strip()
    if not text:
        raise InputUnavailable("empty key name")
    code = getattr(ecodes, text.upper(), None)
    if code is None:
        raise InputUnavailable(f"unknown evdev key name: {text}")
    return int(code)


def device_key_codes(device, ecodes) -> set:
    """Return the key codes an evdev device can report."""
    try:
        caps = device.capabilities(absinfo=False)
    except Exception:
        return set()
    return {int(code) for code, _info in caps.get(ecodes.EV_KEY, [])}


def find_device(evdev, ecodes, spec: str, up_code: int, down_code: int):
    """Open the input device described by ``spec``.

    ``spec`` may be an ``/dev/input/...`` path, ``name:<substring>``,
    ``path:<path>``, a bare name substring, or empty to auto-detect the first
    device that reports both shift keys.
    """
    text = (spec or "").strip()
    if text.startswith("/dev/"):
        return evdev.InputDevice(text)
    if text.lower().startswith("path:"):
        return evdev.InputDevice(text[5:].strip())

    needle = text[5:].strip() if text.lower().startswith("name:") else text
    needle = needle.lower()
    wrong_keys = []
    for path in sorted(evdev.list_devices()):
        try:
            device = evdev.InputDevice(path)
        except Exception:
            continue
        name = getattr(device, "name", "") or ""
        if needle and needle not in name.lower():
            device.close()
            continue
        codes = device_key_codes(device, ecodes)
        if up_code in codes and down_code in codes:
            return device
        wrong_keys.append(name or path)
        device.close()

    if wrong_keys:
        raise InputUnavailable(
            "device(s) found but none report the configured keys "
            f"({', '.join(sorted(set(wrong_keys)))})"
        )
    if needle:
        raise InputUnavailable(
            f"no input device matching {needle!r}; pair the button and run "
            "'daum-bridge inputs list'"
        )
    raise InputUnavailable(
        "no input device reports the configured keys; pair the button and run "
        "'daum-bridge inputs list'"
    )


class EvdevShiftInput(ShiftInput):
    """Shift buttons exposed as a Linux input device (BLE HID or USB)."""

    name = "evdev"

    def __init__(
        self,
        on_shift: Callable[[int, str], None],
        *,
        device: str = "",
        up_key: str = "KEY_VOLUMEUP",
        down_key: str = "KEY_VOLUMEDOWN",
        **kwargs,
    ):
        super().__init__(on_shift, **kwargs)
        self.device = (device or "").strip()
        self.up_key = up_key or "KEY_VOLUMEUP"
        self.down_key = down_key or "KEY_VOLUMEDOWN"
        self.device_name = ""
        self.device_path = ""
        self._dev = None
        self._thread: threading.Thread | None = None
        self._evdev = None
        self._ecodes = None
        self._up_code = 0
        self._down_code = 0

    def describe(self) -> str:
        if self.device_path:
            return f"evdev {self.device_name or self.device_path}"
        return f"evdev ({self.device or 'auto-detect'})"

    def start(self) -> None:
        try:
            import evdev
            from evdev import ecodes
        except Exception as e:
            raise InputUnavailable(
                f"python-evdev is not installed ({e}); install with 'uv sync --extra input'"
            ) from e

        self._evdev = evdev
        self._ecodes = ecodes
        self._up_code = resolve_key_code(ecodes, self.up_key)
        self._down_code = resolve_key_code(ecodes, self.down_key)
        if self._up_code == self._down_code:
            raise InputUnavailable("evdev: up_key and down_key must be different")

        device = self._open()
        if device is None:
            raise InputUnavailable(self.error or "no matching input device")

        self._begin()
        self._thread = threading.Thread(
            target=self._run,
            args=(device,),
            name="evdev-buttons",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._end()
        device = self._dev
        if device is not None:
            try:
                device.close()
            except Exception:
                pass
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    # -- internals -----------------------------------------------------
    def _open(self):
        try:
            return find_device(
                self._evdev, self._ecodes, self.device, self._up_code, self._down_code
            )
        except PermissionError as e:
            self.error = (
                f"cannot read input device ({e}); add the service user to the "
                "'input' group"
            )
            return None
        except InputUnavailable as e:
            self.error = str(e)
            return None
        except Exception as e:
            self.error = str(e)
            return None

    def _run(self, device) -> None:
        while self._running and device is not None:
            self.device_path = getattr(device, "path", "") or ""
            self.device_name = getattr(device, "name", "") or ""
            self._dev = device
            self.error = None
            try:
                for event in device.read_loop():
                    if not self._running:
                        break
                    if event.type != self._ecodes.EV_KEY or event.value == 2:
                        # 2 is the kernel's own autorepeat; hold-to-repeat is
                        # handled in ShiftInput so all backends behave alike.
                        continue
                    if event.code == self._up_code:
                        if event.value:
                            self.press(SHIFT_UP)
                        else:
                            self.release(SHIFT_UP)
                    elif event.code == self._down_code:
                        if event.value:
                            self.press(SHIFT_DOWN)
                        else:
                            self.release(SHIFT_DOWN)
            except OSError as e:
                if self._running:
                    self.error = f"device disconnected: {e}"
                    log.info(
                        "evdev: %s disconnected (%s)", self.device_name or self.device_path, e
                    )
            except Exception as e:
                self.error = str(e)
                log.debug("evdev read loop stopped: %s", e)
            finally:
                try:
                    device.close()
                except Exception:
                    pass
                self._dev = None
                self.device_path = ""

            if not self._running:
                break
            # BLE buttons drop the link when idle; wait for them to come back.
            time.sleep(1.0)
            device = self._open()
