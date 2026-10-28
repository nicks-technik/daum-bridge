# Overview

## Architecture
```
[Daum 8008 TRS] --RS232--> [RS232->USB] --(serial)-- [Bridge (Linux/RPi)]
                                                              |
                                                              +-- BLE FTMS (BlueZ) --> [MyWhoosh on Windows]
                                                              +-- Web UI (HTTP) --> [Browser for gear shifting]
```

## Components
- **serial/**: Protocol implementation and port handling
- **bridge.py**: Core orchestration, state management
- **backends/ble_ftms.py**: BLE FTMS peripheral (Linux focus)
- **web/**: FastAPI web UI for status and gear shifting
- **cli.py**: Typer CLI

## Data Flow
1. Bridge discovers Daum cockpit address via serial
2. Polls `run_Data` every ~500ms to get power/cadence/speed/gear
3. Exposes data via BLE FTMS Indoor Bike Data and web UI
4. MyWhoosh sends target power via FTMS Control Point -> bridge forwards to Daum via `set_Watt`
5. User shifts gears via web UI -> bridge sends `set_Gear`

## Platform Notes
- **Linux (primary)**: Run bridge here, MyWhoosh on Windows connects via BLE
- **Windows**: Bridge can run but BLE peripheral more restricted; documented as backup
- **RPi**: Also supported
