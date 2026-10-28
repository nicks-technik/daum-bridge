# Handling & Setup Guide

## Hardware Setup
1. Connect original Daum RS232 cable to 8008 TRS cockpit
2. Connect RS232→USB adapter to cable
3. Plug adapter into Linux machine
4. Power on Daum 8008 TRS

## Linux Permissions
For serial access:
```bash
sudo usermod -a -G dialout $USER
# logout/login required
```

For BLE/BlueZ:
```bash
# May need to run with capabilities or as root in some cases
# Or add user to bluetooth group
sudo usermod -a -G bluetooth $USER
```

## BlueZ Setup
```bash
# Check adapter
hciconfig
# or
bluetoothctl
```

Ensure BlueZ is running and adapter is up.

## Finding Serial Port
```bash
uv run daum-bridge scan
# or
ls /dev/ttyUSB* /dev/ttyACM*
```

## Running
```bash
# With config
cp config.example.yaml config.yaml
uv run daum-bridge run --config config.yaml

# Auto-detect
uv run daum-bridge run

# Specify port
uv run daum-bridge run --port /dev/ttyUSB0
```

## MyWhoosh Pairing
1. Start bridge on Linux
2. On Windows running MyWhoosh, open Bluetooth settings / MyWhoosh device pairing
3. Look for device named `DAUM-8008-TRS` (or as configured)
4. Pair/connect as a trainer/FTMS device
5. Start ride - power/cadence should appear; ERG control should work

## Web UI (Gear Shifting)
Open browser to `http://<bridge-ip>:8080` to view status and use Shift Up/Down buttons.

## Troubleshooting
- **No serial port found**: Check cable/adapter, permissions, try different USB port
- **No address discovered**: Bike must be on, check RS232 connection
- **BLE not visible**: Check BlueZ, adapter up, permissions, firewall
- **MyWhoosh doesn't connect**: Ensure FTMS peripheral is properly advertised (skeleton implementation needs completion)
- **Raw frames**: Set `logging.log_raw_frames: true` in config for debugging

## BLE FTMS Implementation Notes
The current BLE backend is a skeleton. For full functionality on Linux:
- Use D-Bus to register GATT application with BlueZ
- Implement FTMS service (UUID 0x1826)
- Indoor Bike Data (0x2AD2) - notify with power/cadence/speed
- Fitness Machine Control Point (0x2AD9) - write/indicate for target power
- May need `dbus-next` and proper BlueZ agent setup

See [BlueZ GATT examples](https://git.kernel.org/pub/scm/bluetooth/bluez.git/tree/test) and daumUSB2BLE's BLE implementation for reference.

## Two PC Setup
As requested, bridge runs on Linux, MyWhoosh on Windows - they connect over BLE (Linux advertises, Windows scans/pairs). Both on same network not strictly required for BLE, just Bluetooth range.
