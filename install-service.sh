#!/bin/bash
# Systemd service installation script for daum-bridge

SERVICE_NAME="daum-bridge"
USER="${USER:-pi}"
GROUP="${GROUP:-pi}"
WORKDIR="$(pwd)"
EXEC_PATH="$(which uv 2>/dev/null || echo /usr/local/bin/uv)"

sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null <<EOF
[Unit]
Description=Daum 8008 TRS to BLE/ANT+ Bridge
After=bluetooth.target network.target
Wants=bluetooth.target

[Service]
Type=simple
User=${USER}
Group=${GROUP}
WorkingDirectory=${WORKDIR}
Environment=PATH=/usr/local/bin:/usr/bin:/bin
Environment=PYTHONUNBUFFERED=1
ExecStart=${EXEC_PATH} run daum-bridge run --config ${WORKDIR}/config.yaml
Restart=always
RestartSec=5
NoNewPrivileges=true
ReadWritePaths=${WORKDIR}
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_RAW
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_RAW
RestrictAddressFamilies=AF_UNIX AF_BLUETOOTH AF_NETLINK
MemoryMax=256M
CPUQuota=50%

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}
sudo systemctl start ${SERVICE_NAME}
echo "Service installed and started"
echo "Check status: sudo systemctl status ${SERVICE_NAME}"
echo "View logs: journalctl -u ${SERVICE_NAME} -f"
