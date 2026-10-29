"""ANT+ FE-C (Fitness Equipment - Control) backend.

The bridge acts as an ANT+ FE-C *trainer* (master channel, device type 17):

* it broadcasts pages 16 (General FE Data), 17 (General Settings),
  25 (Specific Trainer Data) and 54 (FE Capabilities);
* it accepts the control pages 48 (Basic Resistance), 49 (Target Power),
  50 (Wind Resistance) and 51 (Track Resistance) sent by a head unit or app;
* it answers control pages with page 71 (Command Status).

The page codecs and :class:`FECPageBuilder` in this module are pure functions
and plain objects, so they can be validated without an ANT radio.
:class:`FECDevice` wires them to the optional ``openant`` package (install with
``uv sync --extra ant``). Without a stick or without ``openant`` the backend
reports that it is unavailable instead of pretending to run.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from ..numbers import clamp

log = logging.getLogger(__name__)

try:  # pragma: no cover - depends on the optional ``ant`` extra
    from openant.devices.common import AntPlusDevice, DeviceType
    from openant.easy.node import Node

    OPENANT_AVAILABLE = True
    _OPENANT_IMPORT_ERROR: Optional[BaseException] = None
except Exception as exc:  # pragma: no cover - exercised on machines without openant
    AntPlusDevice = None  # type: ignore[assignment]
    DeviceType = None  # type: ignore[assignment]
    Node = None  # type: ignore[assignment]
    OPENANT_AVAILABLE = False
    _OPENANT_IMPORT_ERROR = exc


#: ANT+ Fitness Equipment device type.
DEVICE_TYPE_FE_C = 17
#: FE-C channel period (8192 / 32768 s ~= 4 Hz).
CHANNEL_PERIOD = 8192
#: ANT+ RF frequency for the public network (2457 MHz).
RF_FREQUENCY = 57
#: ANT+ public network key.
ANTPLUS_NETWORK_KEY = [0xB9, 0xA5, 0x21, 0xFB, 0xBD, 0x72, 0xC3, 0x45]

# Data pages transmitted by the trainer.
PAGE_GENERAL_FE = 16
PAGE_GENERAL_SETTINGS = 17
PAGE_SPECIFIC_TRAINER = 25
PAGE_FE_CAPABILITIES = 54
PAGE_COMMAND_STATUS = 71

# Control pages (received from the head unit).
PAGE_BASIC_RESISTANCE = 48
PAGE_TARGET_POWER = 49
PAGE_WIND_RESISTANCE = 50
PAGE_TRACK_RESISTANCE = 51

EQUIPMENT_TYPE_TRAINER = 25
HR_INVALID = 0xFF
CADENCE_INVALID = 0xFF
INCLINE_INVALID = 0x7FFF

FE_STATE_READY = 2
FE_STATE_IN_USE = 3
FE_STATE_FINISHED = 4

#: Page 16 byte 7 bits 0-3: distance travelled is provided (virtual speed off).
CAPABILITIES_DISTANCE = 1 << 2
#: Page 54 byte 7: basic resistance, target power and simulation supported.
FE_CAPABILITIES_BASIC_RESISTANCE = 1 << 0
FE_CAPABILITIES_TARGET_POWER = 1 << 1
FE_CAPABILITIES_SIMULATION = 1 << 2
FE_CAPABILITIES_ALL = (
    FE_CAPABILITIES_BASIC_RESISTANCE
    | FE_CAPABILITIES_TARGET_POWER
    | FE_CAPABILITIES_SIMULATION
)

COMMAND_STATUS_PASS = 0x00
COMMAND_STATUS_FAIL = 0x01
COMMAND_STATUS_NOT_SUPPORTED = 0x02
COMMAND_STATUS_REJECTED = 0x03
COMMAND_STATUS_PENDING = 0x04
COMMAND_STATUS_UNINITIALISED = 0xFF

#: Command Status page sequence value before any control page was received.
COMMAND_SEQUENCE_INITIAL = 0xFF


def _clamp_int(value: int, low: int, high: int) -> int:
    """Clamp a value to a packet field range and truncate it to an integer.

    ANT+ pages are packed byte by byte, so unlike the general-purpose
    :func:`daum_bridge.numbers.clamp` this variant must return an ``int``.
    """
    return int(clamp(value, low, high))


def _state_byte(fe_state: int, lap_toggle: bool = False, capabilities: int = 0) -> int:
    """Pack capabilities, FE state and lap toggle into byte 7 of pages 16/17."""
    value = (capabilities & 0x0F) | ((fe_state & 0x07) << 4)
    if lap_toggle:
        value |= 0x80
    return value


def encode_general_fe_data(
    *,
    elapsed_time: float = 0.0,
    distance_m: float = 0.0,
    speed_mps: float = 0.0,
    heart_rate: Optional[int] = None,
    fe_state: int = FE_STATE_IN_USE,
    lap_toggle: bool = False,
    equipment_type: int = EQUIPMENT_TYPE_TRAINER,
    capabilities: int = CAPABILITIES_DISTANCE,
) -> bytes:
    """Encode page 16 (General FE Data).

    ``elapsed_time`` is seconds (0.25 s resolution), ``distance_m`` metres
    (8-bit rollover) and ``speed_mps`` metres per second (0.001 m/s).
    """
    speed_raw = _clamp_int(round(speed_mps * 1000.0), 0, 0xFFFF)
    hr = HR_INVALID if not heart_rate else _clamp_int(int(heart_rate), 0, 0xFE)
    return bytes(
        (
            PAGE_GENERAL_FE,
            equipment_type & 0xFF,
            int(elapsed_time * 4) & 0xFF,
            int(distance_m) & 0xFF,
            speed_raw & 0xFF,
            (speed_raw >> 8) & 0xFF,
            hr,
            _state_byte(fe_state, lap_toggle, capabilities),
        )
    )


def encode_general_settings(
    *,
    cycle_length: int = 0xFF,
    incline_percent: Optional[float] = None,
    resistance_percent: Optional[float] = None,
    fe_state: int = FE_STATE_IN_USE,
    lap_toggle: bool = False,
) -> bytes:
    """Encode page 17 (General Settings).

    Incline uses 0.01 % units (``0x7FFF`` = invalid); resistance uses 0.5 %
    units (``0xFF`` = invalid, 200 = 100 %).
    """
    if incline_percent is None:
        incline_raw = INCLINE_INVALID
    else:
        incline_raw = _clamp_int(round(incline_percent * 100.0), -32768, 32767) & 0xFFFF
    if resistance_percent is None:
        resistance_raw = 0xFF
    else:
        resistance_raw = _clamp_int(round(resistance_percent * 2.0), 0, 200)
    return bytes(
        (
            PAGE_GENERAL_SETTINGS,
            0xFF,
            0xFF,
            cycle_length & 0xFF,
            incline_raw & 0xFF,
            (incline_raw >> 8) & 0xFF,
            resistance_raw,
            _state_byte(fe_state, lap_toggle),
        )
    )


def encode_specific_trainer_data(
    *,
    event_count: int = 0,
    cadence: Optional[int] = 0,
    accumulated_power: int = 0,
    instant_power: int = 0,
    trainer_status: int = 0,
    target_power_limits: int = 0,
    fe_state: int = FE_STATE_IN_USE,
    lap_toggle: bool = False,
) -> bytes:
    """Encode page 25 (Specific Trainer Data).

    Instantaneous power uses 12 bits (bytes 5 and the low nibble of byte 6);
    the high nibble of byte 6 holds the trainer status and byte 7 holds the
    target-power-limits flag plus the FE state.
    """
    power_raw = _clamp_int(instant_power, 0, 0x0FFF)
    cadence_raw = CADENCE_INVALID if cadence is None else _clamp_int(cadence, 0, 0xFE)
    state_lap = fe_state & 0x07
    if lap_toggle:
        state_lap |= 0x08
    return bytes(
        (
            PAGE_SPECIFIC_TRAINER,
            event_count & 0xFF,
            cadence_raw,
            accumulated_power & 0xFF,
            (accumulated_power >> 8) & 0xFF,
            power_raw & 0xFF,
            ((power_raw >> 8) & 0x0F) | ((trainer_status & 0x0F) << 4),
            (target_power_limits & 0x0F) | (state_lap << 4),
        )
    )


def encode_fe_capabilities(
    *,
    max_resistance_n: int = 0xFFFF,
    capabilities: int = FE_CAPABILITIES_ALL,
) -> bytes:
    """Encode page 54 (FE Capabilities)."""
    max_resistance = _clamp_int(max_resistance_n, 0, 0xFFFF)
    return bytes(
        (
            PAGE_FE_CAPABILITIES,
            0xFF,
            0xFF,
            0xFF,
            0xFF,
            max_resistance & 0xFF,
            (max_resistance >> 8) & 0xFF,
            capabilities & 0xFF,
        )
    )


def encode_command_status(
    *,
    command_id: int = 0xFF,
    sequence: int = COMMAND_SEQUENCE_INITIAL,
    status: int = COMMAND_STATUS_UNINITIALISED,
    data: bytes = b"\xff\xff\xff\xff",
) -> bytes:
    """Encode page 71 (Command Status) for the last received control page."""
    payload = bytes(data)[:4].ljust(4, b"\xff")
    return bytes(
        (
            PAGE_COMMAND_STATUS,
            command_id & 0xFF,
            sequence & 0xFF,
            status & 0xFF,
        )
    ) + payload


def decode_control_page(data) -> Optional[dict]:
    """Decode an FE-C control page sent by a head unit.

    Returns ``None`` for pages the trainer does not handle. The returned dict
    always contains ``page`` and ``mode`` plus the decoded values.
    """
    raw = bytes(data or b"")
    if len(raw) < 8:
        return None
    page = raw[0]
    if page == PAGE_BASIC_RESISTANCE:
        resistance = None if raw[7] == 0xFF else raw[7] / 2.0
        return {
            "page": page,
            "mode": "basic_resistance",
            "resistance_percent": resistance,
        }
    if page == PAGE_TARGET_POWER:
        raw = raw[6] | (raw[7] << 8)
        return {
            "page": page,
            "mode": "target_power",
            "target_power_w": None if raw == 0xFFFF else raw / 4.0,
        }
    if page == PAGE_WIND_RESISTANCE:
        return {
            "page": page,
            "mode": "wind",
            "wind_resistance_kg_m": raw[5] * 0.01,
            "wind_speed_kmh": raw[6] - 127,
            "drafting_factor": raw[7] / 100.0,
        }
    if page == PAGE_TRACK_RESISTANCE:
        grade_raw = raw[5] | (raw[6] << 8)
        return {
            "page": page,
            "mode": "track",
            "grade_percent": None if grade_raw == 0xFFFF else grade_raw * 0.01 - 200.0,
            "crr": raw[7] * 0.00005,
        }
    return None


class FECPageBuilder:
    """Pure FE-C page state machine (works without ANT hardware).

    It turns the bridge state into the outbound pages 16/17/25/54 and turns
    inbound control pages into page 71 replies plus bridge callbacks. ``openant``
    drives it through :class:`FECDevice`; tests drive it directly.
    """

    def __init__(
        self,
        *,
        state_provider: Optional[Callable[[], object]] = None,
        on_control: Optional[Callable[[dict], None]] = None,
    ):
        self.state_provider = state_provider
        self.on_control = on_control

        self.power = 0
        self.cadence = 0
        self.speed_mps = 0.0
        self.total_distance_m = 0.0
        self.elapsed_time = 0
        self.heart_rate = 0
        self.fe_state = FE_STATE_READY

        self.event_count = 0
        self.accumulated_power = 0
        self.target_power_limits = 0
        self.max_resistance_n = 0xFFFF

        self.last_command = bytes([0xFF] * 8)
        self.last_command_id = 0xFF
        self.last_status = COMMAND_STATUS_UNINITIALISED
        self.command_sequence = COMMAND_SEQUENCE_INITIAL

    # -- outbound pages -----------------------------------------------------
    def refresh_from_state(self) -> None:
        """Copy the current bridge state into the FE-C fields."""
        provider = self.state_provider
        state = provider() if provider is not None else None
        if state is None:
            return
        try:
            self.power = max(0, int(getattr(state, "power", 0) or 0))
            self.cadence = max(0, int(getattr(state, "cadence", 0) or 0))
            speed_kmh = float(getattr(state, "speed", 0) or 0)
            self.speed_mps = max(0.0, speed_kmh / 3.6)
            self.total_distance_m = max(
                0.0, float(getattr(state, "total_distance", 0) or 0) * 1000.0
            )
            self.elapsed_time = max(0, int(getattr(state, "elapsed_time", 0) or 0))
            self.heart_rate = max(0, int(getattr(state, "heart_rate", 0) or 0))
            self.fe_state = (
                FE_STATE_IN_USE
                if bool(getattr(state, "connected", False))
                else FE_STATE_READY
            )
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("Could not refresh FE-C state: %s", exc)

    def next_page(self, slot: int) -> list:
        """Return the next outbound page for the given ``openant`` slot.

        ``openant`` reserves page counts 0 and 65 for the common manufacturer
        and product information pages, so this schedule avoids them. The
        returned value is a list of 8 ints because ``openant`` passes it to
        ``array.array('B', [channel] + payload)``.
        """
        self.refresh_from_state()
        if slot % 16 == 8:
            return list(encode_fe_capabilities(max_resistance_n=self.max_resistance_n))
        if slot % 8 == 4:
            return list(
                encode_general_settings(resistance_percent=None, fe_state=self.fe_state)
            )
        if slot % 2 == 0:
            return list(
                encode_general_fe_data(
                    elapsed_time=self.elapsed_time,
                    distance_m=self.total_distance_m,
                    speed_mps=self.speed_mps,
                    heart_rate=self.heart_rate,
                    fe_state=self.fe_state,
                )
            )
        return self._trainer_page()

    def _trainer_page(self) -> list:
        self.event_count = (self.event_count + 1) & 0xFF
        self.accumulated_power = (self.accumulated_power + self.power) & 0xFFFF
        return list(
            encode_specific_trainer_data(
                event_count=self.event_count,
                cadence=self.cadence,
                accumulated_power=self.accumulated_power,
                instant_power=self.power,
                target_power_limits=self.target_power_limits,
                fe_state=self.fe_state,
            )
        )

    # -- inbound control pages ---------------------------------------------
    def handle_ack(self, data) -> Optional[list]:
        """Decode an acknowledged request and return the page to broadcast.

        Returns ``None`` when the page needs no reply. Control pages are
        forwarded to ``on_control`` and always answered with page 71.
        """
        raw = bytes(data or b"")[:8]
        if len(raw) < 8:
            return None

        # Request Data Page (0x46) is used by head units to poll page 71.
        if raw[0] == 0x46:
            if raw[6] in (PAGE_COMMAND_STATUS, 0xFF):
                return list(self._command_status_page())
            return None

        control = decode_control_page(raw)
        if control is None:
            return None

        self.last_command = raw
        self.last_command_id = raw[0]
        self.command_sequence = (self.command_sequence + 1) & 0xFF
        status = COMMAND_STATUS_PASS

        mode = control.get("mode")
        if mode == "wind":
            # An ergometer cannot emulate wind; report it honestly instead
            # of silently ignoring the request.
            status = COMMAND_STATUS_NOT_SUPPORTED
            log.info("ANT+ FE-C wind resistance is not supported by the Daum bridge")
        elif self.on_control is not None:
            try:
                self.on_control(control)
            except Exception:
                log.exception("ANT+ FE-C control handler failed")
                status = COMMAND_STATUS_FAIL

        self.last_status = status
        return list(self._command_status_page())

    def _command_status_page(self) -> bytes:
        # Command Status echoes the last four bytes of the request, which is
        # what the FE-C profile defines for pages 48/49/50/51.
        return encode_command_status(
            command_id=self.last_command_id,
            sequence=self.command_sequence,
            status=self.last_status,
            data=self.last_command[4:8],
        )


if OPENANT_AVAILABLE:

    class FECDevice(FECPageBuilder, AntPlusDevice):  # type: ignore[misc,valid-type]
        """ANT+ FE-C trainer channel built on ``openant``.

        ``openant`` calls :meth:`on_tx_data` on every channel period; the
        returned page is broadcast. Control pages arrive through
        :meth:`on_ack_data` and are answered with page 71.
        """

        def __init__(
            self,
            node,
            *,
            device_id: int = 0,
            state_provider: Optional[Callable[[], object]] = None,
            on_control: Optional[Callable[[dict], None]] = None,
        ):
            AntPlusDevice.__init__(
                self,
                node,
                device_type=DeviceType.FitnessEquipment.value,
                device_id=device_id,
                period=CHANNEL_PERIOD,
                rf_freq=RF_FREQUENCY,
                name="FitnessEquipment",
                master=True,
            )
            FECPageBuilder.__init__(
                self, state_provider=state_provider, on_control=on_control
            )

        def on_tx_data(self) -> list:
            return self.next_page(self._page_count)

        def on_ack_data(self, data) -> Optional[list]:
            return self.handle_ack(data)


class ANTFEBackend:
    """Own the openant node and FE-C channel on a background thread."""

    def __init__(self, bridge, config):
        self.bridge = bridge
        self.config = config
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._node = None
        self._device = None
        self._last_error: Optional[str] = None
        ant_cfg = getattr(config, "ant", None)
        self._device_id = int(getattr(ant_cfg, "device_id", 0) or 0)
        self._network_key = self._parse_network_key(
            getattr(ant_cfg, "network_key", "") or ""
        )
        log.info("ANT+ FE-C backend initialized")

    @staticmethod
    def _parse_network_key(value: str) -> list:
        """Parse ``network_key`` ("B9 A5 ..." or "B9A5...") or use ANT+."""
        cleaned = (
            value.replace(",", " ").replace("0x", " ").replace("0X", " ").strip()
        )
        parts = cleaned.split() if " " in cleaned else (
            [cleaned[i : i + 2] for i in range(0, len(cleaned), 2)] if cleaned else []
        )
        if len(parts) == 8:
            try:
                key = [int(part, 16) for part in parts]
            except ValueError:
                log.warning("Invalid ant.network_key %r, using the ANT+ public key", value)
            else:
                if all(0 <= byte <= 0xFF for byte in key):
                    return key
        elif cleaned:
            log.warning("Invalid ant.network_key %r, using the ANT+ public key", value)
        return list(ANTPLUS_NETWORK_KEY)

    @property
    def available(self) -> bool:
        """True when the optional ``openant`` dependency is importable."""
        return OPENANT_AVAILABLE

    @property
    def running(self) -> bool:
        return self._running

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def start(self) -> bool:
        """Start the FE-C channel. Returns False when ``openant`` is missing."""
        if not OPENANT_AVAILABLE:
            self._last_error = (
                "openant is not installed; install it with 'uv sync --extra ant'"
            )
            log.warning("ANT+ FE-C backend cannot start: %s", self._last_error)
            return False
        if self._running:
            return True
        self._running = True
        self._last_error = None
        self._thread = threading.Thread(target=self._run, name="ant-fe", daemon=True)
        self._thread.start()
        log.info(
            "ANT+ FE-C backend started (device id %s)",
            self._device_id or "auto",
        )
        return True

    def _run(self):
        node = None
        try:
            node = Node()
            self._node = node
            node.set_network_key(0x00, self._network_key)
            self._device = FECDevice(
                node,
                device_id=self._device_id,
                state_provider=lambda: getattr(self.bridge, "state", None),
                on_control=self._on_control,
            )
            log.info(
                "ANT+ FE-C channel open (device type %d, id %d, %.1f Hz)",
                DEVICE_TYPE_FE_C,
                self._device_id,
                32768.0 / CHANNEL_PERIOD,
            )
            node.start()  # blocks until stop() is called
        except Exception as exc:
            self._last_error = str(exc)
            log.error("ANT+ FE-C backend failed: %s", exc)
        finally:
            self._running = False
            self._device = None
            self._node = None
            if node is not None:
                try:
                    node.stop()
                except Exception as exc:  # pragma: no cover - hardware dependent
                    log.debug("ANT node stop error: %s", exc)
            log.info("ANT+ FE-C backend stopped")

    def _on_control(self, control: dict) -> None:
        bridge = self.bridge
        if bridge is None:
            return
        mode = control.get("mode")
        if mode == "target_power":
            target = control.get("target_power_w")
            if target is None:
                log.info("ANT+ FE-C target power page marked invalid; ignored")
                return
            watts = round(target)
            log.info("ANT+ FE-C target power: %d W", watts)
            bridge.set_target_watt(watts)
        elif mode == "basic_resistance":
            percent = control.get("resistance_percent")
            if percent is not None:
                log.info("ANT+ FE-C basic resistance: %.1f %%", percent)
                bridge.set_resistance_percent(percent)
        elif mode == "track":
            grade = control.get("grade_percent")
            if grade is not None:
                log.info("ANT+ FE-C track resistance: grade %.2f %%", grade)
                bridge.set_grade_percent(grade)
        else:  # pragma: no cover - decode_control_page only returns known modes
            log.debug("Unhandled ANT+ FE-C control page: %s", control)

    def stop(self):
        self._running = False
        node = self._node
        if node is not None:
            try:
                node.stop()
            except Exception as exc:  # pragma: no cover - hardware dependent
                log.debug("ANT node stop error: %s", exc)
        thread = self._thread
        if thread is not None:
            try:
                thread.join(timeout=3)
            except Exception:
                pass
        self._thread = None
        self._device = None
        self._node = None
        log.info("ANT+ FE-C backend stopped")
