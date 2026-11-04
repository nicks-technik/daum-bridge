"""BLE heart-rate central: pair the belt with the bridge, not the app.

The bridge is normally a BLE *peripheral* (FTMS). A chest strap is also a
peripheral, so to read it the bridge has to act as a BLE *central* as well.
BlueZ runs both roles on the same adapter: the FTMS advertisement keeps
running while the belt is discovered and connected.

Why bother? When the belt is paired directly in MyWhoosh/Zwift the bridge never
sees a heart rate, so the ride file (TCX) has none. Reading the belt here means
the value lands in the ride recording *and* is republished through the FTMS
Heart Rate Service, so the training app still displays it.

The standard Heart Rate Measurement characteristic (``0x2A37``) is decoded
according to the Bluetooth SIG spec: bit 0 of the flags byte selects an 8-bit
or a 16-bit value.
"""

from __future__ import annotations

import asyncio
import logging
import struct
import threading
import time
from typing import Optional

from ..numbers import as_float

log = logging.getLogger(__name__)

try:
    from dbus_next import BusType, Message, MessageType, Variant
    from dbus_next.aio import MessageBus

    DBUS_AVAILABLE = True
    DBUS_IMPORT_ERROR = None
except Exception as e:  # pragma: no cover - only on platforms without dbus
    log.debug("dbus-next not available: %s", e)
    DBUS_AVAILABLE = False
    DBUS_IMPORT_ERROR = f"{type(e).__name__}: {e}"

BLUEZ = "org.bluez"
ADAPTER_IFACE = "org.bluez.Adapter1"
DEVICE_IFACE = "org.bluez.Device1"
GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHAR_IFACE = "org.bluez.GattCharacteristic1"
OBJECT_MANAGER_IFACE = "org.freedesktop.DBus.ObjectManager"
PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"

HEART_RATE_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HEART_RATE_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

#: Advertised names of common straps, used when BlueZ has not resolved the
#: service UUIDs yet. Matching is case-insensitive.
BELT_NAME_HINTS = (
    "heart",
    "hrm",
    "polar",
    "garmin",
    "wahoo",
    "tickr",
    "coospo",
    "magene",
    "sigmasport",
    "suunto",
    "coros",
)


def decode_heart_rate(value) -> Optional[int]:
    """Decode a Heart Rate Measurement payload into beats per minute.

    ``value`` is the raw characteristic value (bytes or a list of ints).
    Returns ``None`` for an empty/short payload or an implausible value, so a
    malformed notification never overwrites a good reading.
    """
    if not value:
        return None
    try:
        data = bytes(value)
    except (TypeError, ValueError):
        return None
    if not data:
        return None
    flags = data[0]
    if flags & 0x01:  # 16-bit heart rate value
        if len(data) < 3:
            return None
        hr = struct.unpack_from("<H", data, 1)[0]
    else:  # 8-bit heart rate value
        if len(data) < 2:
            return None
        hr = data[1]
    # 0 = "not measured"; above 250 cannot be a human heart rate.
    return hr if 25 <= hr <= 250 else None


def _prop(props: dict, key: str, default=None):
    """Return a BlueZ property value, unwrapping dbus-next Variants."""
    value = props.get(key, default)
    return value.value if isinstance(value, Variant) else value


def _looks_like_belt(name: str) -> bool:
    lowered = (name or "").lower()
    return any(hint in lowered for hint in BELT_NAME_HINTS)


