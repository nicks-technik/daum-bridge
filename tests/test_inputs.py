import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from daum_bridge.bridge import DaumBridge
from daum_bridge.config import (
    Config,
    get_env_overrides,
)
from daum_bridge.inputs import SHIFT_DOWN, SHIFT_UP, build_inputs
from daum_bridge.inputs.base import InputUnavailable, ShiftInput
from daum_bridge.inputs.evdev_buttons import find_device, resolve_key_code
from daum_bridge.inputs.gpio_buttons import GpioShiftInput


class RecordingInput(ShiftInput):
    """ShiftInput with no hardware, exposing press/release for tests."""

    name = "recording"

    def __init__(self, on_shift, **kwargs):
        super().__init__(on_shift, **kwargs)
        self.started = False

    def start(self):
        self.started = True
        self._begin()

    def stop(self):
        self._end()
        self.started = False


def make_input(**kwargs):
    calls = []
    item = RecordingInput(lambda delta, source: calls.append((delta, source)), **kwargs)
    item.start()
    return item, calls


# -- base ShiftInput -------------------------------------------------------


def test_press_emits_shift_and_release_is_silent():
    item, calls = make_input()
    item.press(SHIFT_UP)
    item.release(SHIFT_UP)
    item.stop()

    assert calls == [(SHIFT_UP, "recording")]


def test_min_interval_suppresses_rapid_double_press():
    item, calls = make_input(min_interval=0.5, repeat_delay=0, repeat_interval=0)
    item.press(SHIFT_UP)
    item.press(SHIFT_DOWN)  # ignored: too soon after the first shift
    item.stop()

    assert calls == [(SHIFT_UP, "recording")]


def test_hold_repeats_while_pressed():
    item, calls = make_input(repeat_delay=0.02, repeat_interval=0.02, min_interval=0)
    item.press(SHIFT_DOWN)
    time.sleep(0.12)
    item.release(SHIFT_DOWN)
    time.sleep(0.06)

    assert len(calls) >= 2
    assert {delta for delta, _ in calls} == {SHIFT_DOWN}


def test_release_stops_repeating():
    item, calls = make_input(repeat_delay=0.02, repeat_interval=0.02, min_interval=0)
    item.press(SHIFT_UP)
    time.sleep(0.10)
    item.release(SHIFT_UP)
    time.sleep(0.05)
    count = len(calls)
    time.sleep(0.10)

    assert len(calls) == count
    item.stop()


def test_callback_errors_do_not_break_the_input():
    def explode(delta, source):
        raise RuntimeError("boom")

    item = RecordingInput(explode, repeat_delay=0, repeat_interval=0)
    item.start()
    item.press(SHIFT_UP)  # must not raise
    item.stop()

    assert item.last_delta == SHIFT_UP


def test_status_snapshot():
    item, _calls = make_input()
    item.press(SHIFT_UP)

    status = item.status()

    assert status["backend"] == "recording"
    assert status["running"] is True
    assert status["last_delta"] == SHIFT_UP
    assert status["last_shift_at"] is not None
    assert status["error"] is None
    item.stop()
    assert item.status()["running"] is False


# -- config ----------------------------------------------------------------


def test_input_config_defaults():
    cfg = Config()
    assert cfg.input.enabled is False
    assert cfg.input.backend == "both"
    assert cfg.input.shift_clears_erg is True
    assert cfg.input.gpio.up_pin == 17
    assert cfg.input.gpio.down_pin == 27
    assert cfg.input.evdev.up_key == "KEY_VOLUMEUP"


def test_input_config_parses_section():
    cfg = Config.from_dict({
        "input": {
            "enabled": True,
            "backend": "gpio",
            "shift_clears_erg": False,
            "repeat_delay": 0.3,
            "repeat_interval": 0.1,
            "gpio": {"up_pin": 5, "down_pin": 6, "bounce_time": 0.03, "active_low": False},
            "evdev": {
                "device": "name:shutter",
                "up_key": "KEY_PAGEUP",
                "down_key": "KEY_PAGEDOWN",
            },
        }
    })

    assert cfg.input.enabled is True
    assert cfg.input.backend == "gpio"
    assert cfg.input.shift_clears_erg is False
    assert cfg.input.repeat_delay == 0.3
    assert cfg.input.gpio.up_pin == 5
    assert cfg.input.gpio.down_pin == 6
    assert cfg.input.gpio.active_low is False
    assert cfg.input.evdev.device == "name:shutter"
    assert cfg.input.evdev.up_key == "KEY_PAGEUP"
    assert cfg.input.evdev.down_key == "KEY_PAGEDOWN"


def test_input_config_survives_bad_values():
    cfg = Config.from_dict({"input": {"repeat_delay": "nope", "gpio": {"up_pin": None}}})

    assert cfg.input.repeat_delay == 0.45
    assert cfg.input.gpio.up_pin == 17
    # A broken input section must not reset unrelated settings.
    assert cfg.bridge.max_gear == 20


