import asyncio
import struct
from types import SimpleNamespace

from daum_bridge.backends import ble_ftms
from daum_bridge.config import Config
from daum_bridge.serial.daum import DaumState


def test_feature_flags_advertise_sent_data():
    # Cadence, total distance, heart rate, elapsed time and power.
    for bit in (1, 2, 10, 12, 14):
        assert ble_ftms.FEATURE_FLAGS & (1 << bit)
    # Resistance and power target setting.
    assert ble_ftms.TARGET_FEATURE_FLAGS & (1 << 2)
    assert ble_ftms.TARGET_FEATURE_FLAGS & (1 << 3)


def test_indoor_bike_data_layout_matches_flags():
    state = DaumState(
        power=210,
        cadence=90,
        speed=32.4,
        total_distance=1.234,
        elapsed_time=125,
    )

    packet = ble_ftms.build_indoor_bike_data(state)

    assert ble_ftms.INDOOR_BIKE_DATA_FLAGS == 0x1254
    flags, speed, cadence, power = struct.unpack_from("<HHHh", packet, 0)
    distance = int.from_bytes(packet[8:11], "little")
    (elapsed,) = struct.unpack_from("<H", packet, 11)

    assert len(packet) == 13
    # Fields are ordered by flag bit: speed (2), cadence (4), power (6),
    # distance (9), elapsed time (12).
    assert flags == 0x1254
    assert speed == 3240            # 0.01 km/h
    assert cadence == 180           # 0.5 rpm
    assert power == 210             # W
    assert distance == 1234         # m
    assert elapsed == 125           # s


def test_indoor_bike_data_handles_missing_values():
    packet = ble_ftms.build_indoor_bike_data(DaumState())
    flags, speed, cadence, power = struct.unpack_from("<HHHh", packet, 0)
    assert flags == ble_ftms.INDOOR_BIKE_DATA_FLAGS
    assert (speed, cadence, power) == (0, 0, 0)


def test_cycling_power_packet_contains_crank_data():
    state = DaumState(power=250, cadence=90)

    packet = ble_ftms.build_cycling_power(state, now=100.5)

    flags, power, revolutions, event_time = struct.unpack("<HhHH", packet)
    assert flags == ble_ftms.CYCLING_POWER_CRANK_FLAG == 0x0020
    assert power == 250
    assert revolutions == int(100.5 * 90 / 60) & 0xFFFF
    assert event_time == int(0.5 * 1024 * 60 / 90) & 0xFFFF


def test_cycling_power_without_cadence():
    flags, power, revolutions, event_time = struct.unpack(
        "<HhHH", ble_ftms.build_cycling_power(DaumState(power=100), now=5.0)
    )
    assert power == 100
    assert (revolutions, event_time) == (0, 0)


class FakeBridge:
    def __init__(self):
        self._app_connected = False
        self._client_connected = False
        self._app_connected_time = None
        self._erg_control_granted = True
        self.watts = []
        self.resistance = []
        self.grades = []

    def set_target_watt(self, watts):
        self.watts.append(watts)

    def set_resistance_percent(self, percent):
        self.resistance.append(percent)

    def set_grade_percent(self, grade):
        self.grades.append(grade)


def _control_backend(bridge=None):
    backend = ble_ftms.BLEFTMSBackend(bridge or FakeBridge(), Config())
    backend._control_point_enabled = True
    backend._control_point_char = SimpleNamespace(value=[])
    backend._fitness_machine_status_char = SimpleNamespace(value=[])
    return backend


def _response(backend):
    return bytes(backend._control_point_char.value)


def _status(backend):
    return bytes(backend._fitness_machine_status_char.value)


def test_feature_flags_advertise_control_modes():
    assert ble_ftms.TARGET_FEATURE_FLAGS & (1 << 2)  # resistance
    assert ble_ftms.TARGET_FEATURE_FLAGS & (1 << 3)  # target power
    assert ble_ftms.TARGET_FEATURE_FLAGS & (1 << 13)  # simulation parameters


def test_control_point_request_control():
    backend = _control_backend()
    backend._control_point_enabled = False
    backend._handle_control_point(bytes([ble_ftms.OP_REQUEST_CONTROL]))
    assert backend._control_point_enabled is True
    assert _response(backend) == bytes([0x80, 0x00, 0x01])


def test_control_point_set_target_power():
    bridge = FakeBridge()
    backend = _control_backend(bridge)
    backend._handle_control_point(struct.pack("<Bh", ble_ftms.OP_SET_TARGET_POWER, 250))
    assert bridge.watts == [250]
    assert _response(backend) == bytes([0x80, 0x05, 0x01])
    assert _status(backend) == bytes([ble_ftms.STATUS_TARGET_POWER_CHANGED]) == b"\x08"


