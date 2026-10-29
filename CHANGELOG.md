# Changelog

All notable changes to this project are documented here.
This project follows [Semantic Versioning](https://semver.org/).

## [0.4.0] - 2026-10-29

### Added
- Handlebar shift buttons: shift gears from physical buttons instead of the web
  UI or MyWhoosh. Two interchangeable backends can run together: `gpio` (two
  momentary buttons on Raspberry Pi BCM pins via gpiozero) and `evdev`
  (Bluetooth/USB HID buttons read from `/dev/input`, so pairing stays inside
  BlueZ and does not compete with the FTMS peripheral for the adapter).
- Hold-to-repeat shifting with a configurable initial delay and interval, plus a
  minimum interval between shifts that protects the 9600 baud serial link.
- `daum-bridge inputs list|test|status`: find an input device and its keys,
  watch the buttons live, and verify the configured backends.
- Input state in `/api/state` and `/api/diagnostics` (active backends, last
  shift source, backend problems) and a "Handlebar shift buttons" section on
  the web config page.
- Optional extras `uv sync --extra gpio` and `--extra input`; the default
  installation stays free of hardware dependencies.
- `docs/gearshift-buttons.md`: wiring (BCM17/BCM27, RC filter), Bluetooth
  pairing and permissions, hardware options and troubleshooting.

### Changed
- Gear shifting from the buttons, web UI and CLI now goes through a single
  `DaumBridge.shift(delta, source)` call.
- A shift leaves ERG mode by default (`input.shift_clears_erg`), so the gear
  change actually alters the load.

### Fixed
- Gear changes requested while ERG mode was active had no effect on the
  resistance because the cockpit kept holding the last target power.

## [0.3.0] - 2026-10-29

### Added
- Ride recording: power, cadence, speed, heart rate and distance are sampled once
  per second and stored in `rides/<id>.json`.
- Ride finishing on the dashboard button, serial disconnect and bridge shutdown,
  with pause/resume of recording afterwards.
- TCX export, written as `rides/<id>.tcx` when a ride finishes (older JSON-only
  rides are converted on demand).
- `/downloads` page listing finished trainings newest-first with per-ride TCX
  download.
- Email delivery of finished rides as TCX attachments (SMTP with STARTTLS or
  implicit TLS, optional authentication, optional auto-send).
- Optional ANT+ FE-C trainer backend (device type 17): broadcasts pages 16, 17,
  25 and 54, applies control pages 48/49/50/51 and answers with page 71.
- Resistance and grade control: FTMS `Set Resistance Level` (0x04) and
  `Set Indoor Bike Simulation Parameters` (0x11) are mapped onto Daum gears
  (`bridge.max_gear`, 1..28).
- CCCD descriptors for every notify/indicate characteristic, so heart rate and
  cycling power notifications can be subscribed.
- Config/state/diagnostics expose ANT+, target resistance and target grade;
  `DAUM_MAX_GEAR`, `DAUM_ANT_ENABLED`, `DAUM_ANT_DEVICE_ID` and
  `DAUM_ANT_NETWORK_KEY` environment overrides.

### Fixed
- Saving the configuration from the web UI failed with HTTP 500 because it
  imported PyYAML, which is not a dependency; it now uses the project YAML
  helpers (ruamel with a PyYAML fallback).
- Applying resistance or grade now leaves ERG mode, so gear changes actually
  change the load; setting a target power clears stale resistance/grade state.
- FTMS control point responses and status opcodes match the specification
  (reset/stopped/started/resistance/target power/simulation, control not
  permitted, invalid parameter).
- The BLE backend reports that it is unavailable instead of idling when D-Bus or
  dbus-next is missing, and re-registers GATT/advertising after an adapter power
  cycle.
- ANT+ FE-C wind resistance is reported as not supported instead of being
  silently ignored; invalid target power (0xFFFF) is ignored.

### Changed
- ANT+ FE-C replaces the previous experimental stub; it requires the optional
  `ant` extra (`uv sync --extra ant`) and an ANT USB stick.
- `ant.device_path` was replaced by `ant.device_id` plus an optional
  `ant.network_key` hex override.
- `bluez-peripheral` was removed from the dependencies (unused).
- `serial/autodetect.py` was removed in favour of `serial/port.py`.

## [0.2.0] - 2026-10-12

### Added
- Strava integration: OAuth token handling, activity upload from TCX and
  `daum-bridge strava-auth` / `strava-upload` commands.

## [0.1.1] and earlier

See the git history for the initial BLE FTMS bridge, serial protocol
implementation and web UI.
