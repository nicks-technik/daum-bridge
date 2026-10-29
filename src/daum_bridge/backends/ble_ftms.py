"""BLE FTMS peripheral backend for MyWhoosh (Linux/BlueZ via dbus-next).
Implements full FTMS GATT server with advertising, characteristics, notifications, and control point.
"""

from __future__ import annotations

import asyncio
import logging
import struct
import time
from typing import Optional

from ..numbers import as_float, clamp

log = logging.getLogger(__name__)

try:
    from dbus_next.aio import MessageBus
    from dbus_next.service import ServiceInterface, method, dbus_property
    from dbus_next import Variant, BusType
    DBUS_AVAILABLE = True
except Exception as e:
    log.debug("dbus-next not available: %s", e)
    DBUS_AVAILABLE = False

    # Import-time fallbacks so the module (and its packet builders) can be used
    # on platforms without dbus-next. The backend refuses to start in that case.
    class ServiceInterface:  # type: ignore[no-redef]
        def __init__(self, name: str = ""):
            self.name = name

    def method(*args, **kwargs):  # type: ignore[no-redef]
        def decorator(func):
            return func
        return decorator

    def dbus_property(*args, **kwargs):  # type: ignore[no-redef]
        def decorator(func):
            return func
        return decorator

    class Variant:  # type: ignore[no-redef]
        def __init__(self, signature, value):
            self.signature = signature
            self.value = value

    class BusType:  # type: ignore[no-redef]
        SYSTEM = "system"

    class MessageBus:  # type: ignore[no-redef]
        @staticmethod
        async def connect(*args, **kwargs):
            raise RuntimeError("dbus-next is not available")



# FTMS UUIDs (standard)
FTMS_UUID = '00001826-0000-1000-8000-00805f9b34fb'
INDOOR_BIKE_DATA_UUID = '00002ad2-0000-1000-8000-00805f9b34fb'
FITNESS_MACHINE_FEATURE_UUID = '00002ad8-0000-1000-8000-00805f9b34fb'
FITNESS_MACHINE_CONTROL_POINT_UUID = '00002ad9-0000-1000-8000-00805f9b34fb'
FITNESS_MACHINE_STATUS_UUID = '00002ad3-0000-1000-8000-00805f9b34fb'
SUPPORTED_POWER_RANGE_UUID = '00002ad6-0000-1000-8000-00805f9b34fb'
SUPPORTED_RESISTANCE_LEVEL_RANGE_UUID = '00002ad4-0000-1000-8000-00805f9b34fb'
DEVICE_INFORMATION_SERVICE_UUID = '0000180a-0000-1000-8000-00805f9b34fb'
MANUFACTURER_NAME_UUID = '00002a29-0000-1000-8000-00805f9b34fb'
MODEL_NUMBER_UUID = '00002a24-0000-1000-8000-00805f9b34fb'
HEART_RATE_SERVICE_UUID = '0000180d-0000-1000-8000-00805f9b34fb'
HEART_RATE_MEASUREMENT_UUID = '00002a37-0000-1000-8000-00805f9b34fb'
BODY_SENSOR_LOCATION_UUID = '00002a38-0000-1000-8000-00805f9b34fb'
CYCLING_POWER_SERVICE_UUID = '00001818-0000-1000-8000-00805f9b34fb'
CYCLING_POWER_MEASUREMENT_UUID = '00002a63-0000-1000-8000-00805f9b34fb'
CYCLING_POWER_FEATURE_UUID = '00002a65-0000-1000-8000-00805f9b34fb'
GATT_CHARACTERISTIC_USER_DESC_UUID = '00002901-0000-1000-8000-00805f9b34fb'
GATT_CLIENT_CHAR_CFG_UUID = '00002902-0000-1000-8000-00805f9b34fb'


# Fitness Machine Features (0x2AD8, first 32-bit field): cadence, total
# distance, heart rate, elapsed time and power are provided.
FEATURE_FLAGS = (1 << 1) | (1 << 2) | (1 << 10) | (1 << 12) | (1 << 14)
# Target Setting Features (second 32-bit field): resistance, target power and
# indoor bike simulation parameters (grade) are supported.
TARGET_FEATURE_FLAGS = (1 << 2) | (1 << 3) | (1 << 13)

# Indoor Bike Data flags. The order of the fields below follows the bit order,
# as required by the FTMS specification: instantaneous speed, instantaneous
# cadence, instantaneous power, total distance, elapsed time.
INDOOR_BIKE_DATA_FLAGS = (1 << 2) | (1 << 4) | (1 << 6) | (1 << 9) | (1 << 12)