def test_control_point_set_target_power_clamped():
    bridge = FakeBridge()
    backend = _control_backend(bridge)
    backend._handle_control_point(struct.pack("<Bh", ble_ftms.OP_SET_TARGET_POWER, 2000))
    assert bridge.watts == [800]


def test_control_point_set_resistance_level():
    bridge = FakeBridge()
    backend = _control_backend(bridge)
    backend._handle_control_point(struct.pack("<Bh", ble_ftms.OP_SET_RESISTANCE, 650))
    assert bridge.resistance == [65.0]
    assert _response(backend) == bytes([0x80, 0x04, 0x01])
    assert _status(backend) == bytes([ble_ftms.STATUS_RESISTANCE_CHANGED]) == b"\x07"


def test_control_point_set_simulation_parameters():
    bridge = FakeBridge()
    backend = _control_backend(bridge)
    payload = struct.pack("<BhhBB", ble_ftms.OP_SET_SIMULATION, 500, 350, 40, 51)
    backend._handle_control_point(payload)
    assert bridge.grades == [3.5]
    assert _response(backend) == bytes([0x80, 0x11, 0x01])
    assert _status(backend) == bytes([ble_ftms.STATUS_SIMULATION_CHANGED]) == b"\x12"


def test_control_point_requires_request_control():
    bridge = FakeBridge()
    backend = _control_backend(bridge)
    backend._control_point_enabled = False
    backend._handle_control_point(struct.pack("<Bh", ble_ftms.OP_SET_TARGET_POWER, 200))
    assert bridge.watts == []
    assert _response(backend) == bytes([0x80, 0x05, 0x05])  # control not permitted


def test_control_point_invalid_parameter():
    backend = _control_backend()
    backend._handle_control_point(bytes([ble_ftms.OP_SET_RESISTANCE, 0x10]))
    assert _response(backend) == bytes([0x80, 0x04, 0x03, 0x01])


def test_control_point_unsupported_opcode():
    backend = _control_backend()
    backend._handle_control_point(bytes([0x0A]))
    assert _response(backend) == bytes([0x80, 0x0A, 0x02])


def test_control_point_start_and_stop_status():
    backend = _control_backend()
    backend._handle_control_point(bytes([ble_ftms.OP_START_RESUME]))
    assert _status(backend) == bytes([ble_ftms.STATUS_STARTED_BY_USER]) == b"\x04"
    backend._handle_control_point(bytes([ble_ftms.OP_STOP_PAUSE]))
    assert _status(backend) == bytes([ble_ftms.STATUS_STOPPED_BY_USER]) == b"\x02"


def test_control_point_reset_disables_control():
    bridge = FakeBridge()
    backend = _control_backend(bridge)
    backend._handle_control_point(bytes([ble_ftms.OP_RESET]))
    assert backend._control_point_enabled is False
    assert bridge.watts == [0]
    assert _response(backend) == bytes([0x80, 0x01, 0x01])
    assert _status(backend) == bytes([ble_ftms.STATUS_RESET]) == b"\x01"


class _FakeGattManager:
    def __init__(self, calls):
        self.calls = calls

    async def call_register_application(self, path, options):
        self.calls.append(("gatt-register", path, options))

    async def call_unregister_application(self, path):
        self.calls.append(("gatt-unregister", path))


class _FakeAdvertisingManager:
    def __init__(self, calls):
        self.calls = calls

    async def call_register_advertisement(self, path, options):
        self.calls.append(("adv-register", path, options))

    async def call_unregister_advertisement(self, path):
        self.calls.append(("adv-unregister", path))


class _FakeAdapter:
    def __init__(self, powered=True):
        self.powered = powered

    async def get_powered(self):
        return self.powered


class _FakeProxy:
    def __init__(self, calls, powered=True):
        self.calls = calls
        self.powered = powered

    def get_interface(self, name):
        if name == "org.bluez.GattManager1":
            return _FakeGattManager(self.calls)
        if name == "org.bluez.LEAdvertisingManager1":
            return _FakeAdvertisingManager(self.calls)
        if name == "org.bluez.Adapter1":
            return _FakeAdapter(self.powered)
        raise AssertionError(f"unexpected interface {name}")


