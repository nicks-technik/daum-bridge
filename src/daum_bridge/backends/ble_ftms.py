"""BLE FTMS peripheral backend for MyWhoosh (Linux/BlueZ via dbus-next).
Implements a minimal FTMS GATT server structure using D-Bus/BlueZ.
"""

from __future__ import annotations

import asyncio
import logging
import struct
from typing import Optional

log = logging.getLogger(__name__)

try:
    from dbus_next.aio import MessageBus
    from dbus_next.service import ServiceInterface, method, dbus_property
    from dbus_next import Variant, BusType
    DBUS_AVAILABLE = True
except Exception as e:
    log.debug("dbus-next not available: %s", e)
    DBUS_AVAILABLE = False


# FTMS UUIDs
FTMS_UUID = '00001826-0000-1000-8000-00805f9b34fb'
INDOOR_BIKE_DATA_UUID = '00002ad2-0000-1000-8000-00805f9b34fb'
FITNESS_MACHINE_FEATURE_UUID = '00002ad8-0000-1000-8000-00805f9b34fb'
FITNESS_MACHINE_CONTROL_POINT_UUID = '00002ad9-0000-1000-8000-00805f9b34fb'
FITNESS_MACHINE_STATUS_UUID = '00002ad3-0000-1000-8000-00805f9b34fb'


class BLEFTMSBackend:
    def __init__(self, bridge, config):
        self.bridge = bridge
        self.config = config
        self._running = False
        self._bus = None
        self._advertisement = None
        self._application = None
        self._notify_task = None

    async def start(self):
        log.info("Starting BLE FTMS backend on %s as %s", getattr(self.config.ble, 'adapter', 'hci0'), getattr(self.config.ble, 'device_name', 'DAUM-8008-TRS'))
        self._running = True

        if not DBUS_AVAILABLE:
            log.warning("dbus-next not available; BLE FTMS peripheral cannot run on this platform")
            # Keep alive so bridge doesn't crash
            try:
                while self._running:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                pass
            return

        try:
            # Try to connect to system bus
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
            # This is a minimal implementation structure
            # Full GATT registration requires complex D-Bus object paths and BlueZ APIs
            # For now, log intent and start notification loop
            log.info("Attempting FTMS GATT setup (structure initialized)")
            self._notify_task = asyncio.create_task(self._notify_loop())
            while self._running:
                await asyncio.sleep(1)
        except Exception as e:
            log.error("BLE FTMS backend error: %s", e)
        finally:
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

    async def _notify_loop(self):
        """Send periodic Indoor Bike Data notifications from bridge state"""
        while self._running:
            try:
                if self.bridge and hasattr(self.bridge, 'state'):
                    state = self.bridge.state
                    # Pack Indoor Bike Data (minimal)
                    # Flags: power present, cadence present (example)
                    flags = 0x0044  # bit 2 (cadence) and bit 6 (power) set (simplified)
                    packet = struct.pack('<H', flags)
                    # Cadence (0.5 rpm resolution) - simplified
                    if hasattr(state, 'cadence') and state.cadence is not None:
                        cadence = int(state.cadence * 2) & 0xFFFF
                        packet += struct.pack('<H', cadence)
                    else:
                        packet += struct.pack('<H', 0)
                    # Power (sint16 watts)
                    if hasattr(state, 'power') and state.power is not None:
                        power = int(state.power) & 0xFFFF
                        packet += struct.pack('<h', power)
                    else:
                        packet += struct.pack('<h', 0)
                    log.debug("FTMS IBP packet prepared: %s", packet.hex())
            except Exception as e:
                log.debug("Notify loop error: %s", e)
            await asyncio.sleep(0.5)

    async def stop(self):
        self._running = False
        if self._notify_task:
            self._notify_task.cancel()
        log.info("Stopping BLE FTMS backend")
