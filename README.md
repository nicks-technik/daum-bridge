# daum-bridge

Bridge for **Daum 8008 TRS** ergo bike (RS232 via original Daum cable + RS232→USB adapter) to **MyWhoosh** via **BLE FTMS**. Designed to run on **Linux** (separate PC/RPi) while MyWhoosh runs on Windows. Includes a simple web UI for gear shifting and status.

> Based on protocol insights from [weinzmi/daumUSB2BLE](https://github.com/weinzmi/daumUSB2BLE) / ergoFACE.

## Features
- RS232 protocol to Daum 8008 TRS (address discovery, `run_Data` polling, `set_Watt`, `set_Gear`, `set_Prog`)
- BLE FTMS peripheral (Linux/BlueZ) exposing Indoor Bike Data + Fitness Machine Control Point
- Optional ANT+ FE-C trainer broadcast (pages 16/17/25/54, control pages 48/49/50/51)
- Bidirectional control: receive target power/ERG, resistance and grade commands from MyWhoosh (or an ANT+ head unit) and forward them to the bike
- Gear shifting via web UI (and CLI)
- Ride recording with power/cadence/heart rate and distance
- Ride history with TCX export, optional Strava upload (API upload requires a Strava subscription since June 2026) and optional email delivery of TCX files
- Auto-detect serial port with config override
- Simple web UI for status and shifting
- Runs on Linux; Windows support kept in mind where feasible

## Hardware
- Daum 8008 TRS cockpit with RS232 port
- Original Daum RS232 cable
- RS232→USB adapter (you have one)
- Linux machine (separate from Windows running MyWhoosh) with Bluetooth/BlueZ
- Network connectivity between machines (or same LAN)

## Setup (Linux / Raspberry Pi)
Quick automated setup:
```bash
chmod +x scripts/setup-linux.sh
./scripts/setup-linux.sh
# Log out and back in for group changes
./scripts/check-setup.sh
uv run daum-bridge scan
cp config.example.yaml config.yaml  # edit if needed
uv run daum-bridge run
```

Manual setup:
```bash
# Install deps with uv
uv sync

# Copy example config
cp config.example.yaml config.yaml

# Edit config.yaml (serial port, BT adapter, web UI)
# Run
uv run daum-bridge run --config config.yaml
```

See [scripts/README.md](scripts/README.md), [docs/overview.md](docs/overview.md), [docs/protocol.md](docs/protocol.md), [docs/strava.md](docs/strava.md), [docs/email.md](docs/email.md), [docs/installation.md](docs/installation.md) for details.

## Strava (optional)
Rides are recorded automatically and can be uploaded to Strava from the
history page, the CLI (`uv run daum-bridge strava-upload`) or
automatically after each ride.

Strava requires a paid subscription for API access since June 2026. Without
one, use the free manual route: download the ride as TCX from `/downloads`
(or `/history`, or `uv run daum-bridge export-tcx`) and upload it at
<https://www.strava.com/upload/select>.

One-time API setup (subscription required):

```bash
uv run daum-bridge strava-auth --client-id <ID> --client-secret <SECRET> --write-config
```

See [docs/strava.md](docs/strava.md) for creating the Strava API app,
available environment variables and troubleshooting.

## Email (optional)
Finished rides can also be emailed as TCX attachments (no Strava account or
subscription needed). Configure SMTP in the `email:` section of `config.yaml`
or with `DAUM_EMAIL_*` environment variables, then:

- enable `email.auto_send: true` to mail every ride automatically,
- press **Email** on `/downloads` (or **Email latest TCX** on `/history`),
- or run `uv run daum-bridge email-ride` (add `--ride <file>` / `--to <addr>`).

See [docs/email.md](docs/email.md) for Gmail app passwords, provider settings
and troubleshooting.

## ANT+ FE-C (optional)
The bridge can additionally act as an ANT+ FE-C trainer (device type 17) for
head units/apps that use ANT+ instead of BLE:

```bash
uv sync --extra ant          # installs openant
# config.yaml
ant:
  enabled: true
  device_id: 0               # 0 = automatic
```

The FE-C channel broadcasts the General FE Data (16), General Settings (17),
Specific Trainer Data (25) and FE Capabilities (54) pages. Control pages for
target power (49), basic resistance (48) and track resistance (51) are applied
to the bike; wind resistance (50) is reported as not supported because an
ergometer cannot emulate wind. Command status is returned in page 71.

Requires a USB ANT stick and access to it (usually via `udev` rules or the
`plugdev` group). If `openant` is missing the backend logs a warning and only
BLE FTMS is used.

## Usage
- Start bridge on Linux: `uv run daum-bridge run`
- Open web UI: `http://<bridge-ip>:8080` (default) for status and gear shifting
- Ride history: `http://<bridge-ip>:8080/history` — view finished rides and upload them to Strava
- Downloads: `http://<bridge-ip>:8080/downloads` — all trainings, newest first, with TCX download + email links
- Finish a training early from the dashboard (**Finish Ride & Save TCX**) or just stop the bridge / disconnect the bike; every finished ride is saved as `rides/<id>.json` and `rides/<id>.tcx`
- On Windows/MyWhoosh, pair/connect to the advertised BLE FTMS device (e.g. `DAUM-8008-TRS`)
- Use ERG/workouts in MyWhoosh as normal; gear changes via web UI

## Config
See `config.example.yaml`. Auto-detect will scan serial ports if `serial.port` not set.
Rides are stored in `rides/` (override with `DAUM_RIDES_DIR`). Strava settings live in the
`strava:` section; see [docs/strava.md](docs/strava.md). Email settings live in the
`email:` section; see [docs/email.md](docs/email.md).

## Notes
- BLE peripheral requires BlueZ on Linux; may need permissions (`CAP_NET_RAW`, `CAP_NET_ADMIN`) or run as appropriate user. See docs/installation.md.
- The BLE backend uses `dbus-next`, which currently does not import on Python 3.13+ (upstream `typing` change). Use Python 3.10–3.12 on the bridge machine; other modules fall back gracefully.
- ANT+ FE-C (`ant.enabled`) is disabled by default, needs the optional `openant` package (`uv sync --extra ant`) and a USB ANT stick. It broadcasts real FE-C pages; see the ANT+ section above.
- MyWhoosh behavior varies; this aims for FTMS compliance.
- Gear shifting is exposed via web UI as requested.
- If hardware not connected, tests use mocks.

## License
MIT
