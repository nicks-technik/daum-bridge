#!/usr/bin/env bash
# Check setup for daum-bridge
echo "=== daum-bridge Setup Check ==="
echo ""

# Check uv
if command -v uv &> /dev/null; then
    echo "[OK] uv installed: $(uv --version)"
else
    echo "[MISS] uv not installed"
fi

# Check groups
if groups | grep -q dialout; then
    echo "[OK] User in dialout group"
else
    echo "[MISS] User not in dialout group"
fi

if groups | grep -q bluetooth; then
    echo "[OK] User in bluetooth group"
else
    echo "[MISS] User not in bluetooth group"
fi

# Check serial ports
echo ""
echo "Serial ports:"
ls -la /dev/ttyUSB* /dev/ttyACM* 2>&1 | head -10 || echo "  None found"

# Check Bluetooth
echo ""
echo "Bluetooth:"
if command -v hciconfig &> /dev/null; then
    hciconfig 2>&1 | head -10
elif command -v bluetoothctl &> /dev/null; then
    bluetoothctl show 2>&1 | head -15
else
    echo "  No bluetooth tools found"
fi

# Check config
echo ""
if [ -f config.yaml ]; then
    echo "[OK] config.yaml exists"
else
    echo "[MISS] config.yaml not found (copy from config.example.yaml)"
fi

# Check if in project dir
if [ -f pyproject.toml ]; then
    echo "[OK] In project directory"
else
    echo "[MISS] Not in project directory"
fi

echo ""
echo "=== End Check ==="
