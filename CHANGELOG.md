# Changelog

All notable changes to this project are documented here.
This project follows [Semantic Versioning](https://semver.org/).

## [0.5.1] - 2026-11-12

### Fixed
- Free ride gear shifting: the cockpit is put back into manual program 0 with
  gear mode active (`set_Prog 0` + `set_Gear`) after every connection and when
  simulation starts. Before this, `set_Watt` left it in watt mode, so the jog
  wheel changed the target power and the bike's own gear buttons did nothing.
- Cockpit-side gear changes are read from the run data and adopted by the
  bridge during free ride, keeping the web UI and the simulated load in sync.
- FTMS Request Control (0x00) no longer marks ERG as granted; apps request
  control for free ride too, so the bridge no longer assumed a target power
  had been set.
- Free-ride wind and surface: FTMS simulation parameters (0x11) now pass wind
  speed, Crr and Cw into the power model instead of dropping all but the grade.
  ANT+ FE-C wind pages (50) are supported instead of rejected, and page 51 Crr
  is used. Headwind raises the load, tailwind lowers it.
- ``config.example.yaml`` uses a valid ``max_gear`` (27) and documents that it
  must match the cockpit's top gear; above it, cockpit shifts are pulled back.

## [0.5.0] - 2026-11-02

### Added
- BLE heart-rate belt support (``heart_rate`` config section): the bridge scans
  for the strap on the same adapter that advertises FTMS, subscribes to the
  standard Heart Rate Measurement characteristic (0x2A37) and feeds the value
  into the ride recording, so the TCX file contains heart rate even though the
  belt is paired with the bridge instead of the training app. The value is
  republished through the FTMS Heart Rate Service, so MyWhoosh still displays
  it. A strap accepts one central at a time: remove it from the app first.
- ``/api/state`` exposes ``heart_rate_source`` (``ble`` or ``serial``) and
  ``/api/diagnostics`` exposes a ``heart_rate_backend`` status block.

### Fixed
- The heart-rate backend received no notifications even though the strap was
  connected and notifying: dbus-next only delivers broadcast D-Bus signals to a
  connection that registered a matching rule, so the bridge now adds a
  ``PropertiesChanged`` match rule for the Heart Rate Measurement
  characteristic before ``StartNotify``. Heart rate therefore reaches both the
  ride recording and the FTMS Heart Rate Service.
- Training apps showed the host name (``DietPi``) instead of the configured
  ``ble.device_name``: BlueZ serves the GAP Device Name characteristic (0x2A00)
  from the adapter *alias*, not from the advertisement's ``LocalName``. The
  bridge now sets the adapter alias to ``ble.device_name`` at startup; the
  alias is persisted by BlueZ.
- The FTMS advertisement no longer lists the Heart Rate Service when
  ``ble.advertise_heart_rate`` is false, so clients cannot connect to a service
  that is not exported.
- While the BLE heart-rate backend is enabled, the Daum serial frame's guessed
  heart-rate byte is ignored; the parser's byte guesses are noise (0/81/116 at
  rest) and must not overwrite the belt reading.

## [0.4.3] - 2026-11-02

### Added
- Free-ride terrain simulation: when MyWhoosh/Zwift sends a road grade (FTMS
  0x11 / FE-C track simulation), the bridge converts the cockpit's reported
  speed and the grade into a target power using the classic cycling power
  equation (gravity + rolling resistance + aerodynamic drag). That power is
  sent as an ERG target so the Daum brake actually changes load on climbs and
  descents. Gear changes remain in the rider's control and change the
  calculated load by altering the reported speed. Tunable rider/bike constants
  live under the new ``sim`` config section; ``sim.power_scale`` makes the
  whole free ride easier (<1) or harder (>1) without touching the physics.
- ``ble.advertise_heart_rate`` (default ``true``): turn it off when a BLE belt
  is paired directly in the training app. The Daum only reports a heart rate
  when its own chest strap is paired; otherwise the serial value is noise and
  advertising it stops the app from using the real belt.

### Fixed
- FTMS Indoor Bike Data field order was wrong: distance (0x04) and power
  (0x40) bits were set but the payload was packed as speed, cadence, power,
  distance, elapsed. MyWhoosh read power out of the distance bytes and showed
  double/incorrect wattage. Flags are now ``0x0854`` and fields are packed as
  speed, cadence, distance, power, elapsed (matching bit order). The Cycling
  Power characteristic remains unchanged.
- ERG mode could not be released cleanly: setting ``target_watt`` to 0 left
  the cockpit in watt mode, holding 25 W and ignoring the gear buttons until a
  power cycle. Releasing ERG now also sends ``set_Prog 0``. The bridge never
  re-applies ``set_Watt 0`` at idle (which would keep watt mode active).
- Shifting while ERG is active now leaves ERG mode by default
  (``input.shift_clears_erg``), so handlebar buttons and the web UI can change
  gears/load again.
- Bridge state snapshots now expose ``sim_active`` and ``sim_watt`` for the
  web UI and diagnostics.

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
