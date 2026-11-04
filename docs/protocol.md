# Daum 8008 TRS Protocol Notes

See also: [installation.md](installation.md), [overview.md](overview.md), [glossary.md](glossary.md)

Based on analysis of [weinzmi/daumUSB2BLE/daumUSB.js](https://github.com/weinzmi/daumUSB2BLE).

## Connection
- RS232, typically 9600 baud (8N1 common)
- Uses original Daum cable + RS232→USB adapter

## Commands (from daumUSB.js)
| Command | Hex | Purpose |
|---------|-----|---------|
| get_Adress | 0x11 | Discover cockpit address |
| get_PersonData | 0x74 | Get user data |
| run_Data | 0x40 | Request live data |
| set_Watt | 0x51 | Set target power (ERG) |
| set_Gear | 0x53 | Set gear |
| set_Prog | 0x23 | Set program |
| set_WattProfile | 0x68 | Set watt profile |

The values above are the `daumCommands` table from the reference
`config.yml`. An earlier revision of this document listed unrelated `0xA1`…
values, which never matched the reference implementation.

## Load control: ERG vs. simulation
The brake only understands a target power (`set_Watt`, ergopower =
`round(W / 5)`). Everything else is a translation:

- **ERG**: the app sends FTMS `Set Target Power` (0x05) or FE-C page 49; the
  bridge forwards that wattage and re-applies it while the target is active.
  The cockpit holds the power and reports it back.
- **Simulation / free ride**: apps send a road grade (FTMS 0x11, FE-C page 51),
  not a wattage. The Daum has no incline motor, so `daum_bridge.sim` turns the
  cockpit's own speed and the grade into the power a rider would need on that
  slope (gravity + rolling resistance + drag), and the bridge sends *that* as
  the target power. Because the gear changes the speed the cockpit reports,
  gearing changes the load — the virtual-gear behaviour of a smart trainer.

The run-data power byte is the power the cockpit regulates, in 5 W units. At
zero cadence the bridge reports 0 W. The cockpit never reports below 25 W,
which is why an unloaded bike always shows 25 W on its display.

An idle `set_Watt` must not be sent: `set_Watt 0` leaves the cockpit in watt
mode, where it holds 25 W and ignores the gear buttons. Releasing ERG therefore
also sends `set_Prog 0`.

## Discovery
1. Send `get_Adress` (0x11)
2. Parse response to extract cockpit address
3. Use address in subsequent commands: `[cmd][addr][data]`

## Polling
- Request `run_Data` (0x40) every ~500ms
- Parse power, cadence/rpm, speed, etc from response
- Only frames whose second byte equals the discovered cockpit address are used

## Bidirectional Control
- **Read**: Poll `run_Data` for current values
- **Write**: `set_Watt` for ERG target power, `set_Gear` for shifting, `set_Prog` for programs
- `set_Watt` takes the ergopower value, i.e. `round(watts / 5)`, not raw watts
- The parser still accepts the legacy `0xA1`/`0xA2`/`0xA4` response prefixes,
  but requests and writes always use the table above

## Notes
- Frame format details vary; our implementation is simplified but follows the pattern
- Real parsing may need adjustment based on actual bike firmware
- Raw frame logging available via config (`logging.log_raw_frames: true`)

## References
- [weinzmi/daumUSB2BLE](https://github.com/weinzmi/daumUSB2BLE) - working Node.js implementation
- [ergoFACE](https://github.com/weinzmi/ergoFACE) - fork