def find_device(objects: dict, wanted: str = "") -> Optional[tuple[str, dict]]:
    """Pick a heart-rate belt from a BlueZ ``GetManagedObjects`` result.

    ``wanted`` is an address or part of the advertised name. When it is empty,
    the first device advertising the Heart Rate service wins; straps that do
    not expose their UUIDs yet are recognised by their name.

    Returns ``(object_path, info)`` with ``address``/``name``/``uuids``.
    """
    wanted = (wanted or "").strip().lower()
    candidates = []
    for path, interfaces in objects.items():
        props = interfaces.get(DEVICE_IFACE)
        if not props:
            continue
        address = str(_prop(props, "Address", "") or "")
        name = str(_prop(props, "Alias", "") or _prop(props, "Name", "") or "")
        uuids = [str(u).lower() for u in (_prop(props, "UUIDs", []) or [])]
        if wanted:
            if wanted != address.lower() and wanted not in name.lower():
                continue
        elif HEART_RATE_SERVICE_UUID not in uuids and not _looks_like_belt(name):
            continue
        candidates.append(
            (path, {"address": address, "name": name, "uuids": uuids})
        )
    if not candidates:
        return None
    # Prefer a device that actually advertises the Heart Rate service.
    candidates.sort(key=lambda item: HEART_RATE_SERVICE_UUID not in item[1]["uuids"])
    return candidates[0]


def properties_match_rule(char_path: str) -> str:
    """Return the D-Bus match rule for a characteristic's Value signals.

    dbus-next only delivers broadcast signals to a connection that added a
    matching rule. ``add_message_handler`` alone is not enough, so the HR
    backend must subscribe explicitly before ``StartNotify``.
    """
    return (
        "type='signal',sender='org.bluez',"
        "interface='org.freedesktop.DBus.Properties',"
        "member='PropertiesChanged',"
        f"path='{char_path}'"
    )


def find_heart_rate_characteristic(objects: dict) -> Optional[str]:
    """Return the ``0x2A37`` characteristic that belongs to the HR service."""
    services = {}
    for path, interfaces in objects.items():
        props = interfaces.get(GATT_SERVICE_IFACE)
        if props:
            services[path] = str(_prop(props, "UUID", "") or "").lower()

    for path, interfaces in objects.items():
        props = interfaces.get(GATT_CHAR_IFACE)
        if not props:
            continue
        uuid = str(_prop(props, "UUID", "") or "").lower()
        if uuid != HEART_RATE_MEASUREMENT_UUID:
            continue
        service_path = str(_prop(props, "Service", "") or "")
        if services.get(service_path) == HEART_RATE_SERVICE_UUID:
            return path
    return None


