"""Discovery helpers for the USB serial adapter behind the Daum cockpit.

The Daum 8008 TRS speaks RS232 over its original cable, which reaches the
computer through an RS232-to-USB adapter. Those adapters do not announce
themselves in a standardised way, so :func:`auto_detect_daum_port` applies a
name-based heuristic and falls back to the first available port. Users whose
adapter is not recognised can always pin the port in ``config.yaml``
(``serial.port``) and skip detection entirely.
"""

from __future__ import annotations

import logging
from typing import Optional

import serial
from serial.tools import list_ports

log = logging.getLogger(__name__)


def list_serial_ports():
    ports = []
    for p in list_ports.comports():
        ports.append({
            "device": p.device,
            "description": p.description,
            "hwid": p.hwid,
        })
    return ports


def auto_detect_daum_port() -> Optional[str]:
    """Try to auto-detect Daum 8008 TRS serial port.
    Heuristic based on common USB-serial adapters; may need adjustment.
    """
    ports = list_serial_ports()
    # Prefer ports with common adapter names
    for p in ports:
        dev = p["device"]
        desc = (p["description"] or "").lower()
        hwid = (p["hwid"] or "").lower()
        if any(x in desc for x in ["prolific", "ftdi", "ch340", "cp210", "usb-serial"]):
            log.debug("Candidate port %s: %s %s", dev, desc, hwid)
            return dev
    # Fallback to first available
    if ports:
        return ports[0]["device"]
    return None


def open_serial(port: str, baudrate: int = 9600, timeout: float = 1.0, bytesize: int = 8, parity: str = "N", stopbits: int = 1):
    return serial.Serial(
        port=port,
        baudrate=baudrate,
        bytesize=bytesize,
        parity=parity,
        stopbits=stopbits,
        timeout=timeout,
    )