def test_input_env_overrides(monkeypatch):
    monkeypatch.setenv("DAUM_INPUT_ENABLED", "true")
    monkeypatch.setenv("DAUM_INPUT_BACKEND", "GPIO")
    monkeypatch.setenv("DAUM_GPIO_UP_PIN", "23")
    monkeypatch.setenv("DAUM_GPIO_DOWN_PIN", "24")
    monkeypatch.setenv("DAUM_INPUT_DEVICE", "name:click")
    monkeypatch.setenv("DAUM_INPUT_UP_KEY", "KEY_PAGEUP")
    monkeypatch.setenv("DAUM_INPUT_DOWN_KEY", "KEY_PAGEDOWN")

    cfg = get_env_overrides(Config())

    assert cfg.input.enabled is True
    assert cfg.input.backend == "gpio"
    assert cfg.input.gpio.up_pin == 23
    assert cfg.input.gpio.down_pin == 24
    assert cfg.input.evdev.device == "name:click"
    assert cfg.input.evdev.up_key == "KEY_PAGEUP"
    assert cfg.input.evdev.down_key == "KEY_PAGEDOWN"


def test_input_validation_reports_problems():
    cfg = Config()
    cfg.input.enabled = True
    cfg.input.backend = "serial"
    cfg.input.gpio.down_pin = cfg.input.gpio.up_pin
    cfg.input.repeat_interval = 0.005
    cfg.input.min_interval = -1

    errors = "\n".join(cfg.validate())

    assert "input.backend must be one of" in errors
    assert "up_pin and input.gpio.down_pin must differ" in errors
    assert "repeat_interval" in errors
    assert "min_interval" in errors


def test_input_validation_accepts_disabled_defaults():
    assert [e for e in Config().validate() if e.startswith("input.")] == []


# -- factory ---------------------------------------------------------------


def test_build_inputs_disabled_returns_nothing():
    started, problems = build_inputs(Config(), lambda delta, source: None)

    assert started == []
    assert problems == []


def test_build_inputs_backend_none_returns_nothing():
    cfg = Config()
    cfg.input.enabled = True
    cfg.input.backend = "none"

    started, problems = build_inputs(cfg, lambda delta, source: None)

    assert started == []
    assert problems == []


def test_build_inputs_unknown_backend_is_reported_not_raised():
    cfg = Config()
    cfg.input.enabled = True
    cfg.input.backend = "carrier-pigeon"

    started, problems = build_inputs(cfg, lambda delta, source: None)

    assert started == []
    assert problems and "carrier-pigeon" in problems[0]


def test_build_inputs_both_reports_every_backend():
    cfg = Config()
    cfg.input.enabled = True
    cfg.input.backend = "both"

    started, problems = build_inputs(cfg, lambda delta, source: None)

    # On a machine without gpiozero/evdev both fail softly; when the drivers are
    # available they start instead. Either way nothing may raise.
    assert len(started) + len(problems) == 2
    for item in started:
        item.stop()


# -- gpio backend ----------------------------------------------------------


def test_gpio_backend_wires_button_callbacks(monkeypatch):
    buttons = []

    class FakeButton:
        def __init__(self, pin, pull_up=True, bounce_time=None):
            self.pin = pin
            self.pull_up = pull_up
            self.bounce_time = bounce_time
            self.when_pressed = None
            self.when_released = None
            self.closed = False
            buttons.append(self)

        def close(self):
            self.closed = True

    monkeypatch.setitem(sys.modules, "gpiozero", SimpleNamespace(Button=FakeButton))
    calls = []
    item = GpioShiftInput(
        lambda delta, source: calls.append((delta, source)),
        up_pin=17,
        down_pin=27,
        min_interval=0,  # two presses inside one test are not rate limited
    )

    item.start()
    assert [b.pin for b in buttons] == [17, 27]
    assert all(b.pull_up is True for b in buttons)

    buttons[0].when_pressed()
    buttons[1].when_pressed()
    buttons[0].when_released()
    item.stop()

    assert calls == [(SHIFT_UP, "gpio"), (SHIFT_DOWN, "gpio")]
    assert all(b.closed for b in buttons)


def test_gpio_backend_rejects_identical_pins(monkeypatch):
    monkeypatch.setitem(sys.modules, "gpiozero", SimpleNamespace(Button=object))
    item = GpioShiftInput(lambda delta, source: None, up_pin=17, down_pin=17)

    with pytest.raises(InputUnavailable):
        item.start()


def test_gpio_backend_reports_missing_driver(monkeypatch):
    monkeypatch.setitem(sys.modules, "gpiozero", None)
    item = GpioShiftInput(lambda delta, source: None)

    with pytest.raises(InputUnavailable):
        item.start()


# -- evdev helpers ---------------------------------------------------------


class FakeEcodes:
    EV_KEY = 1
    KEY_VOLUMEUP = 115
    KEY_VOLUMEDOWN = 114
    KEY_PAGEUP = 104
    KEY_PAGEDOWN = 109


class FakeDevice:
    def __init__(self, path, name, keys):
        self.path = path
        self.name = name
        self._keys = keys
        self.closed = False

    def capabilities(self, absinfo=False):
        return {FakeEcodes.EV_KEY: [(key, ()) for key in self._keys]}

    def close(self):
        self.closed = True


