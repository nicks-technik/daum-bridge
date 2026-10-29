# Handlebar shift buttons

Shift gears with physical buttons on the bike instead of the web UI or
MyWhoosh. Two interchangeable backends are supported and can run at the same
time:

| Backend | How the button reaches the bridge | Needs |
| --- | --- | --- |
| `gpio` | Two momentary buttons wired to Raspberry Pi GPIO pins | bridge running **on** the Pi, `uv sync --extra gpio` |
| `evdev` | Bluetooth or USB HID button paired with the OS, read as an input device | `uv sync --extra input`, BlueZ |

Both feed the same `DaumBridge.shift()` call as the web UI, so a button press and
a click on the website do exactly the same thing.

## Quick start

```bash
# Bridge host (Linux)
uv sync --extra gpio --extra input

cp config.example.yaml config.yaml
```

```yaml
input:
  enabled: true
  backend: both          # none | gpio | evdev | both
  shift_clears_erg: true
```

```bash
uv run daum-bridge inputs status   # what is configured, which drivers load
uv run daum-bridge inputs test     # press the buttons, see the shifts
uv run daum-bridge run
```

`inputs test` is the fastest way to prove the hardware works: it exercises the
real backends without touching the bike.

## Wired buttons (GPIO)

### Parts

- 2 × IP67 momentary push button (12 mm stainless or 16 mm plastic, normally
  open), mounted under the hoods or on the stem.
- 3-core silicone cable (shift up, shift down, common ground), routed under the
  bar tape.
- Optional per input: 1 kΩ series resistor + 100 nF capacitor to GND. The RC
  filter suppresses trainer EMI and contact bounce on long cable runs.

### Wiring

| Signal | BCM pin | Physical pin |
| --- | --- | --- |
| Shift up | BCM17 | 11 |
| Shift down | BCM27 | 13 |
| Common ground | GND | 9 (or 14) |

Each button connects its signal pin to GND. The Pi's internal pull-up (enabled
by `active_low: true`) keeps the pin high while the button is open, so a broken
wire reads as "not pressed" rather than "held down".

Rules:

- **3.3 V only** — never switch 5 V into a GPIO pin.
- Avoid BCM0–8 (I²C, SPI, UART and boot-mode pins). BCM17/27/22/23/24/25 are safe.
- With the internal pull-up no external resistor is required; the 1 kΩ series
  resistor is protection, not a pull-up.

```yaml
input:
  enabled: true
  backend: gpio
  gpio:
    up_pin: 17
    down_pin: 27
    bounce_time: 0.05
    active_low: true
```

On a Pi 5 the pin factory needs `lgpio`:

```bash
sudo apt install python3-lgpio
```

## Bluetooth buttons (evdev)

A BLE button that speaks HID-over-GATT is paired with BlueZ once. The kernel
then exposes it as `/dev/input/eventN` and every press arrives as a normal key
event, so the bridge needs **no BLE code** and does not compete with the FTMS
peripheral for the adapter.

### Pairing

```bash
bluetoothctl
power on
agent on
default-agent
scan on
# put the button into pairing mode (usually hold it for a few seconds)
pair AA:BB:CC:DD:EE:FF
trust AA:BB:CC:DD:EE:FF      # reconnects automatically after sleep
connect AA:BB:CC:DD:EE:FF
quit
```

Then find the device and the keys it sends:

```bash
uv run daum-bridge inputs list
# /dev/input/by-id/usb-...-event-kbd   AB Shutter 3   KEY_VOLUMEUP, KEY_VOLUMEDOWN
```

```yaml
input:
  enabled: true
  backend: evdev
  evdev:
    device: "name:shutter"        # or /dev/input/by-id/..., empty = auto-detect
    up_key: KEY_VOLUMEUP
    down_key: KEY_VOLUMEDOWN
```

`device` accepts:

| Value | Meaning |
| --- | --- |
| `/dev/input/event3` | exact device node |
| `/dev/input/by-id/usb-...-event-kbd` | stable symlink (preferred) |
| `name:shutter` | first device whose name contains `shutter` |
| empty | first device that reports both configured keys |

Key names are standard evdev names (`KEY_VOLUMEUP`, `KEY_PAGEDOWN`,
`KEY_ENTER`, …). Use `daum-bridge inputs test --up-key ...` to try one before
writing it into the config.

### Permissions

Reading `/dev/input` needs the `input` group. For a systemd service:

```ini
[Service]
SupplementaryGroups=input
```

or add the user directly:

```bash
sudo usermod -aG input "$USER"
# log out and back in
```

### Reconnects

BLE buttons drop the link when idle. The backend reopens the device in the
background (retrying every second) and keeps the bridge running; `input_status`
in `/api/state` shows the error while it is disconnected.

## Hardware suggestions

