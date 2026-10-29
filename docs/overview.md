# Overview

See also: [installation.md](installation.md), [protocol.md](protocol.md), [strava.md](strava.md), [email.md](email.md), [glossary.md](glossary.md)

## Architecture
```
[Daum 8008 TRS] --RS232--> [RS232->USB] --(serial)-- [Bridge (Linux/RPi)]
                                                              |
                                                              +-- BLE FTMS (BlueZ) --> [MyWhoosh on Windows]
                                                              +-- Web UI (HTTP) --> [Browser for gear shifting]
```

## Components
- serial/: Protocol implementation and port handling
- bridge.py: Core orchestration and ride recording
- history.py: Ride persistence (`rides/*.json`, `rides/*.tcx`)
- integrations/: TCX generation, Strava upload and email delivery
- backends/ble_ftms.py: BLE FTMS peripheral (Linux)
- web/: FastAPI web UI
- cli.py: Typer CLI

## Data Flow
1. Discover Daum address via serial
2. Poll run_Data every ~500ms
3. Expose via BLE FTMS and web UI
4. Forward target power via set_Watt
5. Gear shifts via web UI
6. Record power/cadence/heart rate/distance once per second; save the ride when the bike
   disconnects, the bridge stops, or *Finish Ride* is pressed
7. Optionally upload/email the ride as TCX (manual download, API upload or email attachment)

## Platform Notes
- Linux (primary)
- Windows (limited)
- RPi supported
