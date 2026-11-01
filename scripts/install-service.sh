#!/usr/bin/env bash
# Install daum-bridge as systemd service
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=== Installing daum-bridge as systemd service ===${NC}"
echo ""

if [ "$EUID" -eq 0 ]; then
    echo -e "${RED}Please run as normal user (will use sudo for systemctl)${NC}"
    exit 1
fi

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="$USER"

# Create service file
SERVICE_FILE="/tmp/daum-bridge.service"
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Daum 8008 TRS Bridge to MyWhoosh
After=network.target bluetooth.target
Wants=bluetooth.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$PROJECT_DIR
Environment=PATH=$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=$HOME/.local/bin/uv run daum-bridge run --config $PROJECT_DIR/config.yaml
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo cp "$SERVICE_FILE" /etc/systemd/system/daum-bridge.service
sudo chmod 644 /etc/systemd/system/daum-bridge.service

sudo systemctl daemon-reload
sudo systemctl enable daum-bridge.service

echo -e "${GREEN}Service installed and enabled${NC}"
echo ""
echo "Commands:"
echo "  sudo systemctl start daum-bridge    # Start bridge"
echo "  sudo systemctl stop daum-bridge     # Stop bridge"
echo "  sudo systemctl status daum-bridge   # Check status"
echo "  sudo journalctl -u daum-bridge -f   # View logs"
echo ""
