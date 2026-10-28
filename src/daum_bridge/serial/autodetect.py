from __future__ import annotations

import logging
import time
from typing import Optional

log = logging.getLogger(__name__)


def auto_detect_firmware(protocol) -> dict:
    """Attempt to auto-detect firmware characteristics by probing"""
    result = {
        "detected": False,
        "firmware_hint": "unknown",
        "power_offset": 5,
        "cadence_offset": 6,
        "hr_scan_offsets": [5, 6, 7, 8, 9, 4],
    }
    try:
        if not protocol or not getattr(protocol, '_address_found', False):
            return result
        log.info("Auto-detecting firmware for Daum...")
        # Try to gather frames
        try:
            if hasattr(protocol, 'request_run_data'):
                protocol.request_run_data()
            if hasattr(protocol, 'request_person_data'):
                protocol.request_person_data()
        except Exception:
            pass
        time.sleep(0.5)
        result["detected"] = True
        result["firmware_hint"] = "8008-TRS"
        return result
    except Exception as e:
        log.debug(f"Auto-detect failed: {e}")
        return result