#: Cycling Power Measurement flag: crank revolution data present.
CYCLING_POWER_CRANK_FLAG = 0x0020

# Fitness Machine Control Point opcodes.
OP_REQUEST_CONTROL = 0x00
OP_RESET = 0x01
OP_SET_RESISTANCE = 0x04
OP_SET_TARGET_POWER = 0x05
OP_START_RESUME = 0x07
OP_STOP_PAUSE = 0x08
OP_SET_SIMULATION = 0x11

# Control Point response codes (the response always starts with 0x80).
CP_SUCCESS = 0x01
CP_NOT_SUPPORTED = 0x02
CP_INVALID_PARAMETER = 0x03
CP_OPERATION_FAILED = 0x04
CP_CONTROL_NOT_PERMITTED = 0x05

# Fitness Machine Status opcodes.
STATUS_RESET = 0x01
STATUS_STOPPED_BY_USER = 0x02
STATUS_STARTED_BY_USER = 0x04
STATUS_RESISTANCE_CHANGED = 0x07
STATUS_TARGET_POWER_CHANGED = 0x08
STATUS_SIMULATION_CHANGED = 0x12


def build_indoor_bike_data(state) -> bytes:
    """Encode an FTMS Indoor Bike Data notification for ``state``.

    Fields (in this order, matching :data:`INDOOR_BIKE_DATA_FLAGS`):
    instantaneous speed (0.01 km/h), instantaneous cadence (0.5 rpm),
    instantaneous power (W), total distance (m), elapsed time (s).
    """
    speed = int(clamp(as_float(getattr(state, "speed", 0)) * 100.0, 0, 0xFFFF))
    cadence = int(clamp(as_float(getattr(state, "cadence", 0)) * 2.0, 0, 0xFFFF))
    power = int(clamp(as_float(getattr(state, "power", 0)), -32768, 32767))
    distance = int(
        clamp(as_float(getattr(state, "total_distance", 0)) * 1000.0, 0, 0xFFFFFF)
    )
    elapsed = int(clamp(as_float(getattr(state, "elapsed_time", 0)), 0, 0xFFFF))
    return (
        struct.pack("<HHHh", INDOOR_BIKE_DATA_FLAGS, speed, cadence, power)
        + distance.to_bytes(3, "little")
        + struct.pack("<H", elapsed)
    )


def build_cycling_power(state, now: Optional[float] = None) -> bytes:
    """Encode a Cycling Power Measurement notification (power + crank data)."""
    power = int(clamp(as_float(getattr(state, "power", 0)), -32768, 32767))
    cadence = max(0.0, as_float(getattr(state, "cadence", 0)))
    now = time.time() if now is None else float(now)
    if cadence > 0:
        revolutions = int(now * cadence / 60.0) & 0xFFFF
        event_time = int((now % 1.0) * 1024.0 * 60.0 / cadence) & 0xFFFF
    else:
        revolutions = event_time = 0
    return struct.pack(
        "<HhHH", CYCLING_POWER_CRANK_FLAG, power, revolutions, event_time
    )



class Advertisement(ServiceInterface):
    def __init__(self, object_path, device_name):
        super().__init__('org.bluez.LEAdvertisement1')
        self.path = object_path
        self.device_name = device_name

    @dbus_property()
    def Type(self) -> 's':
        return 'peripheral'

    @dbus_property()
    def LocalName(self) -> 's':
        return self.device_name

    @dbus_property()
    def ServiceUUIDs(self) -> 'as':
        # Advertise the services clients need to discover in one go.
        return [FTMS_UUID, HEART_RATE_SERVICE_UUID, CYCLING_POWER_SERVICE_UUID]

    @dbus_property()
    def Includes(self) -> 'as':
        return ['tx-power']

    @method()
    def Release(self):
        log.debug('Advertisement released')


class Application(ServiceInterface):
    def __init__(self, object_path):
        super().__init__('org.bluez.GattApplication1')
        self.path = object_path


class Service(ServiceInterface):
    def __init__(self, object_path, uuid, primary=True):
        super().__init__('org.bluez.GattService1')
        self.path = object_path
        self.uuid = uuid
        self.primary = primary

    @dbus_property()
    def UUID(self) -> 's':
        return self.uuid

    @dbus_property()
    def Primary(self) -> 'b':
        return self.primary

    @dbus_property()
    def Characteristics(self) -> 'ao':
        return []


