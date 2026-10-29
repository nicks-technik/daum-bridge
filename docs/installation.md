# Installation (via GitHub)

See also: [overview.md](overview.md), [protocol.md](protocol.md), [glossary.md](glossary.md)

This guide covers installing the Daum Bridge from GitHub and its prerequisites.

## Prerequisites

### Hardware
- Daum 8008 TRS cockpit with RS232 port
- Original Daum RS232 cable
- RS232→USB adapter
- Linux machine (recommended: Raspberry Pi or separate PC) with Bluetooth
- Windows machine running MyWhoosh (for BLE connection)
- Bluetooth range between Linux bridge and Windows/MyWhoosh

### Software Requirements
- Python >= 3.10
- [uv](https://docs.astral.sh/uv/) for dependency management
- Git
- `pyserial`, `dbus-next` (installed via dependencies)

## Installing Prerequisites

### On Windows (to clone/manage repo and run tooling)
Use `winget` (Windows Package Manager). Open PowerShell/Terminal as Administrator if needed.

```powershell
# Install Git
winget install --id Git.Git -e --source winget

# Install GitHub CLI (optional but recommended for repo management)
winget install --id GitHub.cli -e --source winget

# Install uv (Python package/dependency manager)
winget install --id astral-sh.uv -e --source winget

# Install Python (if not already installed)
winget install --id Python.Python.3.12 -e --source winget
```

After installation, restart your terminal so `git`, `gh`, `uv`, `python` are in PATH.

Verify:
```powershell
git --version
gh --version  # optional
uv --version
python --version
```

### On Linux (for the bridge - recommended)
Use the automated setup script, or install manually.

#### Automated (recommended)
```bash
git clone https://github.com/<your-username>/daum-bridge.git
cd daum-bridge
chmod +x scripts/setup-linux.sh
./scripts/setup-linux.sh
```
The script installs dependencies, adds you to `dialout`/`bluetooth` groups, sets up config, installs Python deps with uv, runs checks, and prints a summary of any problems.

#### Manual by distro
##### Debian/Ubuntu/Raspberry Pi OS
```bash
sudo apt update
sudo apt install -y git python3 python3-pip python3-venv build-essential pkg-config libffi-dev libssl-dev bluez bluetooth libbluetooth-dev dbus libdbus-1-dev libglib2.0-dev usbutils python3-dbus python3-gi
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env 2>/dev/null || source $HOME/.cargo/env 2>/dev/null
```

##### Fedora
```bash
sudo dnf install -y git python3 bluez bluez-tools bluez-libs-devel dbus-devel glib2-devel libffi-devel openssl-devel gcc pkg-config
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env 2>/dev/null || source $HOME/.cargo/env 2>/dev/null
```

##### Arch Linux
```bash
sudo pacman -S --noconfirm git python bluez bluez-utils base-devel pkg-config libffi openssl dbus glib2
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env 2>/dev/null || source $HOME/.cargo/env 2>/dev/null
```

Verify BlueZ:
```bash
bluetoothd -v
systemctl status bluetooth
hciconfig  # or bluetoothctl show
```

### Permissions (Linux)
```bash
sudo usermod -a -G dialout $USER
sudo usermod -a -G bluetooth $USER
# Logout/login required (or use newgrp)
```

## Install from GitHub

### Clone the repository
```bash
git clone https://github.com/<your-username>/daum-bridge.git
cd daum-bridge
```

### Install dependencies
```bash
uv sync
```

For development:
```bash
uv sync --dev
```

With the optional ANT+ FE-C backend:
```bash
uv sync --extra ant
```

### Configure
```bash
cp config.example.yaml config.yaml
# Edit config.yaml as needed (serial port, BLE settings, web UI)
```

You can also use environment variables:
- `DAUM_SERIAL_PORT`
- `DAUM_BLE_NAME`
- `DAUM_WEB_PORT`
- `DAUM_MAX_GEAR` (highest gear for resistance mapping, default 20)
- `DAUM_ANT_ENABLED`, `DAUM_ANT_DEVICE_ID`, `DAUM_ANT_NETWORK_KEY`

### Run
```bash
# Scan for serial ports
uv run daum-bridge scan

# Run with config
uv run daum-bridge run --config config.yaml

# Or auto-detect
uv run daum-bridge run
```

## WSL2 Notes
When using WSL2, direct USB/Bluetooth passthrough isn't available by default.

### USB (RS232→USB adapter)
Use [usbipd-win](https://github.com/dorssel/usbipd-win) to attach the USB adapter to WSL2:
```powershell
# On Windows (as admin)
winget install usbipd
usbipd list
usbipd bind --busid <BUSID>
usbipd attach --wsl --busid <BUSID>
```
In WSL, check with `ls /dev/ttyUSB* /dev/ttyACM*`.

### Bluetooth (BLE FTMS)
WSL2 kernels often lack a full Bluetooth stack; BLE peripheral (advertising as FTMS) is unreliable. For best results, use native Linux (Raspberry Pi/PC). If you must use WSL2, you may need a USB Bluetooth adapter passed through via usbipd and a compatible kernel - success not guaranteed.

### Web UI access
The web UI will be available on the WSL IP or via `http://localhost:<port>` depending on port forwarding. Check with `ip addr show eth0` or use Windows portproxy if needed.

## Bluetooth/BlueZ Setup (FTMS Peripheral)

For MyWhoosh to connect properly, BlueZ needs to be configured as a peripheral.

### Quick checks
```bash
hciconfig
sudo bluetoothctl show
```

### Make adapter discoverable/power on
```bash
sudo bluetoothctl
power on
agent NoInputNoOutput
default-agent
discoverable on
pairable on
quit
```

### Experimental features (if needed)
Some BlueZ versions need experimental features for GATT server/advertising. Edit `/etc/systemd/system/bluetooth.target.wants/bluetooth.service` or override:
```bash
sudo systemctl edit bluetooth
```
Add:
```ini
[Service]
ExecStart=
ExecStart=/usr/lib/bluetooth/bluetoothd -E
```
Then restart:
```bash
sudo systemctl daemon-reload
sudo systemctl restart bluetooth
```

### Permissions
The user running the bridge must be in `bluetooth` group (done by setup script). Also needs D-Bus access to system bus.

### Tips
- Run as the user in bluetooth group (not root)
- On some distros, BlueZ 5.50+ works fine with dbus-next
- If MyWhoosh still doesn't see it, try disabling LE privacy/random address temporarily
```bash
sudo hciconfig hci0 down
sudo hciconfig hci0 up
```

## ANT+ FE-C (optional)

In addition to BLE FTMS the bridge can act as an ANT+ FE-C trainer. Install
the optional dependency and enable it in `config.yaml`:

```bash
uv sync --extra ant
```

```yaml
ant:
  enabled: true
  device_id: 0        # 0 = automatic
  network_key: ""     # empty = ANT+ public key (B9 A5 21 FB BD 72 C3 45)
```

The backend opens a master channel for device type 17 (4 Hz) and broadcasts
pages 16 (General FE Data), 17 (General Settings), 25 (Specific Trainer Data)
and 54 (FE Capabilities). Control pages are decoded and applied to the bike:

| Page | Request | Applied as |
| --- | --- | --- |
| 49 | Target power | `set_target_watt()` (ERG) |
| 48 | Basic resistance | resistance % → gear |
| 51 | Track resistance | grade % → resistance % → gear |
| 50 | Wind resistance | not supported (command status reports it) |

Page 71 (Command Status) reports the result of the last control page. If
`openant` is not installed the backend logs a warning and BLE remains active.

ANT USB sticks usually need permissions. Add a udev rule (adjust the vendor
ID, e.g. Dynastream 0fcf) or run as a user in the `plugdev` group:

```bash
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="0fcf", MODE="0666"' | \
  sudo tee /etc/udev/rules.d/51-ant-usb.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

## Handlebar shift buttons (optional)

Shift gears from buttons on the bike instead of the web UI. Two backends are
available and can run together:

```bash
uv sync --extra gpio --extra input
```

```yaml
input:
  enabled: true
  backend: both     # none | gpio | evdev | both
```

- `gpio`: two momentary buttons on BCM17/BCM27 to GND (bridge must run on the Pi).
- `evdev`: a Bluetooth HID button paired with `bluetoothctl`, read as an input
  device (the bridge user must be in the `input` group).

Check the wiring before riding:

```bash
uv run daum-bridge inputs status
uv run daum-bridge inputs list
uv run daum-bridge inputs test
```

See [gearshift-buttons.md](gearshift-buttons.md) for wiring, pairing, hardware
suggestions and troubleshooting.

## Web UI
Open `http://<bridge-ip>:8080` for status and gear shifting.

## Notes
- BLE FTMS peripheral requires BlueZ on Linux. See [overview.md](overview.md) for details.
- MyWhoosh pairs as a BLE FTMS trainer device.
- The optional ANT+ FE-C backend requires `uv sync --extra ant`, a USB ANT stick and device permissions.
- For protocol details, see [protocol.md](protocol.md).
