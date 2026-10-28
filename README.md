# daum-bridge

Bridge for **Daum 8008 TRS** ergo bike (RS232 via original Daum cable + RS232→USB adapter) to **MyWhoosh** via **BLE FTMS**. Designed to run on **Linux** (separate PC/RPi) while MyWhoosh runs on Windows. Includes a simple web UI for gear shifting and status.

> Based on protocol insights from [weinzmi/daumUSB2BLE](https://github.com/weinzmi/daumUSB2BLE) / ergoFACE.

## Features
- RS232 protocol to Daum 8008 TRS (address discovery, `run_Data` polling, `set_Watt`, `set_Gear`, `set_Prog`)
- BLE FTMS peripheral (Linux/BlueZ) exposing Indoor Bike Data + Fitness Machine Control Point
- Bidirectional control: receive target power/ERG commands from MyWhoosh and forward to bike
- Gear shifting via web UI (and CLI)
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

See [scripts/README.md](scripts/README.md), [docs/overview.md](docs/overview.md), [docs/protocol.md](docs/protocol.md), [docs/handling.md](docs/handling.md) for details.

## Usage
- Start bridge on Linux: `uv run daum-bridge run`
- Open web UI: `http://<bridge-ip>:8080` (default) for status and gear shifting
- On Windows/MyWhoosh, pair/connect to the advertised BLE FTMS device (e.g. `DAUM-8008-TRS`)
- Use ERG/workouts in MyWhoosh as normal; gear changes via web UI

## Config
See `config.example.yaml`. Auto-detect will scan serial ports if `serial.port` not set.

## Notes
- BLE peripheral requires BlueZ on Linux; may need permissions (`CAP_NET_RAW`, `CAP_NET_ADMIN`) or run as appropriate user. See docs/handling.md.
- MyWhoosh behavior varies; this aims for FTMS compliance.
- Gear shifting is exposed via web UI as requested.
- If hardware not connected, tests use mocks.

## License
MIT
