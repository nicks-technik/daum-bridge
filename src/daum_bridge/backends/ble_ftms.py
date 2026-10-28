"""BLE FTMS peripheral backend for MyWhoosh (Linux/BlueZ via dbus-next).
Implements full FTMS GATT server with advertising, characteristics, notifications, and control point.
"""

from __future__ import annotations

import asyncio
import logging
import struct
from typing import Dict, List

log = logging.getLogger(__name__)

try:
    from dbus_next.aio import MessageBus
    from dbus_next.service import ServiceInterface, method, dbus_property
    from dbus_next import Variant, BusType
    DBUS_AVAILABLE = True
except Exception as e:
    log.debug("dbus-next not available: %s", e)
    DBUS_AVAILABLE = False


# FTMS UUIDs (standard)
FTMS_UUID = '00001826-0000-1000-8000-00805f9b34fb'
INDOOR_BIKE_DATA_UUID = '00002ad2-0000-1000-8000-00805f9b34fb'
FITNESS_MACHINE_FEATURE_UUID = '00002ad8-0000-1000-8000-00805f9b34fb'
FITNESS_MACHINE_CONTROL_POINT_UUID = '00002ad9-0000-1000-8000-00805f9b34fb'
FITNESS_MACHINE_STATUS_UUID = '00002ad3-0000-1000-8000-00805f9b34fb'
DEVICE_INFORMATION_SERVICE_UUID = '0000180a-0000-1000-8000-00805f9b34fb'
MANUFACTURER_NAME_UUID = '00002a29-0000-1000-8000-00805f9b34fb'
MODEL_NUMBER_UUID = '00002a24-0000-1000-8000-00805f9b34fb'
GATT_CHARACTERISTIC_USER_DESC_UUID = '00002901-0000-1000-8000-00805f9b34fb'
GATT_CLIENT_CHAR_CFG_UUID = '00002902-0000-1000-8000-00805f9b34fb'


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
        return [FTMS_UUID]

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
    def __init__(self, object_path, uuid, flags, service_path):
        super().__init__('org.bluez.GattCharacteristic1')
        self.path = object_path
        self.uuid = uuid
        self.flags = flags
        self.service_path = service_path
        self.value = []
        self.notifying = False
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

    @method()
    def StopNotify(self):
        log.info(f"StopNotify on {self.uuid}")
        self.notifying = False

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

    async def start(self):
        log.info("Starting BLE FTMS backend on %s as %s", self._adapter, self._device_name)
        self._running = True

        if not DBUS_AVAILABLE:
            log.warning("dbus-next not available; BLE FTMS peripheral cannot run on this platform")
            try:
                while self._running:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                pass
            return

        try:
            self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            log.info("Connected to system D-Bus")
        except Exception as e:
            log.error("Failed to connect to system D-Bus: %s", e)
            log.warning("BLE FTMS peripheral requires BlueZ on Linux with system D-Bus access")
            try:
                while self._running:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                pass
            return

        try:
            await self._setup_gatt()
            await self._register_advertisement()
            log.info("FTMS GATT server and advertising registered")
        except Exception as e:
            log.error("Failed to setup FTMS GATT: %s", e)
            log.warning("Falling back to advertising only")

        try:
            self._notify_task = asyncio.create_task(self._notify_loop())
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
            if self._bus:
                try:
                    self._bus.disconnect()
                except Exception:
                    pass

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
        feature_char = Characteristic(feature_path, FITNESS_MACHINE_FEATURE_UUID, ['read'], ftms_service_path)
        # Feature bits: bit 1 = Cadence supported, bit 2 = Total Distance supported, bit 6 = Power Measurement Supported
        # For indoor bike: power and cadence
        features = 0x00000042  # simplified
        feature_char.value = list(struct.pack('<I', features))
        self._bus.export(feature_path, feature_char)
        self._objects.append(feature_char)
        
        # Indoor Bike Data (notify)
        ibd_path = f'{ftms_service_path}/char1'
        ibd_char = Characteristic(ibd_path, INDOOR_BIKE_DATA_UUID, ['notify'], ftms_service_path)
        self._indoor_bike_data_char = ibd_char
        self._bus.export(ibd_path, ibd_char)
        self._objects.append(ibd_char)
        
        # Fitness Machine Status (notify)
        status_path = f'{ftms_service_path}/char2'
        status_char = Characteristic(status_path, FITNESS_MACHINE_STATUS_UUID, ['notify'], ftms_service_path)
        self._bus.export(status_path, status_char)
        self._objects.append(status_char)
        
        # Fitness Machine Control Point (write, indicate)
        cp_path = f'{ftms_service_path}/char3'
        cp_char = Characteristic(cp_path, FITNESS_MACHINE_CONTROL_POINT_UUID, ['write', 'indicate'], ftms_service_path)
        cp_char._notify_callback = self._handle_control_point
        self._control_point_char = cp_char
        self._bus.export(cp_path, cp_char)
        self._objects.append(cp_char)
        
        # Register application
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
        try:
            if not data:
                return
            op_code = data[0]
            log.info(f"Control Point op: 0x{op_code:02X} data={data.hex()}")
            # Request Control (0x00)
            if op_code == 0x00:
                self._control_point_enabled = True
                # Send success response
                self._send_cp_response(0x00, 0x01, 0x00)  # Request Control, Success
            # Set Target Power (0x05) - format: op(1) + power(2 little endian)
            elif op_code == 0x05 and len(data) >= 3:
                power = struct.unpack('<h', data[1:3])[0]
                log.info(f"FTMS set target power: {power}W")
                if self.bridge and hasattr(self.bridge, 'set_target_watt'):
                    try:
                        self.bridge.set_target_watt(int(power))
                    except Exception as e:
                        log.debug(f"Error setting power: {e}")
                self._send_cp_response(0x05, 0x01, 0x00)  # Success
            # Reset (0x01)
            elif op_code == 0x01:
                self._control_point_enabled = False
                self._send_cp_response(0x01, 0x01, 0x00)
            else:
                # Not supported
                self._send_cp_response(op_code, 0x02, 0x07)
        except Exception as e:
            log.error(f"Control point error: {e}")

    def _send_cp_response(self, request_op, result_code, error_code=0x00):
        try:
            if not self._control_point_char:
                return
            # Response: 0x80 (Response Code) + Request Op Code + Result Code [+ Error Code if needed]
            resp = bytearray([0x80, request_op, result_code])
            if result_code != 0x01 and error_code != 0x00:
                resp.append(error_code)
            self._control_point_char.value = list(resp)
            log.debug(f"CP response: {bytes(resp).hex()}")
        except Exception as e:
            log.debug(f"CP response error: {e}")

    async def _notify_loop(self):
        while self._running:
            try:
                if self.bridge and hasattr(self.bridge, 'state') and self._indoor_bike_data_char:
                    state = self.bridge.state
                    # Pack Indoor Bike Data (FTMS 0x2AD2)
                    flags = 0x0042  # cadence present (bit 1) + power present (bit 6)
                    packet = bytearray()
                    packet += struct.pack('<H', flags)
                    # Instantaneous Cadence (uint16, resolution 0.5 rpm)
                    if hasattr(state, 'cadence') and state.cadence is not None:
                        try:
                            cadence = int(round(float(state.cadence) * 2)) & 0xFFFF
                        except Exception:
                            cadence = 0
                    else:
                        cadence = 0
                    packet += struct.pack('<H', cadence)
                    # Instantaneous Power (sint16, watts)
                    if hasattr(state, 'power') and state.power is not None:
                        try:
                            power = int(float(state.power))
                            # Handle signed
                            if power < 0:
                                power = power & 0xFFFF
                        except Exception:
                            power = 0
                    else:
                        power = 0
                    packet += struct.pack('<h', power & 0xFFFF)
                    self._indoor_bike_data_char.value = list(packet)
                    if self._indoor_bike_data_char.notifying:
                        log.debug("FTMS notifying IBP: cadence=%s power=%s", state.cadence, state.power)
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

    async def stop(self):
        self._running = False
        if self._notify_task:
            self._notify_task.cancel()
        log.info("Stopping BLE FTMS backend")
