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

    assert ble_ftms.INDOOR_BIKE_DATA_FLAGS == 0x0854
    flags, speed, cadence = struct.unpack_from("<HHH", packet, 0)
    distance = int.from_bytes(packet[6:9], "little")
    power, elapsed = struct.unpack_from("<hH", packet, 9)

    assert len(packet) == 13
    # Fields are ordered by flag bit: speed (0), cadence (2), distance (4),
    # power (6), elapsed time (11).
    assert flags == 0x0854
    assert speed == 3240            # 0.01 km/h
    assert cadence == 180           # 0.5 rpm
    assert power == 210             # W
    assert distance == 1234         # m
    assert elapsed == 125           # s


def test_indoor_bike_data_handles_missing_values():
    packet = ble_ftms.build_indoor_bike_data(DaumState())
    flags, speed, cadence = struct.unpack_from("<HHH", packet, 0)
    (power,) = struct.unpack_from("<h", packet, 9)
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


def test_gatt_setup_leaves_cccd_to_bluez():
    """BlueZ adds the CCCD for notify/indicate characteristics itself.

    Exporting our own 0x2902 descriptor made BlueZ insert a second CCCD after
    the auto-created one; writes to that duplicate never enabled notifications.
    """
    backend = ble_ftms.BLEFTMSBackend(FakeBridge(), Config())
    backend._bus = FakeBus()

    asyncio.run(backend._setup_gatt())

    descriptors = [
        path
        for path, obj in backend._bus.exported.items()
        if getattr(obj, "name", None) == "org.bluez.GattDescriptor1"
    ]
    assert descriptors == []
    assert not any(path.endswith("/desc0") for path in backend._bus.exported)


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



def _notify_characteristic(bus=None, notifying=True):
    char = ble_ftms.Characteristic(
        "/app0/service0/char1",
        ble_ftms.INDOOR_BIKE_DATA_UUID,
        ["notify"],
        "/app0/service0",
        bus=bus,
        backend=None,
    )
    char.notifying = notifying
    return char


def test_send_notification_emits_raw_bytes_value():
    """BlueZ wraps the Value in a Variant itself, so we must pass bytes.

    Passing ``Variant("ay", ...)`` here used to raise a signature mismatch for
    every notification, which silently stopped all data reaching clients.
    """
    char = _notify_characteristic(bus=object())
    emitted = {}

    def fake_emit(changed_properties, invalidated_properties=None):
        emitted.update(changed_properties)

    char.emit_properties_changed = fake_emit

    assert asyncio.run(char.send_notification(b"\x01\x02")) is True
    assert emitted["Value"] == b"\x01\x02"
    assert isinstance(emitted["Value"], bytes)
    assert char.notifications_sent == 1
    assert char.last_error is None


def test_send_notification_skips_when_client_not_subscribed():
    char = _notify_characteristic(bus=object(), notifying=False)
    char.indicating = False

    assert asyncio.run(char.send_notification(b"\x01")) is False
    assert char.notifications_sent == 0


def test_send_notification_records_errors():
    char = _notify_characteristic(bus=object())

    def boom(_changed, _invalidated=None):
        raise RuntimeError("dbus gone")

    char.emit_properties_changed = boom

    assert asyncio.run(char.send_notification(b"\x01")) is False
    assert char.notifications_sent == 0
    assert "dbus gone" in char.last_error


def test_diagnostics_reports_subscription_state():
    backend = ble_ftms.BLEFTMSBackend(FakeBridge(), Config())
    fake = SimpleNamespace(
        uuid=ble_ftms.INDOOR_BIKE_DATA_UUID,
        notifying=True,
        indicating=False,
        notifications_sent=7,
        last_error=None,
    )
    backend._indoor_bike_data_char = fake

    info = backend.diagnostics()

    assert info["control_point_enabled"] is False
    assert info["characteristics"]["indoor_bike_data"] == {
        "uuid": ble_ftms.INDOOR_BIKE_DATA_UUID,
        "notifying": True,
        "indicating": False,
        "notifications_sent": 7,
        "last_error": None,
    }
    assert info["characteristics"]["heart_rate"] is None
