# Bluetooth/BlueZ Setup for FTMS Peripheral

For MyWhoosh to connect properly, BlueZ needs to be configured as a peripheral.

## Quick checks
```bash
hciconfig
sudo bluetoothctl show
```

## Make adapter discoverable/power on
```bash
sudo bluetoothctl
power on
agent NoInputNoOutput
default-agent
discoverable on
pairable on
quit
```

## Experimental features (if needed)
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

## Permissions
The user running the bridge must be in `bluetooth` group (done by setup script). Also needs D-Bus access to system bus.

## Notes
- Run as the user in bluetooth group (not root)
- On some distros, BlueZ 5.50+ works fine with dbus-next
- If MyWhoosh still doesn't see it, try disabling LE privacy/random address temporarily
```bash
sudo hciconfig hci0 down
sudo hciconfig hci0 up
```
