# Daum 8008 TRS Protocol Notes

See also: [installation.md](installation.md), [overview.md](overview.md), [handling.md](handling.md), [wsl-prep.md](wsl-prep.md)

Based on analysis of [weinzmi/daumUSB2BLE/daumUSB.js](https://github.com/weinzmi/daumUSB2BLE).

## Connection
- RS232, typically 9600 baud (8N1 common)
- Uses original Daum cable + RS232→USB adapter

## Commands (from daumUSB.js)
| Command | Hex | Purpose |
|---------|-----|---------|
| get_Adress | 0xA1 | Discover cockpit address |
| get_PersonData | 0xA2 | Get user data |
| run_Data | 0xA4 | Request live data |
| set_Watt | 0xA6 | Set target power (ERG) |
| set_Gear | 0xA7 | Set gear |
| set_Prog | 0xA9 | Set program |
| set_WattProfile | 0xAA | Set watt profile |

## Discovery
1. Send `get_Adress` (0xA1)
2. Parse response to extract cockpit address
3. Use address in subsequent commands: `[cmd][addr][data]`

## Polling
- Request `run_Data` every ~500ms
- Parse power, cadence/rpm, speed, etc from response

## Bidirectional Control
- **Read**: Poll `run_Data` for current values
- **Write**: `set_Watt` for ERG target power, `set_Gear` for shifting, `set_Prog` for programs

## Notes
- Frame format details vary; our implementation is simplified but follows the pattern
- Real parsing may need adjustment based on actual bike firmware
- Raw frame logging available via config (`logging.log_raw_frames: true`)

## References
- [weinzmi/daumUSB2BLE](https://github.com/weinzmi/daumUSB2BLE) - working Node.js implementation
- [ergoFACE](https://github.com/weinzmi/ergoFACE) - fork