class FakeEvdev:
    def __init__(self, devices):
        self._devices = devices

    def list_devices(self):
        return [device.path for device in self._devices]

    def InputDevice(self, path):
        for device in self._devices:
            if device.path == path:
                return device
        raise OSError(path)


def test_resolve_key_code_accepts_names_and_numbers():
    assert resolve_key_code(FakeEcodes, "KEY_VOLUMEUP") == 115
    assert resolve_key_code(FakeEcodes, "key_volumedown") == 114
    assert resolve_key_code(FakeEcodes, 42) == 42

    with pytest.raises(InputUnavailable):
        resolve_key_code(FakeEcodes, "KEY_NOPE")


def test_find_device_auto_detects_shift_keys():
    keyboard = FakeDevice("/dev/input/event0", "AT Keyboard", [1, 2, 115])
    shutter = FakeDevice("/dev/input/event3", "AB Shutter 3", [115, 114])

    found = find_device(FakeEvdev([keyboard, shutter]), FakeEcodes, "", 115, 114)

    assert found is shutter
    assert keyboard.closed is True


def test_find_device_by_name_and_path():
    shutter = FakeDevice("/dev/input/event3", "AB Shutter 3", [115, 114])
    other = FakeDevice("/dev/input/event4", "Mouse", [272])
    evdev = FakeEvdev([shutter, other])

    assert find_device(evdev, FakeEcodes, "name:shutter", 115, 114) is shutter

    by_path = FakeEvdev([FakeDevice("/dev/input/event9", "Click", [115, 114])])
    assert find_device(by_path, FakeEcodes, "/dev/input/event9", 115, 114).name == "Click"


def test_find_device_explains_missing_device():
    keyboard = FakeDevice("/dev/input/event0", "AT Keyboard", [1, 2])

    with pytest.raises(InputUnavailable) as exc:
        find_device(FakeEvdev([keyboard]), FakeEcodes, "name:shutter", 115, 114)

    assert "no input device matching" in str(exc.value)

    with pytest.raises(InputUnavailable) as exc:
        find_device(FakeEvdev([keyboard]), FakeEcodes, "", 115, 114)

    assert "none report the configured keys" in str(exc.value)


# -- bridge integration ----------------------------------------------------


def test_bridge_shift_updates_gear_and_source():
    bridge = DaumBridge(Config())
    bridge.protocol = Mock()
    bridge.protocol._address_found = True

    bridge.shift(SHIFT_UP, "gpio")
    bridge.shift(SHIFT_DOWN, "evdev")

    assert bridge._target_gear == 1  # clamped at the lowest gear
    status = bridge.input_status()
    assert status["last_source"] == "evdev"
    assert status["last_shift_at"] is not None


def test_bridge_shift_clears_erg_by_default():
    bridge = DaumBridge(Config())
    bridge.protocol = Mock()
    bridge.protocol._address_found = True
    bridge._target_watt = 200
    bridge._erg_control_granted = True

    bridge.shift(SHIFT_UP, "gpio")

    assert bridge._target_watt == 0
    assert bridge._erg_control_granted is False
    bridge.protocol.set_watt.assert_called_with(0)


def test_bridge_shift_can_keep_erg():
    cfg = Config()
    cfg.input.shift_clears_erg = False
    bridge = DaumBridge(cfg)
    bridge.protocol = Mock()
    bridge.protocol._address_found = True
    bridge._target_watt = 200
    bridge._erg_control_granted = True

    bridge.shift(SHIFT_UP, "gpio")

    assert bridge._target_watt == 200
    assert bridge._erg_control_granted is True


def test_bridge_shift_ignores_zero_and_garbage():
    bridge = DaumBridge(Config())
    bridge._target_gear = 5

    bridge.shift(0)
    bridge.shift("nope")

    assert bridge._target_gear == 5
    assert bridge._last_shift_source is None


def test_bridge_input_status_reports_config():
    cfg = Config()
    cfg.input.enabled = True
    cfg.input.backend = "evdev"
    bridge = DaumBridge(cfg)

    status = bridge.input_status()

    assert status["enabled"] is True
    assert status["backend"] == "evdev"
    assert status["active"] == []
    assert status["problems"] == []


def test_bridge_starts_and_stops_inputs(monkeypatch):
    import daum_bridge.inputs as inputs_module

    stopped = []

    class DummyInput:
        def start(self):
            pass

        def stop(self):
            stopped.append(True)

        def status(self):
            return {"backend": "dummy", "running": True}

    dummy = DummyInput()
    monkeypatch.setattr(
        inputs_module, "build_inputs", lambda cfg, callback: ([dummy], ["evdev: nope"])
    )

    bridge = DaumBridge(Config())
    bridge._start_inputs()

    assert bridge._inputs == [dummy]
    assert bridge.input_status()["problems"] == ["evdev: nope"]
    assert bridge.input_status()["active"] == [{"backend": "dummy", "running": True}]

    bridge._stop_inputs()
    assert stopped == [True]
    assert bridge._inputs == []
