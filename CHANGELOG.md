# Changelog

All notable changes to this project are documented here.
This project follows [Semantic Versioning](https://semver.org/).

## [0.4.2] - 2026-11-01

### Changed
- `requires-python` is now `>=3.10,<3.13`, `.python-version` pins 3.12 and the
  installation guide documents the supported range. `dbus-next` does not
  import on Python 3.13+, so the BLE FTMS backend could never start there.

### Fixed
- Serial control never reached the cockpit: the command bytes did not match
  the reference `daumUSB.js` (`get_Adress` 0x11, `run_Data` 0x40, `set_Watt`
  0x51, `set_Gear` 0x53, `set_Prog` 0x23, `set_WattProfile` 0x68,
  `get_PersonData` 0x74), so discovery, polling and shifting all sent
  unrelated commands. `set_watt` now also sends the ergopower value
  (`round(watts / 5)`) instead of raw watts. `docs/protocol.md` was corrected;
  response parsing still accepts the legacy `0xA1`/`0xA2`/`0xA4` prefixes.
- BLE FTMS could not start at all: `requires-python` allowed Python 3.13+, where
  `dbus-next` fails to import (`typing.no_type_check_decorator` was removed).
  The project now requires Python >=3.10,<3.13 and pins `.python-version` to
  3.12; `uv run` picks a working interpreter automatically.
- The GATT application was rejected by BlueZ even on supported Python versions:
  - All BlueZ D-Bus properties were declared read/write, which dbus-next
    rejects at export time ("property is writable but does not have a setter").
    They are now explicitly read-only, with setters for `Value`/`Notifying`.
  - `Characteristic.Value` returned a `list` for signature `ay` (dbus-next
    requires `bytes`).
  - The application object did not expose
    `org.freedesktop.DBus.ObjectManager.GetManagedObjects`, so BlueZ reported
    "No object received"/"No valid service object found". The backend now
    exports a minimal object manager for its GATT tree.
- The backend exported its own CCCD (0x2902) for every notify/indicate
  characteristic, but BlueZ already creates one for external GATT applications
  (`database_add_ccc`). The result was a duplicate, spec-invalid CCCD whose
  writes were handled by the app instead of BlueZ, so subscriptions made
  through it never enabled notifications. The manual descriptor export was
  removed.
- No FTMS/HR/cycling-power data reached the client (e.g. MyWhoosh) even though
  the app connected: `Characteristic.send_notification` passed an already
  wrapped `Variant('ay', ...)` to `emit_properties_changed`, which wraps the
  value itself. Every send raised `SignatureBodyMismatchError`, swallowed at
  debug level. Notifications now pass raw `bytes`, log a warning when they
  fail, and are counted.
- `/api/diagnostics` now includes a `ble` section with per-characteristic
  subscription state (`notifying`/`indicating`), notification counters and the
  last error, so a client that never subscribes is distinguishable from one
  whose notifications fail.
- The BLE failure warning now shows the actual import error and Python version.

## [0.4.1] - 2026-10-29

### Changed
- `DaumBridge` was split into focused collaborators: ride statistics and
  trackpoints now live in `RideRecorder`, and the gear/resistance translation in
  `gears`. `_current_ride`, `_ride_history` and `_ride_paused` remain available
  as views onto the recorder, so the web layer and tests are unaffected.
- The web layer was split into `web.routes` (`pages`, `state`, `rides`,
  `integrations`, `control`, `config`) plus `web.snapshot`; `web/app.py` now only
  assembles the application. All 29 routes keep their paths and response shapes.
- `config.yaml` is parsed one section at a time instead of inside a single
  `try` block, and shared helpers (`numbers`, `formatting`) replace the private
  copies in the CLI, the TCX/email integrations and both backends.
- `cli.py` loads rides through one `_load_ride()` helper shared by
  `strava-upload`, `email-ride` and `export-tcx`.

### Fixed
- A single unreadable value in `config.yaml` (for example `serial.baudrate`)
  no longer discards every section after it. Only the affected field falls back
  to its default and the remaining sections are still applied.
- `GET /api/diagnostics` no longer restarts the "app connected for" timer on
  every poll; the endpoint is read-only and the timestamp is recorded when the
  app actually connects.

### Removed
- The dead `DaumBridge._client_connected` flag. The API still reports
  `client_connected` as an alias of `app_connected` for older clients.

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