class Characteristic(ServiceInterface):
    def __init__(self, object_path, uuid, flags, service_path, bus=None, backend=None):
        super().__init__('org.bluez.GattCharacteristic1')
        self.path = object_path
        self.uuid = uuid
        self.flags = flags
        self.service_path = service_path
        self.bus = bus
        self._backend = backend
        self.value = []
        self.notifying = False
        self.indicating = False
        self._notify_callback = None

    @dbus_property()
    def UUID(self) -> 's':
        return self.uuid

    @dbus_property()
    def Service(self) -> 'o':
        return self.service_path

    @dbus_property()
    def Value(self) -> 'ay':
        return self.value

    @dbus_property()
    def Flags(self) -> 'as':
        return self.flags

    @dbus_property()
    def Notifying(self) -> 'b':
        return self.notifying

    @method()
    def StartNotify(self):
        log.info(f"StartNotify on {self.uuid}")
        self.notifying = True
        try:
            if hasattr(self, '_backend') and self._backend:
                if hasattr(self._backend.bridge, '_app_connected'):
                    self._backend.bridge._app_connected = True
        except Exception:
            pass

    @method()
    def StopNotify(self):
        log.info(f"StopNotify on {self.uuid}")
        self.notifying = False

    @method()
    def StartIndicate(self):
        log.info(f"StartIndicate on {self.uuid}")
        self.indicating = True

    @method()
    def StopIndicate(self):
        log.info(f"StopIndicate on {self.uuid}")
        self.indicating = False

    @method()
    def ReadValue(self, options: 'a{sv}') -> 'ay':
        log.debug(f"ReadValue {self.uuid}")
        return self.value

    @method()
    def WriteValue(self, value: 'ay', options: 'a{sv}'):
        self.value = value
        log.debug(f"WriteValue {self.uuid}: {bytes(value).hex()}")
        if self._notify_callback:
            try:
                self._notify_callback(bytes(value))
            except Exception as e:
                log.debug(f"Write callback error: {e}")

    async def send_notification(self, data: bytes):
        try:
            if not (self.notifying or self.indicating) or not self.bus:
                return False
            self.value = list(data)
            self.emit_properties_changed({'Value': Variant('ay', self.value)})
            return True
        except Exception as e:
            log.debug(f"send_notification error: {e}")
            return False


class CCCD(ServiceInterface):
    """Client Characteristic Configuration Descriptor (0x2902).

    BlueZ expects a CCCD for every notify/indicate characteristic so a client
    can enable notifications. The value is only used for reads; the actual
    subscription state is tracked by :class:`Characteristic`.
    """

    def __init__(self, object_path: str, characteristic_path: str):
        super().__init__('org.bluez.GattDescriptor1')
        self.path = object_path
        self.uuid = '00002902-0000-1000-8000-00805f9b34fb'
        self.characteristic_path = characteristic_path
        self.value = [0x00, 0x00]

    @dbus_property()
    def UUID(self) -> 's':
        return self.uuid

    @dbus_property()
    def Characteristic(self) -> 'o':
        return self.characteristic_path

    @dbus_property()
    def Value(self) -> 'ay':
        return self.value

    @method()
    def ReadValue(self, options: 'a{sv}') -> 'ay':
        return self.value

    @method()
    def WriteValue(self, value: 'ay', options: 'a{sv}'):
        self.value = value


