# Overview

See also: [installation.md](installation.md), [protocol.md](protocol.md), [glossary.md](glossary.md)

## Architecture
```
[Daum 8008 TRS] --RS232--> [RS232->USB] --(serial)-- [Bridge (Linux/RPi)]
                                                              |
                                                              +-- BLE FTMS (BlueZ) --> [MyWhoosh on Windows]
                                                              +-- Web UI (HTTP) --> [Browser for gear shifting]
```

## Components
- serial/: Protocol implementation and port handling
- bridge.py: Core orchestration
- backends/ble_ftms.py: BLE FTMS peripheral (Linux)
- web/: FastAPI web UI
- cli.py: Typer CLI

## Data Flow
1. Discover Daum address via serial
2. Poll run_Data every ~500ms
3. Expose via BLE FTMS and web UI
4. Forward target power via set_Watt
5. Gear shifts via web UI

## Platform Notes
- Linux (primary)
- Windows (limited)
- RPi supported
