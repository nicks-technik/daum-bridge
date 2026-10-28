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
                if hasattr(self._backend.bridge, '_client_connected'):
                    self._backend.bridge._client_connected = True
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

    async def start(self):
        log.info("Starting BLE FTMS backend on %s as %s", self._adapter, self._device_name)
        self._running = True
        if self.bridge:
            if hasattr(self.bridge, '_app_connected'):
                self.bridge._app_connected = False
            if hasattr(self.bridge, '_client_connected'):
                self.bridge._client_connected = False

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

    async def _watch_adapter(self):
        while self._running:
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception:
                pass
            try:
                if not self._bus or not DBUS_AVAILABLE:
                    continue
                # Check if we need to re-register
                try:
                    introspection = await self._bus.introspect('org.bluez', f'/org/bluez/{self._adapter}')
                    proxy_obj = self._bus.get_proxy_object('org.bluez', f'/org/bluez/{self._adapter}', introspection)
                    adapter = proxy_obj.get_interface('org.bluez.Adapter1')
                    powered = await adapter.get_powered()
                    if not powered:
                        log.warning("BLE adapter not powered")
                except Exception:
                    pass
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
        feature_char = Characteristic(feature_path, FITNESS_MACHINE_FEATURE_UUID, ['read'], ftms_service_path, bus=self._bus, backend=self)
        fitness_machine_features = 0x00000000
        target_setting_features = 0x00000000
        fitness_machine_features |= (1 << 1) | (1 << 10) | (1 << 14)
        target_setting_features |= (1 << 1) | (1 << 2)
        features = struct.pack('<II', fitness_machine_features, target_setting_features)
        feature_char.value = list(features)
        self._bus.export(feature_path, feature_char)
        self._objects.append(feature_char)
        
        # Indoor Bike Data (notify)
        ibd_path = f'{ftms_service_path}/char1'
        ibd_char = Characteristic(ibd_path, INDOOR_BIKE_DATA_UUID, ['notify'], ftms_service_path, bus=self._bus, backend=self)
        self._indoor_bike_data_char = ibd_char
        self._bus.export(ibd_path, ibd_char)
        self._objects.append(ibd_char)
        try:
            cccd_ibd_path = f'{ibd_path}/desc0'
            class CCCD2(ServiceInterface):
                def __init__(self, opath, cpath):
                    super().__init__('org.bluez.GattDescriptor1')
                    self.path = opath
                    self.uuid = '00002902-0000-1000-8000-00805f9b34fb'
                    self.cpath = cpath
                    self.value = [0x00, 0x00]
                @dbus_property()
                def UUID(self): return self.uuid
                @dbus_property()
                def Characteristic(self): return self.cpath
                @dbus_property()
                def Value(self): return self.value
                @method()
                def ReadValue(self, options): return self.value
                @method()
                def WriteValue(self, value, options):
                    self.value = value
            c2 = CCCD2(cccd_ibd_path, ibd_path)
            self._bus.export(cccd_ibd_path, c2)
            self._objects.append(c2)
        except Exception:
            pass
        
        # Fitness Machine Status (notify)
        status_path = f'{ftms_service_path}/char2'
        status_char = Characteristic(status_path, FITNESS_MACHINE_STATUS_UUID, ['notify'], ftms_service_path, bus=self._bus, backend=self)
        self._fitness_machine_status_char = status_char
        self._bus.export(status_path, status_char)
        self._objects.append(status_char)
        try:
            cccd_st_path = f'{status_path}/desc0'
            class CCCD3(ServiceInterface):
                def __init__(self, opath, cpath):
                    super().__init__('org.bluez.GattDescriptor1')
                    self.path = opath
                    self.uuid = '00002902-0000-1000-8000-00805f9b34fb'
                    self.cpath = cpath
                    self.value = [0x00, 0x00]
                @dbus_property()
                def UUID(self): return self.uuid
                @dbus_property()
                def Characteristic(self): return self.cpath
                @dbus_property()
                def Value(self): return self.value
                @method()
                def ReadValue(self, options): return self.value
                @method()
                def WriteValue(self, value, options):
                    self.value = value
            c3 = CCCD3(cccd_st_path, status_path)
            self._bus.export(cccd_st_path, c3)
            self._objects.append(c3)
        except Exception:
            pass
        
        # Fitness Machine Control Point (write, indicate)
        cp_path = f'{ftms_service_path}/char3'
        cp_char = Characteristic(cp_path, FITNESS_MACHINE_CONTROL_POINT_UUID, ['write', 'indicate'], ftms_service_path, bus=self._bus, backend=self)
        cp_char._notify_callback = self._handle_control_point
        self._control_point_char = cp_char
        self._bus.export(cp_path, cp_char)
        self._objects.append(cp_char)
        
        # CCCD for Control Point
        try:
            cccd_cp_path = f'{cp_path}/desc0'
            from dbus_next.service import ServiceInterface as SI
            class CCCD(SI):
                def __init__(self, opath, cpath):
                    super().__init__('org.bluez.GattDescriptor1')
                    self.path = opath
                    self.uuid = '00002902-0000-1000-8000-00805f9b34fb'
                    self.cpath = cpath
                    self.value = [0x00, 0x00]
                @dbus_property()
                def UUID(self): return self.uuid
                @dbus_property()
                def Characteristic(self): return self.cpath
                @dbus_property()
                def Value(self): return self.value
                @method()
                def ReadValue(self, options): return self.value
                @method()
                def WriteValue(self, value, options):
                    self.value = value
            cccd_cp = CCCD(cccd_cp_path, cp_path)
            self._bus.export(cccd_cp_path, cccd_cp)
            self._objects.append(cccd_cp)
        except Exception as e:
            log.debug(f"CCCD CP error: {e}")
        
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
            srl_char.value = list(struct.pack('<hhh', 0, 100, 1))
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
            try:
                self._advertisement.ServiceUUIDs = [FTMS_UUID, HEART_RATE_SERVICE_UUID, CYCLING_POWER_SERVICE_UUID]
            except Exception:
                pass
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
            self._last_cp_req = op_code
            log.info(f"Control Point op: 0x{op_code:02X} data={data.hex()}")
            if self.bridge and hasattr(self.bridge, '_app_connected'):
                self.bridge._app_connected = True
            if self.bridge and hasattr(self.bridge, '_client_connected'):
                self.bridge._client_connected = True
            # Request Control (0x00)
            if op_code == 0x00:
                self._control_point_enabled = True
                if self.bridge and hasattr(self.bridge, '_erg_control_granted'):
                    self.bridge._erg_control_granted = True
                self._send_cp_response(0x00, 0x01, 0x00)
                self._send_fitness_machine_status(0x01)
                return
            # Reset (0x01)
            elif op_code == 0x01:
                self._control_point_enabled = False
                if self.bridge and hasattr(self.bridge, '_erg_control_granted'):
                    self.bridge._erg_control_granted = False
                if self.bridge and hasattr(self.bridge, 'set_target_watt'):
                    try:
                        self.bridge.set_target_watt(0)
                    except Exception:
                        pass
                self._send_cp_response(0x01, 0x01, 0x00)
                self._send_fitness_machine_status(0x02)
                return
            # Start or Resume (0x07)
            elif op_code == 0x07:
                if not self._control_point_enabled:
                    self._send_cp_response(0x07, 0x02, 0x02)
                    return
                self._send_cp_response(0x07, 0x01, 0x00)
                self._send_fitness_machine_status(0x01)
                return
            # Stop or Pause (0x08)
            elif op_code == 0x08:
                if not self._control_point_enabled:
                    self._send_cp_response(0x08, 0x02, 0x02)
                    return
                self._send_cp_response(0x08, 0x01, 0x00)
                self._send_fitness_machine_status(0x04)
                return
            # Set Target Power (0x05)
            elif op_code == 0x05 and len(data) >= 3:
                if not self._control_point_enabled:
                    self._send_cp_response(0x05, 0x02, 0x02)
                    return
                try:
                    power = struct.unpack('<h', data[1:3])[0]
                except Exception:
                    self._send_cp_response(0x05, 0x03, 0x01)
                    return
                power_clamped = max(10, min(800, int(power)))
                log.info(f"FTMS set target power: {power}W (clamped to {power_clamped}W)")
                if self.bridge and hasattr(self.bridge, 'set_target_watt'):
                    try:
                        self.bridge.set_target_watt(power_clamped)
                        if hasattr(self.bridge, '_erg_control_granted'):
                            self.bridge._erg_control_granted = True
                    except Exception as e:
                        log.debug(f"Error setting power: {e}")
                self._send_cp_response(0x05, 0x01, 0x00)
                self._send_fitness_machine_status(0x07)
                return
            # Set Indoor Bike Simulation Parameters (0x11)
            elif op_code == 0x11 and len(data) >= 7:
                if not self._control_point_enabled:
                    self._send_cp_response(0x11, 0x02, 0x02)
                    return
                # Basic SIM support - acknowledge
                self._send_cp_response(0x11, 0x01, 0x00)
                self._send_fitness_machine_status(0x14)  # Simulation parameters changed if available
                return
            # Set Resistance Level (0x04)
            elif op_code == 0x04 and len(data) >= 3:
                if not self._control_point_enabled:
                    self._send_cp_response(0x04, 0x02, 0x02)
                    return
                self._send_cp_response(0x04, 0x01, 0x00)
                return
            else:
                self._send_cp_response(op_code, 0x02, 0x07)
        except Exception as e:
            log.error(f"Control point error: {e}")

    def _send_cp_response(self, request_op, result_code, error_code=0x00):
        try:
            if not self._control_point_char:
                return
            resp = bytearray([0x80, request_op & 0xFF, result_code & 0xFF])
            if result_code != 0x01:
                if result_code == 0x03 and error_code == 0x00:
                    resp.append(error_code)
                elif error_code != 0x00:
                    resp.append(error_code)
            self._control_point_char.value = list(resp)
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(self._control_point_char.send_notification(bytes(resp)))
            except Exception:
                pass
            if self.bridge and hasattr(self.bridge, '_app_connected'):
                self.bridge._app_connected = True
            if self.bridge and hasattr(self.bridge, '_client_connected'):
                self.bridge._client_connected = True
            log.debug(f"CP response: {bytes(resp).hex()}")
        except Exception as e:
            log.debug(f"CP response error: {e}")

    def _send_fitness_machine_status(self, status: int, data: bytes = b''):
        try:
            if not self._fitness_machine_status_char:
                return
            packet = bytearray([status & 0xFF]) + bytearray(data)
            self._fitness_machine_status_char.value = list(packet)
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(self._fitness_machine_status_char.send_notification(bytes(packet)))
            except Exception:
                pass
            log.debug(f"FTMS status: 0x{status:02X}")
        except Exception as e:
            log.debug(f"Status send error: {e}")

    async def _notify_loop(self):
        while self._running:
            try:
                if self.bridge and hasattr(self.bridge, 'state'):
                    state = self.bridge.state
                    # Indoor Bike Data
                    if self._indoor_bike_data_char:
                        flags = 0x0057  # speed(0) + cadence(1) + distance(2) + elapsed time(3) + power(6)
                        packet = bytearray()
                        packet += struct.pack('<H', flags)
                        if hasattr(state, 'speed') and state.speed is not None:
                            try:
                                speed = int(round(float(state.speed) * 100)) & 0xFFFF
                            except Exception:
                                speed = 0
                        else:
                            speed = 0
                        packet += struct.pack('<H', speed)
                        if hasattr(state, 'cadence') and state.cadence is not None:
                            try:
                                cadence = int(round(float(state.cadence) * 2)) & 0xFFFF
                            except Exception:
                                cadence = 0
                        else:
                            cadence = 0
                        packet += struct.pack('<H', cadence)
                        if hasattr(state, 'total_distance') and state.total_distance is not None:
                            try:
                                dist_m = int(float(state.total_distance) * 1000) & 0xFFFFFF
                            except Exception:
                                dist_m = 0
                        else:
                            dist_m = 0
                        packet += bytes([dist_m & 0xFF, (dist_m >> 8) & 0xFF, (dist_m >> 16) & 0xFF])
                        if hasattr(state, 'elapsed_time') and state.elapsed_time is not None:
                            try:
                                et = int(state.elapsed_time) & 0xFFFF
                            except Exception:
                                et = 0
                        else:
                            et = 0
                        packet += struct.pack('<H', et)
                        if hasattr(state, 'power') and state.power is not None:
                            try:
                                power = int(float(state.power))
                            except Exception:
                                power = 0
                        else:
                            power = 0
                        packet += struct.pack('<h', power & 0xFFFF)
                        if self._indoor_bike_data_char.notifying or getattr(self._indoor_bike_data_char, 'indicating', False):
                            try:
                                await self._indoor_bike_data_char.send_notification(bytes(packet))
                            except Exception:
                                pass
                        else:
                            self._indoor_bike_data_char.value = list(packet)
                    # Heart Rate
                    if self._heart_rate_char and hasattr(state, 'heart_rate') and state.heart_rate and state.heart_rate > 0:
                        try:
                            hr = int(state.heart_rate)
                            if 40 <= hr <= 220:
                                hr_packet = bytearray([0x00, hr & 0xFF])
                                if self._heart_rate_char.notifying or getattr(self._heart_rate_char, 'indicating', False):
                                    await self._heart_rate_char.send_notification(bytes(hr_packet))
                                else:
                                    self._heart_rate_char.value = list(hr_packet)
                        except Exception:
                            pass
                    # Cycling Power (with optional crank data)
                    if self._cycling_power_char:
                        try:
                            pwr = int(getattr(state, 'power', 0) or 0)
                            cad = int(getattr(state, 'cadence', 0) or 0)
                            flags = 0x0020  # Crank Revolution Data
                            cp_packet = bytearray([flags & 0xFF, (flags >> 8) & 0xFF])
                            cp_packet += struct.pack('<h', pwr & 0xFFFF)
                            # Crank revolutions (uint16) and crank event time (uint16, 1/1024s)
                            if cad > 0:
                                rev = int(time.time() * cad / 60) & 0xFFFF
                                ctime = int((time.time() % 1) * 1024 * 60 / max(cad,1)) & 0xFFFF
                            else:
                                rev = 0
                                ctime = 0
                            cp_packet += struct.pack('<HH', rev, ctime)
                            if self._cycling_power_char.notifying or getattr(self._cycling_power_char, 'indicating', False):
                                await self._cycling_power_char.send_notification(bytes(cp_packet))
                            else:
                                self._cycling_power_char.value = list(cp_packet)
                        except Exception:
                            pass
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
            if self.bridge and hasattr(self.bridge, '_client_connected'):
                self.bridge._client_connected = False
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
