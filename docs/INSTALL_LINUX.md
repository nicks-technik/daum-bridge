# Linux Installation Checklist

## Prerequisites
- Linux (Debian/Ubuntu/Raspberry Pi OS recommended)
- Bluetooth adapter with BlueZ
- RS232->USB adapter connected to Daum 8008 TRS
- Python 3.10+

## Installation
```bash
git clone https://github.com/nicks-technik/daum-bridge.git
cd daum-bridge
./scripts/setup-linux.sh
```

## Post-Setup
1. Re-login or `newgrp dialout && newgrp bluetooth`
2. `./scripts/check-setup.sh` - verify
3. Edit `config.yaml` (set serial port or leave empty for auto-detect)
4. `uv run daum-bridge scan` to find ports
5. `uv run daum-bridge run` to start

## MyWhoosh
1. Ensure bridge is running and advertising as `DAUM-8008-TRS` (default)
2. On Windows, open Bluetooth & pair with device
3. Start MyWhoosh and connect to trainer
4. Use web UI at `http://<bridge-ip>:8080` for gear shifting

## Troubleshooting
- Serial: check `ls /dev/ttyUSB* /dev/ttyACM*`, permissions in dialout group
- BLE: `hciconfig` should show adapter UP, BlueZ running
- Logs: `journalctl -u daum-bridge -f` if using systemd