class BLEFTMSBackend:
    def __init__(self, bridge, config):
        self.bridge = bridge
        self.config = config
        self._running = False
        self._bus = None
        self._advertisement = None
        self._app = None
        self._notify_task = None
        self._adv_path = '/org/bluez/daum/advertisement0'
        self._app_path = '/org/bluez/daum/app0'
        self._adapter = getattr(getattr(config, 'ble', None), 'adapter', 'hci0')
        self._device_name = getattr(getattr(config, 'ble', None), 'device_name', 'DAUM-8008-TRS')
        self._objects = []
        self._indoor_bike_data_char = None
        self._control_point_char = None
        self._control_point_enabled = False
        self._fitness_machine_status_char = None
        self._last_cp_req = None
        self._heart_rate_char = None
        self._cycling_power_char = None
        self._clients_connected = 0
        self.virtual_shifting_enabled = True
        self._adapter_watch_task = None

    async def start(self) -> bool:
        log.info("Starting BLE FTMS backend on %s as %s", self._adapter, self._device_name)
        self._running = True
        if self.bridge:
            if hasattr(self.bridge, '_app_connected'):
                self.bridge._app_connected = False

        if not DBUS_AVAILABLE:
            log.warning("dbus-next not available; BLE FTMS peripheral cannot run on this platform")
            log.warning("BLE FTMS requires Linux, BlueZ and Python 3.10-3.12 (dbus-next)")
            self._running = False
            return False

        try:
            self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            log.info("Connected to system D-Bus")
        except Exception as e:
            log.error("Failed to connect to system D-Bus: %s", e)
            log.warning("BLE FTMS peripheral requires BlueZ on Linux with system D-Bus access")
            self._running = False
            return False

        try:
            await self._setup_gatt()
            await self._register_advertisement()
            log.info("FTMS GATT server and advertising registered")
        except Exception as e:
            log.error("Failed to setup FTMS GATT: %s", e)
            log.warning("Falling back to advertising only")

        try:
            self._notify_task = asyncio.create_task(self._notify_loop())
            self._adapter_watch_task = asyncio.create_task(self._watch_adapter())
            while self._running:
                await asyncio.sleep(1)
        except Exception as e:
            log.error("BLE FTMS backend error: %s", e)
        finally:
            await self._cleanup()
            if self._notify_task:
                self._notify_task.cancel()
                try:
                    await self._notify_task
                except Exception:
                    pass
            if self._adapter_watch_task:
                self._adapter_watch_task.cancel()
                try:
                    await self._adapter_watch_task
                except Exception:
                    pass
            if self._bus:
                try:
                    self._bus.disconnect()
                except Exception:
                    pass
        return True

    async def _watch_adapter(self):
        was_powered = True
        while self._running:
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            if not self._bus or not DBUS_AVAILABLE:
                continue
            was_powered = await self._check_adapter_state(was_powered)

    async def _check_adapter_state(self, was_powered: bool) -> bool:
        """Poll adapter power and re-register GATT after a power cycle."""
        try:
            powered = await self._adapter_is_powered()
        except Exception as exc:
            log.debug("Could not query adapter power: %s", exc)
            return was_powered
        if not powered:
            if was_powered:
                log.warning("Bluetooth adapter %s is powered off", self._adapter)
            return False
        if not was_powered and self._bus is not None:
            # After a power cycle BlueZ drops the advertisement and possibly
            # the GATT application; re-register both (errors are harmless if
            # BlueZ still has them).
            log.info("Bluetooth adapter %s is powered on again, re-registering GATT", self._adapter)
            try:
                await self._register_gatt_application()
            except Exception as e:
                log.debug("GATT application re-register failed: %s", e)
            try:
                await self._register_advertisement()
            except Exception as e:
                log.debug("Advertisement re-register failed: %s", e)
        return True

    async def _adapter_is_powered(self) -> bool:
        introspection = await self._bus.introspect('org.bluez', f'/org/bluez/{self._adapter}')
        proxy_obj = self._bus.get_proxy_object('org.bluez', f'/org/bluez/{self._adapter}', introspection)
        adapter = proxy_obj.get_interface('org.bluez.Adapter1')
        return bool(await adapter.get_powered())

    async def _setup_gatt(self):
        # Create application
        self._app = Application(self._app_path)
        self._bus.export(self._app_path, self._app)
        
        # Create FTMS service
        ftms_service_path = f'{self._app_path}/service0'
        ftms_service = Service(ftms_service_path, FTMS_UUID, primary=True)
        self._bus.export(ftms_service_path, ftms_service)
        self._objects.append(ftms_service)
        
        # Fitness Machine Feature (read)
        feature_path = f'{ftms_service_path}/char0'
        feature_char = Characteristic(feature_path, FITNESS_MACHINE_FEATURE_UUID, ['read'], ftms_service_path, bus=self._bus, backend=self)
        features = struct.pack('<II', FEATURE_FLAGS, TARGET_FEATURE_FLAGS)
        feature_char.value = list(features)
        self._bus.export(feature_path, feature_char)
        self._objects.append(feature_char)
        
        # Indoor Bike Data (notify)
        ibd_path = f'{ftms_service_path}/char1'
        ibd_char = Characteristic(ibd_path, INDOOR_BIKE_DATA_UUID, ['notify'], ftms_service_path, bus=self._bus, backend=self)
        self._indoor_bike_data_char = ibd_char
        self._bus.export(ibd_path, ibd_char)
        self._objects.append(ibd_char)
        self._export_cccd(ibd_path)

        # Fitness Machine Status (notify)
        status_path = f'{ftms_service_path}/char2'
        status_char = Characteristic(status_path, FITNESS_MACHINE_STATUS_UUID, ['notify'], ftms_service_path, bus=self._bus, backend=self)
        self._fitness_machine_status_char = status_char
        self._bus.export(status_path, status_char)
        self._objects.append(status_char)
        self._export_cccd(status_path)

        # Fitness Machine Control Point (write, indicate)
        cp_path = f'{ftms_service_path}/char3'
        cp_char = Characteristic(cp_path, FITNESS_MACHINE_CONTROL_POINT_UUID, ['write', 'indicate'], ftms_service_path, bus=self._bus, backend=self)
        cp_char._notify_callback = self._handle_control_point
        self._control_point_char = cp_char
        self._bus.export(cp_path, cp_char)
        self._objects.append(cp_char)
        self._export_cccd(cp_path)
        
        # Supported Power Range (0x2AD6)
        try:
            spr_path = f'{ftms_service_path}/char4'
            spr_char = Characteristic(spr_path, SUPPORTED_POWER_RANGE_UUID, ['read'], ftms_service_path, bus=self._bus, backend=self)
            spr_char.value = list(struct.pack('<hhh', 10, 800, 1))
            self._bus.export(spr_path, spr_char)
            self._objects.append(spr_char)
        except Exception as e:
            log.debug(f"SPR setup error: {e}")
        
        # Supported Resistance Level Range (0x2AD4)
        try:
            srl_path = f'{ftms_service_path}/char5'
            srl_char = Characteristic(srl_path, SUPPORTED_RESISTANCE_LEVEL_RANGE_UUID, ['read'], ftms_service_path, bus=self._bus, backend=self)
            srl_char.value = list(struct.pack('<hhh', 0, 1000, 1))
            self._bus.export(srl_path, srl_char)
            self._objects.append(srl_char)
        except Exception as e:
            log.debug(f"SRL setup error: {e}")
        
        # Heart Rate Service
        try:
            hrs_service_path = f'{self._app_path}/service1'
            hrs_service = Service(hrs_service_path, HEART_RATE_SERVICE_UUID, primary=True)
            self._bus.export(hrs_service_path, hrs_service)
            self._objects.append(hrs_service)
            hrm_path = f'{hrs_service_path}/char0'
            hrm_char = Characteristic(hrm_path, HEART_RATE_MEASUREMENT_UUID, ['notify'], hrs_service_path, bus=self._bus, backend=self)
            self._heart_rate_char = hrm_char
            self._bus.export(hrm_path, hrm_char)
            self._objects.append(hrm_char)
            self._export_cccd(hrm_path)
            bsl_path = f'{hrs_service_path}/char1'
            bsl_char = Characteristic(bsl_path, BODY_SENSOR_LOCATION_UUID, ['read'], hrs_service_path, bus=self._bus, backend=self)
            bsl_char.value = [0x01]
            self._bus.export(bsl_path, bsl_char)
            self._objects.append(bsl_char)
        except Exception as e:
            log.debug(f"HRS setup error: {e}")
        
        # Cycling Power Service
        try:
            cps_service_path = f'{self._app_path}/service2'
            cps_service = Service(cps_service_path, CYCLING_POWER_SERVICE_UUID, primary=True)
            self._bus.export(cps_service_path, cps_service)
            self._objects.append(cps_service)
            cpf_path = f'{cps_service_path}/char0'
            cpf_char = Characteristic(cpf_path, CYCLING_POWER_FEATURE_UUID, ['read'], cps_service_path, bus=self._bus, backend=self)
            cpf_char.value = list(struct.pack('<I', 0x00000008))  # crank revolution data not required
            self._bus.export(cpf_path, cpf_char)
            self._objects.append(cpf_char)
            cpm_path = f'{cps_service_path}/char1'
            cpm_char = Characteristic(cpm_path, CYCLING_POWER_MEASUREMENT_UUID, ['notify'], cps_service_path, bus=self._bus, backend=self)
            self._cycling_power_char = cpm_char
            self._bus.export(cpm_path, cpm_char)
            self._objects.append(cpm_char)
            self._export_cccd(cpm_path)
        except Exception as e:
            log.debug(f"CPS setup error: {e}")
        
        # Device Information Service
        try:
            dis_service_path = f'{self._app_path}/service3'
            dis_service = Service(dis_service_path, DEVICE_INFORMATION_SERVICE_UUID, primary=True)
            self._bus.export(dis_service_path, dis_service)
            self._objects.append(dis_service)
            mn_path = f'{dis_service_path}/char0'
            mn_char = Characteristic(mn_path, MANUFACTURER_NAME_UUID, ['read'], dis_service_path, bus=self._bus, backend=self)
            mn_char.value = list("Daum".encode('utf-8'))
            self._bus.export(mn_path, mn_char)
            self._objects.append(mn_char)
            mdl_path = f'{dis_service_path}/char1'
            mdl_char = Characteristic(mdl_path, MODEL_NUMBER_UUID, ['read'], dis_service_path, bus=self._bus, backend=self)
            mdl_char.value = list("8008-TRS".encode('utf-8'))
            self._bus.export(mdl_path, mdl_char)
            self._objects.append(mdl_char)
        except Exception as e:
            log.debug(f"DIS setup error: {e}")
        
        # Register application
        await self._register_gatt_application()

    def _export_cccd(self, characteristic_path: str) -> None:
        """Export the CCCD descriptor (0x2902) for a notify/indicate characteristic."""
        cccd_path = f'{characteristic_path}/desc0'
        descriptor = CCCD(cccd_path, characteristic_path)
        try:
            self._bus.export(cccd_path, descriptor)
        except Exception as e:
            log.debug("CCCD export error for %s: %s", characteristic_path, e)
            return
        self._objects.append(descriptor)

    async def _register_gatt_application(self):
        try:
            introspection = await self._bus.introspect('org.bluez', f'/org/bluez/{self._adapter}')
            proxy_obj = self._bus.get_proxy_object('org.bluez', f'/org/bluez/{self._adapter}', introspection)
            gatt_manager = proxy_obj.get_interface('org.bluez.GattManager1')
            await gatt_manager.call_register_application(self._app_path, {})
            log.info("GATT application registered")
        except Exception as e:
            log.warning(f"Failed to register GATT application: {e}")
            raise

    async def _register_advertisement(self):
        if self._advertisement is None:
            self._advertisement = Advertisement(self._adv_path, self._device_name)
            self._bus.export(self._adv_path, self._advertisement)
        try:
            introspection = await self._bus.introspect('org.bluez', f'/org/bluez/{self._adapter}')
            proxy_obj = self._bus.get_proxy_object('org.bluez', f'/org/bluez/{self._adapter}', introspection)
            adv_manager = proxy_obj.get_interface('org.bluez.LEAdvertisingManager1')
            await adv_manager.call_register_advertisement(self._adv_path, {})
            log.info("LE Advertisement registered")
        except Exception as e:
            log.debug("Advertisement registration details: %s", e)
            raise

    def _handle_control_point(self, data: bytes):
        """Handle a Fitness Machine Control Point write.

        Opcodes implemented: Request Control (0x00), Reset (0x01),
        Set Resistance Level (0x04), Set Target Power (0x05),
        Start/Resume (0x07), Stop/Pause (0x08) and Set Indoor Bike Simulation
        Parameters (0x11). Resistance and grade are translated to Daum gears
        by :class:`~daum_bridge.bridge.DaumBridge`.
        """
        try:
            raw = bytes(data or b"")
            if not raw:
                return
            op_code = raw[0]
            self._last_cp_req = op_code
            log.info("Control Point op: 0x%02X data=%s", op_code, raw.hex())
            if self.bridge and hasattr(self.bridge, '_app_connected'):
                self.bridge._app_connected = True

            # Request Control (0x00)
            if op_code == OP_REQUEST_CONTROL:
                self._control_point_enabled = True
                if self.bridge and hasattr(self.bridge, '_erg_control_granted'):
                    self.bridge._erg_control_granted = True
                if self.bridge and hasattr(self.bridge, '_app_connected_time'):
                    self.bridge._app_connected_time = time.time()
                self._send_cp_response(OP_REQUEST_CONTROL, CP_SUCCESS)
                return

            # Reset (0x01)
            if op_code == OP_RESET:
                self._control_point_enabled = False
                if self.bridge and hasattr(self.bridge, '_erg_control_granted'):
                    self.bridge._erg_control_granted = False
                if self.bridge and hasattr(self.bridge, 'set_target_watt'):
                    try:
                        self.bridge.set_target_watt(0)
                    except Exception:
                        pass
                self._send_cp_response(OP_RESET, CP_SUCCESS)
                self._send_fitness_machine_status(STATUS_RESET)
                return

            # Start or Resume (0x07)
            if op_code == OP_START_RESUME:
                if not self._require_control(op_code):
                    return
                self._send_cp_response(OP_START_RESUME, CP_SUCCESS)
                self._send_fitness_machine_status(STATUS_STARTED_BY_USER)
                return

            # Stop or Pause (0x08)
            if op_code == OP_STOP_PAUSE:
                if not self._require_control(op_code):
                    return
                self._send_cp_response(OP_STOP_PAUSE, CP_SUCCESS)
                self._send_fitness_machine_status(STATUS_STOPPED_BY_USER)
                return

            # Set Target Power (0x05), sint16 in watts
            if op_code == OP_SET_TARGET_POWER:
                if not self._require_control(op_code):
                    return
                if len(raw) < 3:
                    self._send_cp_response(op_code, CP_INVALID_PARAMETER, 0x01)
                    return
                power = struct.unpack_from('<h', raw, 1)[0]
                power_clamped = max(10, min(800, int(power)))
                log.info("FTMS set target power: %sW (clamped to %sW)", power, power_clamped)
                if not hasattr(self.bridge, "set_target_watt"):
                    self._send_cp_response(op_code, CP_NOT_SUPPORTED)
                    return
                try:
                    self.bridge.set_target_watt(power_clamped)
                    if hasattr(self.bridge, '_erg_control_granted'):
                        self.bridge._erg_control_granted = True
                except Exception as e:
                    log.warning("Error setting target power: %s", e)
                    self._send_cp_response(op_code, CP_OPERATION_FAILED)
                    return
                self._send_cp_response(op_code, CP_SUCCESS)
                self._send_fitness_machine_status(STATUS_TARGET_POWER_CHANGED)
                return

            # Set Resistance Level (0x04), sint16 in 0.1 % units
            if op_code == OP_SET_RESISTANCE:
                if not self._require_control(op_code):
                    return
                if len(raw) < 3:
                    self._send_cp_response(op_code, CP_INVALID_PARAMETER, 0x01)
                    return
                (raw_level,) = struct.unpack_from('<h', raw, 1)
                percent = max(0.0, min(100.0, raw_level / 10.0))
                if not hasattr(self.bridge, "set_resistance_percent"):
                    self._send_cp_response(op_code, CP_NOT_SUPPORTED)
                    return
                log.info("FTMS set resistance: %.1f %%", percent)
                try:
                    self.bridge.set_resistance_percent(percent)
                except Exception as e:
                    log.warning("Error setting resistance: %s", e)
                    self._send_cp_response(op_code, CP_OPERATION_FAILED)
                    return
                self._send_cp_response(op_code, CP_SUCCESS)
                self._send_fitness_machine_status(STATUS_RESISTANCE_CHANGED)
                return

            # Set Indoor Bike Simulation Parameters (0x11)
            #   wind speed (0.001 m/s), grade (0.01 %), crr, wind resistance
            if op_code == OP_SET_SIMULATION:
                if not self._require_control(op_code):
                    return
                if len(raw) < 7:
                    self._send_cp_response(op_code, CP_INVALID_PARAMETER, 0x01)
                    return
                wind_speed, grade_raw, _crr, _wind_res = struct.unpack_from('<hhBB', raw, 1)
                grade = max(-25.0, min(25.0, grade_raw / 100.0))
                if not hasattr(self.bridge, "set_grade_percent"):
                    self._send_cp_response(op_code, CP_NOT_SUPPORTED)
                    return
                log.info(
                    "FTMS simulation: grade %.2f %%, wind %.3f m/s (wind ignored)",
                    grade,
                    wind_speed / 1000.0,
                )
                try:
                    self.bridge.set_grade_percent(grade)
                except Exception as e:
                    log.warning("Error setting simulation parameters: %s", e)
                    self._send_cp_response(op_code, CP_OPERATION_FAILED)
                    return
                self._send_cp_response(op_code, CP_SUCCESS)
                self._send_fitness_machine_status(STATUS_SIMULATION_CHANGED)
                return

            self._send_cp_response(op_code, CP_NOT_SUPPORTED)
        except Exception as e:
            log.error("Control point error: %s", e)

    def _require_control(self, op_code: int) -> bool:
        if self._control_point_enabled:
            return True
        self._send_cp_response(op_code, CP_CONTROL_NOT_PERMITTED)
        return False

    def _notify_char(self, char, packet: bytes):
        """Store a notification value and emit it when a loop is running."""
        if char is None:
            return
        try:
            char.value = list(packet)
        except Exception:
            pass
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        try:
            loop.create_task(char.send_notification(bytes(packet)))
        except Exception as e:
            log.debug("Notification scheduling error: %s", e)

    def _send_cp_response(self, request_op, result_code, error_code=0x00):
        resp = bytearray([0x80, request_op & 0xFF, result_code & 0xFF])
        if result_code == CP_INVALID_PARAMETER:
            resp.append(error_code or 0x01)
        self._notify_char(self._control_point_char, bytes(resp))
        log.debug("CP response: %s", bytes(resp).hex())

    def _send_fitness_machine_status(self, status: int, data: bytes = b''):
        packet = bytes([status & 0xFF]) + bytes(data)
        self._notify_char(self._fitness_machine_status_char, packet)
        log.debug("FTMS status: 0x%02X", status)

    async def _notify_loop(self):
        while self._running:
            try:
                if self.bridge and hasattr(self.bridge, 'state'):
                    state = self.bridge.state
                    # Indoor Bike Data
                    if self._indoor_bike_data_char:
                        packet = build_indoor_bike_data(state)
                        if self._indoor_bike_data_char.notifying or getattr(self._indoor_bike_data_char, 'indicating', False):
                            try:
                                await self._indoor_bike_data_char.send_notification(packet)
                            except Exception:
                                pass
                        else:
                            self._indoor_bike_data_char.value = list(packet)
                    # Heart Rate
                    if self._heart_rate_char and hasattr(state, 'heart_rate') and state.heart_rate and state.heart_rate > 0:
                        try:
                            hr = int(state.heart_rate)
                            if 40 <= hr <= 220:
                                hr_packet = bytes([0x00, hr & 0xFF])
                                if self._heart_rate_char.notifying or getattr(self._heart_rate_char, 'indicating', False):
                                    await self._heart_rate_char.send_notification(hr_packet)
                                else:
                                    self._heart_rate_char.value = list(hr_packet)
                        except Exception:
                            pass
                    # Cycling Power (with crank revolution data)
                    if self._cycling_power_char:
                        cp_packet = build_cycling_power(state)
                        if self._cycling_power_char.notifying or getattr(self._cycling_power_char, 'indicating', False):
                            await self._cycling_power_char.send_notification(cp_packet)
                        else:
                            self._cycling_power_char.value = list(cp_packet)
                    log.debug("FTMS IBP: speed=%s cadence=%s dist=%s power=%s hr=%s", getattr(state, 'speed', None), getattr(state, 'cadence', None), getattr(state, 'total_distance', None), getattr(state, 'power', None), getattr(state, 'heart_rate', None))
            except Exception as e:
                log.debug("Notify loop error: %s", e)
            await asyncio.sleep(0.25)

    async def _cleanup(self):
        try:
            if self._bus:
                try:
                    introspection = await self._bus.introspect('org.bluez', f'/org/bluez/{self._adapter}')
                    proxy_obj = self._bus.get_proxy_object('org.bluez', f'/org/bluez/{self._adapter}', introspection)
                    adv_manager = proxy_obj.get_interface('org.bluez.LEAdvertisingManager1')
                    try:
                        await adv_manager.call_unregister_advertisement(self._adv_path)
                    except Exception:
                        pass
                except Exception:
                    pass
                try:
                    introspection = await self._bus.introspect('org.bluez', f'/org/bluez/{self._adapter}')
                    proxy_obj = self._bus.get_proxy_object('org.bluez', f'/org/bluez/{self._adapter}', introspection)
                    gatt_manager = proxy_obj.get_interface('org.bluez.GattManager1')
                    try:
                        await gatt_manager.call_unregister_application(self._app_path)
                    except Exception:
                        pass
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if self.bridge and hasattr(self.bridge, '_app_connected'):
                self.bridge._app_connected = False
        except Exception:
            pass

    async def stop(self):
        self._running = False
        await self._cleanup()
        if self._notify_task:
            self._notify_task.cancel()
            try:
                await self._notify_task
            except Exception:
                pass
        if self._bus:
            try:
                self._bus.disconnect()
            except Exception:
                pass
        log.info("Stopping BLE FTMS backend")
