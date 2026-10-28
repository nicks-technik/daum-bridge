#!/usr/bin/env bash
# Setup and check script for daum-bridge on Debian/Raspberry Pi OS (bridge side)
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=== daum-bridge Linux Setup & Check ===${NC}"
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo -e "${YELLOW}Warning: Running as root. It's recommended to run as normal user.${NC}"
fi

PROBLEMS=()

# Update package list
echo -e "${GREEN}[1/8] Updating package list...${NC}"
if ! sudo apt update; then
    PROBLEMS+=("apt update failed")
fi

# Install system dependencies
echo -e "${GREEN}[2/8] Installing system dependencies...${NC}"
if ! sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    git \
    curl \
    build-essential \
    pkg-config \
    libffi-dev \
    libssl-dev \
    bluez \
    bluetooth \
    libbluetooth-dev \
    dbus \
    libdbus-1-dev \
    libglib2.0-dev \
    usbutils \
    python3-dbus \
    python3-gi; then
    PROBLEMS+=("Failed to install some system packages")
fi

# Add user to required groups
echo -e "${GREEN}[3/8] Adding user to dialout and bluetooth groups...${NC}"
if ! sudo usermod -a -G dialout,bluetooth "$USER"; then
    PROBLEMS+=("Failed to add user to dialout/bluetooth groups")
fi

# Install uv
echo -e "${GREEN}[4/8] Installing uv...${NC}"
if ! command -v uv &> /dev/null; then
    if ! curl -LsSf https://astral.sh/uv/install.sh | sh; then
        PROBLEMS+=("Failed to install uv")
    else
        export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
    fi
else
    echo "uv already installed: $(uv --version)"
fi

# Setup project
echo -e "${GREEN}[5/8] Setting up daum-bridge...${NC}"
cd "$(dirname "$0")/.."

# Create config from example if not exists
if [ ! -f config.yaml ]; then
    if cp config.example.yaml config.yaml; then
        echo -e "${YELLOW}Created config.yaml from config.example.yaml${NC}"
        echo "Please edit config.yaml to match your setup (serial port, BLE adapter, etc.)"
    else
        PROBLEMS+=("Failed to create config.yaml")
    fi
fi

# Install dependencies
echo -e "${GREEN}[6/8] Installing Python dependencies...${NC}"
if ! uv sync; then
    PROBLEMS+=("Failed to install Python dependencies with uv sync")
fi

# Check setup
echo -e "${GREEN}[7/8] Checking setup...${NC}"
echo ""
echo "=== Checks ==="

# Check uv
if command -v uv &> /dev/null; then
    echo -e "${GREEN}[OK]${NC} uv installed: $(uv --version)"
else
    echo -e "${RED}[MISS]${NC} uv not installed"
    PROBLEMS+=("uv not in PATH")
fi

# Check groups
if groups "$USER" 2>/dev/null | grep -q dialout; then
    echo -e "${GREEN}[OK]${NC} User in dialout group"
else
    echo -e "${RED}[MISS]${NC} User not in dialout group (will take effect after logout/login)"
    PROBLEMS+=("User not in dialout group")
fi

if groups "$USER" 2>/dev/null | grep -q bluetooth; then
    echo -e "${GREEN}[OK]${NC} User in bluetooth group"
else
    echo -e "${RED}[MISS]${NC} User not in bluetooth group (will take effect after logout/login)"
    PROBLEMS+=("User not in bluetooth group")
fi

# Check serial ports
echo ""
echo "Serial ports:"
if ls /dev/ttyUSB* /dev/ttyACM* 2>&1 | grep -q tty; then
    ls -la /dev/ttyUSB* /dev/ttyACM* 2>&1
else
    echo "  None found"
fi

# Check Bluetooth
echo ""
echo "Bluetooth:"
if command -v hciconfig &> /dev/null; then
    hciconfig 2>&1 | head -10
elif command -v bluetoothctl &> /dev/null; then
    bluetoothctl show 2>&1 | head -15
else
    echo "  No bluetooth tools found"
    PROBLEMS+=("No Bluetooth tools found")
fi

# Check config
echo ""
if [ -f config.yaml ]; then
    echo -e "${GREEN}[OK]${NC} config.yaml exists"
else
    echo -e "${RED}[MISS]${NC} config.yaml not found"
    PROBLEMS+=("config.yaml missing")
fi

# Check if in project dir
if [ -f pyproject.toml ]; then
    echo -e "${GREEN}[OK]${NC} In project directory"
else
    echo -e "${RED}[MISS]${NC} Not in project directory"
    PROBLEMS+=("Not in project directory")
fi

# Summary
echo ""
echo -e "${GREEN}[8/8] Summary...${NC}"
echo ""
if [ ${#PROBLEMS[@]} -eq 0 ]; then
    echo -e "${GREEN}=== Setup Complete - No Problems Found ===${NC}"
else
    echo -e "${RED}=== Problems Found (${#PROBLEMS[@]}) ===${NC}"
    for p in "${PROBLEMS[@]}"; do
        echo -e "${RED}- $p${NC}"
    done
    echo ""
    echo -e "${YELLOW}Some issues may require logout/login or manual intervention.${NC}"
fi

echo ""
echo "Next steps:"
echo "1. Log out and back in (or run 'newgrp dialout && newgrp bluetooth') for group changes"
echo "2. Edit config.yaml: set serial.port or use auto-detect"
echo "3. Scan for serial ports: uv run daum-bridge scan"
echo "4. Run bridge: uv run daum-bridge run"
echo "5. Open web UI at http://<this-ip>:8080 for gear shifting"
echo "6. Pair from MyWhoosh on Windows to the BLE device"
echo ""
echo -e "${YELLOW}Note: BLE FTMS peripheral may need additional BlueZ configuration.${NC}"
echo "See docs/overview.md for details."
echo ""
