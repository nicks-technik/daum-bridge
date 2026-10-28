# Installation (via GitHub)

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
Install required packages. Commands vary by distro.

#### Debian/Ubuntu/Raspberry Pi OS
```bash
sudo apt update
sudo apt install -y git python3 python3-pip bluez bluetooth pi-bluetooth
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
# Reload shell
source $HOME/.cargo/env 2>/dev/null || source $HOME/.local/bin/env 2>/dev/null
```

#### Fedora
```bash
sudo dnf install -y git python3 bluez bluez-tools
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env 2>/dev/null || source $HOME/.local/bin/env 2>/dev/null
```

#### Arch Linux
```bash
sudo pacman -S --noconfirm git python bluez bluez-utils
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env 2>/dev/null || source $HOME/.local/bin/env 2>/dev/null
```

Verify BlueZ is installed and running:
```bash
bluetoothd -v
systemctl status bluetooth
hciconfig  # or bluetoothctl show
```

### Permissions (Linux)
```bash
sudo usermod -a -G dialout $USER
sudo usermod -a -G bluetooth $USER
# Logout/login required
```

## Install from GitHub

### Clone the repository
```bash
git clone https://github.com/<your-username>/daum-bridge.git
cd daum-bridge
```

Or download a release/archive from the GitHub repository page.

### Install dependencies
```bash
uv sync
```

For development:
```bash
uv sync --dev
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

### Run
```bash
# Scan for serial ports
uv run daum-bridge scan

# Run with config
uv run daum-bridge run --config config.yaml

# Or auto-detect
uv run daum-bridge run
```

## Web UI
Open `http://<bridge-ip>:8080` for status and gear shifting.

## Notes
- BLE FTMS peripheral requires BlueZ on Linux. See `docs/handling.md` for details.
- MyWhoosh pairs as a BLE FTMS trainer device.
- For more details, see `docs/handling.md`, `docs/overview.md`, and `docs/protocol.md`.
