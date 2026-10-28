# Glossary

- **FTMS** (Fitness Machine Service): Bluetooth GATT service (UUID 0x1826) defined by the Bluetooth SIG for fitness equipment like treadmills, bikes, and rowers. It allows trainers/apps (e.g., MyWhoosh) to read data (power, cadence, speed) and send control commands (target power/ERG).
- **GATT** (Generic Attribute Profile): Bluetooth LE protocol for discovering and exchanging data via services/characteristics.
- **BlueZ**: Linux Bluetooth stack used for BLE scanning/advertising and GATT.
- **ERG mode**: Electronic Resistance/Goal mode where the trainer maintains a target power regardless of cadence.
- **RS232**: Serial communication standard used by the Daum 8008 TRS cockpit.
- **INDOOR_BIKE_DATA (0x2AD2)**: FTMS characteristic for broadcasting live bike metrics.
- **FITNESS_MACHINE_CONTROL_POINT (0x2AD9)**: FTMS characteristic for receiving control commands from the app.
- **FITNESS_MACHINE_FEATURE (0x2AD8)**: FTMS characteristic describing supported features/capabilities.
- **D-Bus**: Inter-process communication system used by BlueZ on Linux.
- **dbus-next**: Python library for interacting with D-Bus (used for BlueZ GATT registration).
