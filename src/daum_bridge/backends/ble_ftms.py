"""BLE FTMS peripheral backend for MyWhoosh (Linux/BlueZ via dbus-next).
Implements a minimal FTMS GATT server with advertising and control point handling.
"""

from __future__ import annotations

import asyncio
import logging
import struct
from typing import Optional

log = logging.getLogger(__name__)

try:
    from dbus_next.aio import MessageBus
    from dbus_next.service import ServiceInterface, method, dbus_property, signal
    from dbus_next import Variant, BusType
    from dbus_next.errors import DBusError
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


class Application(ServiceInterface):
    def __init__(self, object_path):
        super().__init__('org.bluez.GattApplication1')
        self.path = object_path

    @dbus_property()
    def GetManagedObjects(self) -> 'a{oa{sa{sv}}}':
        return {}


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


class BLEFTMSBackend:
    def __init__(self, bridge, config):
        self.bridge = bridge
        self.config = config
        self._running = False
        self._bus = None
        self._advertisement = None
        self._application = None
        self._notify_task = None
        self._adv_path = '/org/bluez/example/advertisement0'
        self._app_path = '/org/bluez/example/application0'
        self._adapter = getattr(getattr(config, 'ble', None), 'adapter', 'hci0')
        self._device_name = getattr(getattr(config, 'ble', None), 'device_name', 'DAUM-8008-TRS')

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
            # Try to register advertisement
            await self._register_advertisement()
            log.info("FTMS advertising registered")
        except Exception as e:
            log.warning("Failed to register advertisement (may need BlueZ configured): %s", e)

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

    async def _register_advertisement(self):
        # Register LE advertisement
        self._advertisement = Advertisement(self._adv_path, self._device_name)
        self._bus.export(self._adv_path, self._advertisement)
        # Get advertising manager
        try:
            introspection = await self._bus.introspect('org.bluez', f'/org/bluez/{self._adapter}')
            proxy_obj = self._bus.get_proxy_object('org.bluez', f'/org/bluez/{self._adapter}', introspection)
            adv_manager = proxy_obj.get_interface('org.bluez.LEAdvertisingManager1')
            await adv_manager.call_register_advertisement(self._adv_path, {})
            log.info("LE Advertisement registered")
        except Exception as e:
            log.debug("Advertisement registration details: %s", e)
            raise

    async def _cleanup(self):
        try:
            if self._advertisement:
                introspection = await self._bus.introspect('org.bluez', f'/org/bluez/{self._adapter}')
                proxy_obj = self._bus.get_proxy_object('org.bluez', f'/org/bluez/{self._adapter}', introspection)
                adv_manager = proxy_obj.get_interface('org.bluez.LEAdvertisingManager1')
                try:
                    await adv_manager.call_unregister_advertisement(self._adv_path)
                except Exception:
                    pass
        except Exception:
            pass

    async def _notify_loop(self):
        """Send periodic Indoor Bike Data notifications from bridge state"""
        while self._running:
            try:
                if self.bridge and hasattr(self.bridge, 'state'):
                    state = self.bridge.state
                    # Pack Indoor Bike Data (FTMS 0x2AD2)
                    # Flags: bit 1 = Instantaneous Cadence present, bit 6 = Instantaneous Power present
                    flags = 0x0042  # cadence (bit 1) + power (bit 6)
                    packet = bytearray()
                    packet += struct.pack('<H', flags)
                    # Instantaneous Cadence (uint16, resolution 0.5 rpm)
                    if hasattr(state, 'cadence') and state.cadence is not None:
                        cadence = int(round(float(state.cadence) * 2)) & 0xFFFF
                    else:
                        cadence = 0
                    packet += struct.pack('<H', cadence)
                    # Instantaneous Power (sint16, watts)
                    if hasattr(state, 'power') and state.power is not None:
                        power = int(float(state.power)) & 0xFFFF
                    else:
                        power = 0
                    packet += struct.pack('<h', power)
                    log.debug("FTMS Indoor Bike Data: cadence=%s power=%s", state.cadence, state.power)
            except Exception as e:
                log.debug("Notify loop error: %s", e)
            await asyncio.sleep(0.5)

    async def stop(self):
        self._running = False
        if self._notify_task:
            self._notify_task.cancel()
        log.info("Stopping BLE FTMS backend")