class FakeBus:
    """Minimal stand-in for ``dbus_next.aio.MessageBus``."""

    def __init__(self, powered=True):
        self.exported = {}
        self.calls = []
        self.powered = powered
        self.disconnected = False

    def export(self, path, obj):
        self.exported[path] = obj

    async def introspect(self, service, path):
        return object()

    def get_proxy_object(self, service, path, introspection):
        return _FakeProxy(self.calls, self.powered)

    def disconnect(self):
        self.disconnected = True


def test_gatt_setup_exports_ftms_service_and_characteristics():
    backend = ble_ftms.BLEFTMSBackend(FakeBridge(), Config())
    backend._bus = FakeBus()

    asyncio.run(backend._setup_gatt())

    exported = backend._bus.exported
    service = exported[f"{backend._app_path}/service0"]
    assert service.uuid == ble_ftms.FTMS_UUID

    feature = exported[f"{backend._app_path}/service0/char0"]
    assert feature.uuid == ble_ftms.FITNESS_MACHINE_FEATURE_UUID
    assert bytes(feature.value) == struct.pack(
        "<II", ble_ftms.FEATURE_FLAGS, ble_ftms.TARGET_FEATURE_FLAGS
    )

    indoor = exported[f"{backend._app_path}/service0/char1"]
    assert indoor.uuid == ble_ftms.INDOOR_BIKE_DATA_UUID

    control = exported[f"{backend._app_path}/service0/char3"]
    assert control.uuid == ble_ftms.FITNESS_MACHINE_CONTROL_POINT_UUID
    assert control._notify_callback == backend._handle_control_point

    assert ("gatt-register", backend._app_path, {}) in backend._bus.calls


def test_gatt_setup_exports_cccd_for_every_notify_characteristic():
    backend = ble_ftms.BLEFTMSBackend(FakeBridge(), Config())
    backend._bus = FakeBus()

    asyncio.run(backend._setup_gatt())

    exported = backend._bus.exported
    notify_paths = [
        f"{backend._app_path}/service0/char1",  # indoor bike data
        f"{backend._app_path}/service0/char2",  # fitness machine status
        f"{backend._app_path}/service0/char3",  # control point (indicate)
        f"{backend._app_path}/service1/char0",  # heart rate measurement
        f"{backend._app_path}/service2/char1",  # cycling power measurement
    ]
    for path in notify_paths:
        descriptor = exported[f"{path}/desc0"]
        assert descriptor.uuid == "00002902-0000-1000-8000-00805f9b34fb"
        assert descriptor.Characteristic() == path
        assert descriptor.ReadValue({}) == [0x00, 0x00]


def test_characteristic_descriptor_tracks_client_subscription_value():
    descriptor = ble_ftms.CCCD("/app0/service0/char1/desc0", "/app0/service0/char1")
    descriptor.WriteValue([0x01, 0x00], {})
    assert descriptor.Value() == [0x01, 0x00]
    assert descriptor.UUID() == "00002902-0000-1000-8000-00805f9b34fb"


def test_advertisement_registration_reaches_bluez_manager():
    backend = ble_ftms.BLEFTMSBackend(FakeBridge(), Config())
    backend._bus = FakeBus()

    asyncio.run(backend._register_advertisement())

    assert backend._advertisement is not None
    assert backend._advertisement.device_name == "DAUM-8008-TRS"
    assert ("adv-register", backend._adv_path, {}) in backend._bus.calls


def test_adapter_power_query_uses_dbus_proxy():
    backend = ble_ftms.BLEFTMSBackend(FakeBridge(), Config())
    backend._bus = FakeBus()
    assert asyncio.run(backend._adapter_is_powered()) is True


def test_adapter_repower_reregisters_gatt_and_advertisement():
    backend = ble_ftms.BLEFTMSBackend(FakeBridge(), Config())
    backend._bus = FakeBus()

    assert asyncio.run(backend._check_adapter_state(False)) is True

    assert ("gatt-register", backend._app_path, {}) in backend._bus.calls
    assert ("adv-register", backend._adv_path, {}) in backend._bus.calls


def test_adapter_powered_off_is_reported():
    backend = ble_ftms.BLEFTMSBackend(FakeBridge(), Config())
    backend._bus = FakeBus(powered=False)

    assert asyncio.run(backend._check_adapter_state(True)) is False
    assert backend._bus.calls == []


def test_start_returns_false_without_dbus(monkeypatch):
    monkeypatch.setattr(ble_ftms, "DBUS_AVAILABLE", False)
    backend = ble_ftms.BLEFTMSBackend(FakeBridge(), Config())
    assert asyncio.run(backend.start()) is False
    assert backend._running is False

