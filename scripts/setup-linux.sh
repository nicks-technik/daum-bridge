#!/usr/bin/env bash
# Setup script for daum-bridge on Debian/Raspberry Pi OS (bridge side)
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=== daum-bridge Linux Setup ===${NC}"
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo -e "${YELLOW}Warning: Running as root. It's recommended to run as normal user.${NC}"
fi

# Update package list
echo -e "${GREEN}[1/7] Updating package list...${NC}"
sudo apt update

# Install system dependencies
echo -e "${GREEN}[2/7] Installing system dependencies...${NC}"
sudo apt install -y \
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
    python3-gi

# Add user to required groups
echo -e "${GREEN}[3/7] Adding user to dialout and bluetooth groups...${NC}"
sudo usermod -a -G dialout,bluetooth "$USER" || true

# Install uv
echo -e "${GREEN}[4/7] Installing uv...${NC}"
if ! command -v uv &> /dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
else
    echo "uv already installed: $(uv --version)"
fi

# Setup project
echo -e "${GREEN}[5/7] Setting up daum-bridge...${NC}"
cd "$(dirname "$0")/.."

# Create config from example if not exists
if [ ! -f config.yaml ]; then
    cp config.example.yaml config.yaml
    echo -e "${YELLOW}Created config.yaml from config.example.yaml${NC}"
    echo "Please edit config.yaml to match your setup (serial port, BLE adapter, etc.)"
fi

# Install dependencies
echo -e "${GREEN}[6/7] Installing Python dependencies...${NC}"
uv sync

# Check Bluetooth
echo -e "${GREEN}[7/7] Checking Bluetooth...${NC}"
if command -v hciconfig &> /dev/null; then
    hciconfig | head -5
else
    echo -e "${YELLOW}hciconfig not found, Bluetooth status unknown${NC}"
fi

echo ""
echo -e "${GREEN}=== Setup Complete ===${NC}"
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
echo "See docs/handling.md for details."
echo ""
