# WSL/Linux Prep Guide for daum-bridge

When you're ready to run this on Linux (WSL2 or native), follow these steps.

## Quick Setup
```bash
# Clone repo
git clone https://github.com/nicks-technik/daum-bridge.git
cd daum-bridge

# Install deps
chmod +x scripts/setup-linux.sh
./scripts/setup-linux.sh

# Logout/login for group changes
newgrp dialout
newgrp bluetooth

# Check setup
./scripts/check-setup.sh

# Configure
cp config.example.yaml config.yaml
# Edit config.yaml as needed (serial port, ble adapter)

# Scan for Daum
uv run daum-bridge scan

# Run
uv run daum-bridge run
```

## Notes for WSL2
- WSL2 doesn't have direct USB/Bluetooth passthrough by default. For serial (RS232->USB), use `usbipd-win` to attach the USB adapter to WSL2.
- For Bluetooth (BLE FTMS), WSL2 kernel may lack full Bluetooth stack; native Linux (Raspberry Pi) is recommended for reliable BLE peripheral.
- Web UI will work from Windows via `http://localhost:<port>` if port-forwarded, or use the WSL IP.

## Systemd Service (native Linux)
```bash
chmod +x scripts/install-service.sh
./scripts/install-service.sh
sudo systemctl start daum-bridge
journalctl -u daum-bridge -f
```

## Bluetooth permissions
If BLE doesn't advertise properly:
```bash
sudo bluetoothctl power on
sudo bluetoothctl advertise on  # or let BlueZ handle
# May need to run with proper capabilities
```

See `docs/handling.md` for more details.