class HeartRateBackend:
    """Scan for, connect to and subscribe to a BLE heart-rate belt."""

    def __init__(self, bridge, config):
        self.bridge = bridge
        self.config = config
        cfg = getattr(config, "heart_rate", None)
        self.enabled = bool(getattr(cfg, "enabled", False))
        self.device = str(getattr(cfg, "device", "") or "")
        self.adapter = (
            str(getattr(cfg, "adapter", "") or "")
            or getattr(getattr(config, "ble", None), "adapter", "hci0")
        )
        self.scan_timeout = max(1.0, as_float(getattr(cfg, "scan_timeout", 30.0), 30.0))
        self.reconnect_delay = max(
            0.5, as_float(getattr(cfg, "reconnect_delay", 5.0), 5.0)
        )
        self.last_error: Optional[str] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._loop = None
        self._task = None
        self._bus = None
        self._device_path: Optional[str] = None
        self._char_path: Optional[str] = None
        self._info: dict = {}
        self._last_seen = 0.0
        self._last_hr = 0
        self._match_rule: Optional[str] = None

    # -- public API -------------------------------------------------------
    def start(self) -> bool:
        """Start the scan/connect thread. Returns ``False`` when unavailable."""
        if not self.enabled:
            return False
        if not DBUS_AVAILABLE:
            self.last_error = DBUS_IMPORT_ERROR or "dbus-next is not installed"
            return False
        self._running = True
        self._thread = threading.Thread(
            target=self._run, name="hr-ble", daemon=True
        )
        self._thread.start()
        return True

    def stop(self):
        self._running = False
        loop = self._loop
        if loop is not None and loop.is_running() and self._task is not None:
            try:
                loop.call_soon_threadsafe(self._task.cancel)
            except Exception:
                pass
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)

    def status(self) -> dict:
        """Return a JSON-serialisable status for diagnostics."""
        return {
            "enabled": self.enabled,
            "adapter": self.adapter,
            "device": self.device,
            "connected": self._device_path is not None and self._char_path is not None,
            "address": self._info.get("address"),
            "name": self._info.get("name"),
            "heart_rate": self._last_hr,
            "last_error": self.last_error,
        }

    # -- thread / event loop ---------------------------------------------
    def _run(self):
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        self._task = loop.create_task(self._run_forever())
        try:
            loop.run_until_complete(self._task)
        except asyncio.CancelledError:
            pass
        except Exception as e:  # pragma: no cover - hardware dependent
            self.last_error = str(e)
            log.warning("Heart-rate backend stopped: %s", e)
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            except Exception:
                pass
            loop.close()
            self._loop = None

    async def _run_forever(self):
        self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        self._bus.add_message_handler(self._on_message)
        log.info(
            "Heart-rate backend scanning on %s (device=%s)",
            self.adapter,
            self.device or "any",
        )
        try:
            while self._running:
                try:
                    await self._connect_once()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self.last_error = str(e)
                    log.warning("Heart-rate belt: %s", e)
                if self._running:
                    await self._sleep(self.reconnect_delay)
        finally:
            await self._cleanup()

    async def _cleanup(self):
        for path, iface, member in (
            (self._char_path, GATT_CHAR_IFACE, "StopNotify"),
            (self._device_path, DEVICE_IFACE, "Disconnect"),
        ):
            if not path:
                continue
            try:
                await self._call(path, iface, member)
            except Exception:
                pass
        await self._remove_match()
        self._char_path = None
        self._device_path = None
        if self._bus is not None:
            try:
                self._bus.disconnect()
            except Exception:
                pass
            self._bus = None

    async def _connect_once(self):
        match = await self._scan()
        if not match:
            return
        path, info = match
        self._info = info
        self._device_path = path
        self.last_error = None
        log.info(
            "Connecting to heart-rate belt %s (%s)",
            info.get("name") or info.get("address"),
            info.get("address"),
        )
        try:
            await self._call(path, DEVICE_IFACE, "Connect")
            char_path = await self._find_characteristic()
            if not char_path:
                raise RuntimeError("belt has no Heart Rate Measurement characteristic")
            self._char_path = char_path
            await self._add_match(char_path)
            await self._call(char_path, GATT_CHAR_IFACE, "StartNotify")
        except Exception:
            self._char_path = None
            self._device_path = None
            raise
        log.info(
            "Subscribed to heart rate from %s",
            info.get("name") or info.get("address"),
        )
        self._last_seen = time.monotonic()
        while self._running:
            await asyncio.sleep(2.0)
            if not await self._device_connected(path):
                log.info(
                    "Heart-rate belt %s disconnected",
                    info.get("name") or info.get("address"),
                )
                break
            # A strap that stops notifying (battery empty, taken off) should not
            # keep an old value in the ride file forever.
            if time.monotonic() - self._last_seen > 30.0 and self._last_hr:
                self._last_hr = 0
                self._set_heart_rate(0)
        try:
            await self._call(path, GATT_CHAR_IFACE, "StopNotify")
        except Exception:
            pass
        try:
            await self._call(path, DEVICE_IFACE, "Disconnect")
        except Exception:
            pass
        await self._remove_match()
        self._char_path = None
        self._device_path = None
        self._last_hr = 0
        self._set_heart_rate(0)

    async def _scan(self):
        adapter_path = f"/org/bluez/{self.adapter}"
        await self._call(
            adapter_path,
            ADAPTER_IFACE,
            "SetDiscoveryFilter",
            "a{sv}",
            [{"Transport": Variant("s", "le")}],
        )
        await self._call(adapter_path, ADAPTER_IFACE, "StartDiscovery")
        deadline = time.monotonic() + self.scan_timeout
        try:
            while self._running and time.monotonic() < deadline:
                objects = await self._objects()
                match = find_device(objects, self.device)
                if match:
                    log.debug(
                        "Heart-rate belt found: %s (%s)",
                        match[1].get("name"),
                        match[1].get("address"),
                    )
                    return match
                await asyncio.sleep(1.0)
        finally:
            try:
                await self._call(adapter_path, ADAPTER_IFACE, "StopDiscovery")
            except Exception:
                pass
        self.last_error = (
            f"no heart-rate belt found within {self.scan_timeout:.0f} s "
            "(is it still connected to the training app?)"
        )
        log.warning(self.last_error)
        return None

    async def _find_characteristic(self) -> Optional[str]:
        objects = await self._objects()
        return find_heart_rate_characteristic(objects)

    async def _device_connected(self, path: str) -> bool:
        try:
            body = await self._call(
                path, PROPERTIES_IFACE, "Get", "ss", [DEVICE_IFACE, "Connected"]
            )
        except Exception:
            return False
        if not body:
            return False
        value = body[0]
        return bool(value.value if isinstance(value, Variant) else value)

    # -- D-Bus helpers ----------------------------------------------------
    async def _objects(self) -> dict:
        body = await self._call("/", OBJECT_MANAGER_IFACE, "GetManagedObjects")
        return body[0] if body else {}

    async def _call(self, path: str, interface: str, member: str, signature: str = "", body=None):
        if self._bus is None:
            raise RuntimeError("D-Bus not connected")
        reply = await self._bus.call(
            Message(
                destination=BLUEZ,
                path=path,
                interface=interface,
                member=member,
                signature=signature,
                body=body or [],
            )
        )
        if reply.message_type == MessageType.ERROR:
            raise RuntimeError(f"{reply.error_name}: {reply.body}")
        return reply.body

    async def _sleep(self, seconds: float):
        deadline = time.monotonic() + seconds
        while self._running and time.monotonic() < deadline:
            await asyncio.sleep(min(1.0, max(0.0, deadline - time.monotonic())))

    async def _add_match(self, char_path: str):
        """Ask D-Bus to deliver the characteristic's ``PropertiesChanged``."""
        rule = properties_match_rule(char_path)
        if rule == self._match_rule:
            return
        await self._remove_match()
        reply = await self._bus.call(
            Message(
                destination="org.freedesktop.DBus",
                path="/org/freedesktop/DBus",
                interface="org.freedesktop.DBus",
                member="AddMatch",
                signature="s",
                body=[rule],
            )
        )
        if reply.message_type == MessageType.ERROR:
            raise RuntimeError(
                f"AddMatch failed: {reply.error_name}: {reply.body}"
            )
        self._match_rule = rule

    async def _remove_match(self):
        rule, self._match_rule = self._match_rule, None
        if not rule or self._bus is None:
            return
        try:
            await self._bus.call(
                Message(
                    destination="org.freedesktop.DBus",
                    path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus",
                    member="RemoveMatch",
                    signature="s",
                    body=[rule],
                )
            )
        except Exception:
            pass

    def _set_heart_rate(self, value: int):
        try:
            self.bridge.state.heart_rate = int(value)
        except Exception:
            pass

    def _on_message(self, message) -> bool:
        if message.message_type != MessageType.SIGNAL:
            return False
        if (
            message.interface != PROPERTIES_IFACE
            or message.member != "PropertiesChanged"
            or message.path != self._char_path
        ):
            return False
        if len(message.body) < 2:
            return False
        changed = message.body[1] or {}
        raw = changed.get("Value")
        if raw is None:
            return False
        hr = decode_heart_rate(raw.value if isinstance(raw, Variant) else raw)
        if hr is None:
            return False
        first = self._last_hr == 0
        self._last_hr = hr
        self._last_seen = time.monotonic()
        if first:
            log.info(
                "Heart rate from %s: %d bpm",
                self._info.get("name") or self._info.get("address"),
                hr,
            )
        self._set_heart_rate(hr)
        return False
