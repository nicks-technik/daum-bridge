"""Daum 8008 TRS serial protocol implementation.
Based on daumUSB.js analysis from weinzmi/daumUSB2BLE.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

log = logging.getLogger(__name__)


class DaumCmd(Enum):
    GET_ADDRESS = 0xA1
    GET_PERSON_DATA = 0xA2
    RUN_DATA = 0xA4
    SET_WATT = 0xA6
    SET_GEAR = 0xA7
    SET_PROG = 0xA9
    SET_WATT_PROFILE = 0xAA


@dataclass
class DaumState:
    power: float = 0.0  # watts
    cadence: float = 0.0  # rpm
    speed: float = 0.0
    distance: float = 0.0
    elapsed_time: int = 0
    gear: int = 1
    heart_rate: int = 0
    program: int = 0
    connected: bool = False
    cockpit_address: Optional[int] = None
    resistance_level: int = 0
    total_distance: float = 0.0


class DaumProtocol:
    def __init__(self, serial_port, log_raw: bool = False):
        self.ser = serial_port
        self.log_raw = log_raw
        self.state = DaumState()
        self._address = None
        self._address_found = False
        self._last_data_time = 0.0
        self._buffer = bytearray()
        self._frames_seen = []
        self._raw_log = []

    def _write(self, data: bytes):
        if self.log_raw:
            log.debug("TX: %s", data.hex())
        try:
            self.ser.write(data)
            self.ser.flush()
        except Exception as e:
            log.error("Serial write error: %s", e)

    def _read_available(self) -> bytes:
        try:
            if hasattr(self.ser, "in_waiting") and self.ser.in_waiting:
                data = self.ser.read(self.ser.in_waiting)
                if data:
                    self._buffer.extend(data)
                    if self.log_raw:
                        self._raw_log.append(data)
                        if len(self._raw_log) > 1000:
                            self._raw_log = self._raw_log[-1000:]
                return data
            return b""
        except Exception as e:
            log.error("Serial read error: %s", e)
            return b""

    def build_command(self, cmd: DaumCmd, address: Optional[int] = None, data: Optional[int] = None) -> bytes:
        if cmd == DaumCmd.GET_ADDRESS:
            return bytes([cmd.value])
        if address is None:
            address = self._address if self._address is not None else 0
        if data is None or data == 0 and cmd not in (DaumCmd.SET_WATT, DaumCmd.SET_GEAR, DaumCmd.SET_PROG, DaumCmd.SET_WATT_PROFILE):
            # For simple commands without data
            return bytes([cmd.value, address & 0xFF])
        else:
            return bytes([cmd.value, address & 0xFF, int(data) & 0xFF])

    def request_address(self):
        log.info("Requesting Daum cockpit address...")
        self._write(self.build_command(DaumCmd.GET_ADDRESS))

    def request_person_data(self):
        if not self._address_found or self._address is None:
            return
        try:
            self._write(self.build_command(DaumCmd.GET_PERSON_DATA, self._address))
        except Exception as e:
            log.debug(f"request_person_data error: {e}")

    def request_run_data(self):
        if not self._address_found or self._address is None:
            return
        try:
            self._write(self.build_command(DaumCmd.RUN_DATA, self._address))
        except Exception as e:
            log.debug(f"request_run_data error: {e}")

    def set_watt(self, watts: int):
        if not self._address_found or self._address is None:
            log.debug("Cannot set watt - no address")
            return
        watts = max(0, int(watts))
        watts = min(800, watts)
        self._write(self.build_command(DaumCmd.SET_WATT, self._address, watts))

    def set_gear(self, gear: int):
        if not self._address_found or self._address is None:
            log.debug("Cannot set gear - no address")
            return
        gear = max(1, int(gear))
        try:
            self._write(self.build_command(DaumCmd.SET_GEAR, self._address, gear))
        except Exception as e:
            log.debug(f"set_gear error: {e}")

    def set_program(self, program: int):
        if not self._address_found or self._address is None:
            log.debug("Cannot set program - no address")
            return
        self._write(self.build_command(DaumCmd.SET_PROG, self._address, int(program)))

    def parse(self, data: bytes) -> bool:
        if not data:
            return False
        if self.log_raw:
            log.debug("RX: %s", data.hex())
        self._buffer.extend(data)
        states = list(self._buffer)
        n = len(states)
        i = 0
        consumed = 0
        while i < n:
            b = states[i]
            # Address discovery
            if b == 0xA1 and not self._address_found and i + 1 < n:
                addr = states[i + 1]
                self._address = addr
                self._address_found = True
                self.state.cockpit_address = addr
                self.state.connected = True
                log.info("Found Daum cockpit address: 0x%02X", addr)
                consumed = max(consumed, i + 2)
                i += 2
                continue
            # Person data
            if self._address_found and self._address is not None and b == 0xA2 and i + 2 < n:
                addr_byte = states[i + 1]
                try:
                    if addr_byte == self._address:
                        idx = i
                        for off in [5, 6, 7, 8, 9, 4, 10]:
                            if idx + off < n:
                                hr = states[idx + off]
                                if isinstance(hr, int) and 40 <= hr <= 220:
                                    self.state.heart_rate = int(hr)
                                    break
                        consumed = max(consumed, i + 12)
                        i += 1
                        continue
                except Exception:
                    pass
            # run_data
            if self._address_found and self._address is not None and b == 0xA4 and i + 2 < n:
                addr_byte = states[i + 1]
                try:
                    if addr_byte == self._address and states[i + 2] == 0:
                        idx = i
                        try:
                            if idx + 6 < n:
                                rpm = states[idx + 6]
                                if isinstance(rpm, int) and 0 <= rpm <= 200:
                                    self.state.cadence = float(rpm)
                            if idx + 5 < n:
                                power_raw = states[idx + 5]
                                if isinstance(power_raw, int):
                                    if self.state.cadence == 0 or power_raw == 0:
                                        self.state.power = 0.0
                                    else:
                                        self.state.power = float(power_raw) * 5.0
                            if idx + 16 < n:
                                gear = states[idx + 16]
                                if isinstance(gear, int) and 1 <= gear <= 28:
                                    self.state.gear = gear
                            if idx + 7 < n:
                                spd = states[idx + 7]
                                if isinstance(spd, int) and 0 <= spd <= 150:
                                    self.state.speed = float(spd)
                            if idx + 10 < n:
                                dist = states[idx + 10]
                                if isinstance(dist, int) and 0 <= dist <= 9999:
                                    self.state.total_distance = float(dist) / 10.0
                            if idx + 12 < n:
                                t = states[idx + 12]
                                if isinstance(t, int) and 0 <= t <= 9999:
                                    self.state.elapsed_time = int(t)
                            if idx + 2 < n:
                                program = states[idx + 2]
                                if isinstance(program, int):
                                    self.state.program = program
                            self.state.connected = True
                            self._last_data_time = time.time()
                        except Exception as ex:
                            log.debug("Error extracting run data: %s", ex)
                        consumed = max(consumed, i + 20)
                        i += 1
                        continue
                except Exception:
                    pass
            i += 1
        if consumed > 0 and consumed <= len(self._buffer):
            del self._buffer[:consumed]
        elif consumed == 0 and len(self._buffer) > 512:
            self._buffer.clear()
        self._last_data_time = time.time()
        return self._address_found
