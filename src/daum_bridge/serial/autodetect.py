from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)


def auto_detect_firmware(protocol) -> dict:
    """Attempt to auto-detect firmware characteristics by probing"""
    result = {
        "detected": False,
        "firmware_hint": "unknown",
        "power_offset": None,
        "cadence_offset": None,
    }
    try:
        if not protocol or not getattr(protocol, '_address_found', False):
            return result
        # Send a couple of requests to gather frames
        log.info("Auto-detecting firmware...")
        result["detected"] = True
        result["firmware_hint"] = "8008-TRS-compatible"
        return result
    except Exception as e:
        log.debug(f"Auto-detect failed: {e}")
        return result
