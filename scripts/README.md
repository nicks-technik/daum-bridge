# Scripts

Helper scripts for setting up and running daum-bridge on Linux (Debian/Raspberry Pi OS).

## setup-linux.sh
Prepares a fresh Debian-based system for the bridge:
- Installs system dependencies (Python, BlueZ, build tools)
- Adds user to `dialout` and `bluetooth` groups
- Installs `uv`
- Creates `config.yaml` from example
- Runs `uv sync`

```bash
chmod +x scripts/setup-linux.sh
./scripts/setup-linux.sh
```

## check-setup.sh
Verifies the setup is correct:
- Checks uv, groups, serial ports, Bluetooth, config

```bash
chmod +x scripts/check-setup.sh
./scripts/check-setup.sh
```

## install-service.sh
Installs daum-bridge as a systemd service to run on boot:

```bash
chmod +x scripts/install-service.sh
./scripts/install-service.sh
sudo systemctl start daum-bridge
```

View logs: `sudo journalctl -u daum-bridge -f`

## Quick Start (Raspberry Pi)
```bash
git clone <repo> ~/daum-bridge
cd ~/daum-bridge
./scripts/setup-linux.sh
# Log out/in
./scripts/check-setup.sh
uv run daum-bridge scan
cp config.example.yaml config.yaml  # edit if needed
uv run daum-bridge run
```
