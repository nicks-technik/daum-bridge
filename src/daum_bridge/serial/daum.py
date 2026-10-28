"""Daum 8008 TRS serial protocol implementation.
Based on daumUSB.js analysis from weinzmi/daumUSB2BLE.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

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
    gear: int = 1
    heart_rate: int = 0
    program: int = 0
    connected: bool = False
    cockpit_address: Optional[int] = None


class DaumProtocol:
    def __init__(self, serial_port, log_raw: bool = False):
        self.ser = serial_port
        self.log_raw = log_raw
        self.state = DaumState()
        self._address = None
        self._address_found = False
        self._last_data_time = 0.0

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
                return self.ser.read(self.ser.in_waiting)
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
        self._write(self.build_command(DaumCmd.GET_PERSON_DATA, self._address))

    def request_run_data(self):
        if not self._address_found or self._address is None:
            return
        self._write(self.build_command(DaumCmd.RUN_DATA, self._address))

    def set_watt(self, watts: int):
        if not self._address_found or self._address is None:
            log.debug("Cannot set watt - no address")
            return
        watts = max(0, int(watts))
        self._write(self.build_command(DaumCmd.SET_WATT, self._address, watts))

    def set_gear(self, gear: int):
        if not self._address_found or self._address is None:
            log.debug("Cannot set gear - no address")
            return
        gear = max(1, int(gear))
        self._write(self.build_command(DaumCmd.SET_GEAR, self._address, gear))

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
        # Parsing based on daumUSB.js logic
        states = list(data)
        n = len(states)
        i = 0
        while i < n:
            b = states[i]
            # Address discovery: look for 0xA1 followed by address
            if b == 0xA1 and not self._address_found and i + 1 < n:
                addr = states[i + 1]
                self._address = addr
                self._address_found = True
                self.state.cockpit_address = addr
                self.state.connected = True
                log.info("Found Daum cockpit address: 0x%02X", addr)
                i += 2
                continue
            # Person data (heart rate) - 0xA2
            if self._address_found and self._address is not None and b == 0xA2 and i + 2 < n:
                addr_byte = states[i + 1]
                try:
                    if addr_byte == self._address:
                        idx = i
                        # Try common offsets for HR in person data
                        for off in [5, 6, 7, 8, 9, 4]:
                            if idx + off < n:
                                hr = states[idx + off]
                                if isinstance(hr, int) and 40 <= hr <= 220:
                                    self.state.heart_rate = int(hr)
                                    break
                        i += 1
                        continue
                except Exception:
                    pass
            # run_data parsing when address found
            if self._address_found and self._address is not None and b == 0xA4 and i + 2 < n:
                addr_byte = states[i + 1]
                # Check if address matches
                try:
                    if addr_byte == self._address and states[i + 2] == 0:
                        idx = i
                        try:
                            # RPM/Cadence at offset +6
                            if idx + 6 < n:
                                rpm = states[idx + 6]
                                if isinstance(rpm, int) and 0 <= rpm <= 200:
                                    self.state.cadence = float(rpm)
                            # Power at offset +5
                            if idx + 5 < n:
                                power_raw = states[idx + 5]
                                if isinstance(power_raw, int):
                                    if self.state.cadence == 0 or power_raw == 0:
                                        self.state.power = 0.0
                                    else:
                                        self.state.power = float(power_raw) * 5.0
                            # Gear at offset +16
                            if idx + 16 < n:
                                gear = states[idx + 16]
                                if isinstance(gear, int) and 1 <= gear <= 28:
                                    self.state.gear = gear
                            # Program at offset +2
                            if idx + 2 < n:
                                program = states[idx + 2]
                                if isinstance(program, int):
                                    self.state.program = program
                            self.state.connected = True
                            self._last_data_time = time.time()
                        except Exception as ex:
                            log.debug("Error extracting run data: %s", ex)
                        i += 1
                        continue
                except Exception:
                    pass
            i += 1
        self._last_data_time = time.time()
        return self._address_found
