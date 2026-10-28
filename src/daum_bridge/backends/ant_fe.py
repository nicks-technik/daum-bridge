"""ANT+ FE-C (Fitness Equipment - Control) backend.

This is a placeholder implementation for ANT+ support. For full ANT+ FE-C support,
you need a USB ANT+ stick (e.g., Garmin ANT+ USB stick) and libraries like openant
or pyant. The Daum 8008 TRS can be bridged via serial as before, and this backend
would broadcast as an ANT+ FE-C trainer to apps that prefer ANT+.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

log = logging.getLogger(__name__)


class ANTFEBackend:
    def __init__(self, bridge, config):
        self.bridge = bridge
        self.config = config
        self._running = False
        self._thread = None
        log.info("ANT+ FE-C backend initialized (placeholder)")

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info("ANT+ FE-C backend started (placeholder - no ANT+ hardware support yet)")

    def _run(self):
        import time
        while self._running:
            time.sleep(1)

    def stop(self):
        self._running = False
        if self._thread:
            try:
                self._thread.join(timeout=2)
            except Exception:
                pass
        log.info("ANT+ FE-C backend stopped")