| Option | Price | Buttons | Notes |
| --- | --- | --- | --- |
| Generic BLE shutter remote (AB Shutter 3 and clones) | €5–10 | 2 | Pairs as a keyboard and sends `KEY_VOLUMEUP`/`KEY_VOLUMEDOWN` — a ready-made two-button shifter. CR2032, plastic, not weatherproof. Best for a first test. |
| 8Bitdo Micro | ~€25 | 16, mappable | Keyboard or gamepad mode, keys mapped from a phone app, rechargeable, solid build. Best "buy once" choice. |
| Zwift Click v2 | ~€45 | 2, bar-mounted | Purpose-built ergonomics, but proprietary **encrypted** BLE. It is *not* a HID device, so `evdev` cannot read it; it needs a separate `bleak`-based client implementing the RideOn/SyncRX handshake. Out of scope for this backend. |
| Two IP67 buttons + cable | €10–20 | 2 | Most reliable, no battery, no radio, instant reaction. Needs the bridge on the Pi. |
| DIY ESP32-C3 / nRF52840 | €10 + time | any | Full control (custom GATT, waterproof enclosure, LiPo). Most work. |

Avoid Zwift Play for the same reason as the Click: encrypted, not HID.

## Configuration reference

| Key | Default | Meaning |
| --- | --- | --- |
| `input.enabled` | `false` | Master switch |
| `input.backend` | `both` | `none`, `gpio`, `evdev` or `both` |
| `input.shift_clears_erg` | `true` | Leave ERG when a button shifts (see below) |
| `input.repeat_delay` | `0.45` | Hold time before the first repeat, seconds |
| `input.repeat_interval` | `0.12` | Interval between repeats, seconds (`0` disables) |
| `input.min_interval` | `0.10` | Minimum time between two shifts |
| `input.gpio.up_pin` | `17` | BCM pin, shift up |
| `input.gpio.down_pin` | `27` | BCM pin, shift down |
| `input.gpio.bounce_time` | `0.05` | Software debounce, seconds |
| `input.gpio.active_low` | `true` | Button to GND with internal pull-up |
| `input.evdev.device` | `""` | Path, `name:<substring>`, or empty to auto-detect |
| `input.evdev.up_key` | `KEY_VOLUMEUP` | Key that shifts up |
| `input.evdev.down_key` | `KEY_VOLUMEDOWN` | Key that shifts down |

Environment overrides: `DAUM_INPUT_ENABLED`, `DAUM_INPUT_BACKEND`,
`DAUM_GPIO_UP_PIN`, `DAUM_GPIO_DOWN_PIN`, `DAUM_INPUT_DEVICE`,
`DAUM_INPUT_UP_KEY`, `DAUM_INPUT_DOWN_KEY`.

## Commands and UI

```bash
uv run daum-bridge inputs status          # config + driver availability
uv run daum-bridge inputs list            # input devices and their useful keys
uv run daum-bridge inputs test            # live button monitor
uv run daum-bridge inputs test --backend gpio --up-pin 17 --down-pin 27
uv run daum-bridge inputs test --up-key KEY_PAGEUP --down-key KEY_PAGEDOWN
```

The web config page has a **Handlebar shift buttons** section, and
`/api/state` reports the last shift source (`gpio`, `evdev`, `api`) plus any
backend problems.

## Why `shift_clears_erg` matters

The Daum cockpit holds the last target power in ERG mode. A gear change while
ERG is active therefore has **no effect** on the load until ERG is released.
With `shift_clears_erg: true` (default) a button press drops the target power
first, exactly like moving the resistance slider in the web UI. Set it to
`false` if you want buttons ignored during ERG intervals.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `inputs status` shows `evdev: not available` | `uv sync --extra input` |
| `inputs status` shows `gpiozero: not available` | `uv sync --extra gpio`; on Pi 5 also `sudo apt install python3-lgpio` |
| `PermissionError` / device not readable | add the service user to the `input` group |
| Device listed but no shifts | run `inputs test`, check the key names; some remotes send `KEY_ENTER` instead of volume keys |
| Shift only once, then nothing | hold-to-repeat is working; `min_interval` or `repeat_interval` too long for your taste |
| Double shifts per press | lower `bounce_time` (e.g. `0.02`) or add the RC filter on long cables |
| Buttons do nothing while riding | ERG mode holds the watts — keep `shift_clears_erg: true` |
| Buttons shift the wrong way | swap `up_pin`/`down_pin` or `up_key`/`down_key` |
| Reconnect loop after the button sleeps | normal for BLE; `trust` the device in `bluetoothctl` |

## How it works

```
inputs/base.py          ShiftInput: rate limit, debounce, hold-to-repeat
inputs/gpio_buttons.py  gpiozero Button -> press()/release()
inputs/evdev_buttons.py /dev/input read_loop -> press()/release(), auto-reconnect
inputs/__init__.py      build_inputs(): start configured backends, report problems
bridge.py               shift(delta, source) -> release ERG (optional) -> set_gear()
```

A missing driver, an unknown pin or an unpaired button is reported at startup
and in `/api/state`; it never prevents the bridge from starting, so BLE FTMS
keeps working even if the buttons are not ready yet.
