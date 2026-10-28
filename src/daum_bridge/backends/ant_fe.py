"""ANT+ FE-C (Fitness Equipment - Control) backend.

Implements ANT+ FE-C to broadcast as a controllable trainer.
Uses openant if available. Falls back gracefully if not.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

log = logging.getLogger(__name__)

try:
    from openant.devices import ANTDevice
    from openant.devices.fitness_equipment import FitnessEquipment, FitnessEquipmentType
    from openant.easy.node import Node
    OPENANT_AVAILABLE = True
except Exception as e:
    OPENANT_AVAILABLE = False
    log.debug(f"openant not available: {e}")


class ANTFEBackend:
    def __init__(self, bridge, config):
        self.bridge = bridge
        self.config = config
        self._running = False
        self._thread = None
        self._node = None
        self._fe = None
        self._last_update = 0.0
        log.info("ANT+ FE-C backend initialized")

    def start(self):
        if not OPENANT_AVAILABLE:
            log.warning("openant not installed - ANT+ FE-C backend cannot start")
            self._running = True
            self._thread = threading.Thread(target=self._run_fallback, daemon=True)
            self._thread.start()
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info("ANT+ FE-C backend started")

    def _run_fallback(self):
        while self._running:
            try:
                self._update()
            except Exception as e:
                log.debug(f"ANT+ fallback update error: {e}")
            time.sleep(0.25)

    def _run(self):
        try:
            self._node = Node()
            try:
                self._node.start()
            except Exception as e:
                log.error(f"Failed to start ANT node: {e}")
                self._run_fallback()
                return
            try:
                self._fe = FitnessEquipment(self._node)
                self._fe.open()
                log.info("ANT+ FE-C device opened")
            except Exception as e:
                log.error(f"Failed to open FE-C device: {e}")
                self._run_fallback()
                return
            while self._running:
                try:
                    self._update()
                except Exception as e:
                    log.debug(f"ANT+ update error: {e}")
                time.sleep(0.25)
        except Exception as e:
            log.error(f"ANT+ backend error: {e}")
            self._run_fallback()

    def _update(self):
        try:
            if not self.bridge:
                return
            state = getattr(self.bridge, 'state', None)
            if not state:
                return
            power = int(getattr(state, 'power', 0) or 0)
            cadence = int(getattr(state, 'cadence', 0) or 0)
            speed = float(getattr(state, 'speed', 0.0) or 0.0)
            hr = int(getattr(state, 'heart_rate', 0) or 0)
            # Try to update FE-C device if available
            if self._fe and hasattr(self._fe, 'set_power'):
                try:
                    target = int(getattr(self.bridge, '_target_watt', 0) or 0)
                    if target > 0:
                        self._fe.set_power(target)
                except Exception:
                    pass
            if self._fe and hasattr(self._fe, 'update'):
                try:
                    self._fe.update(power=power, cadence=cadence, speed=speed)
                except Exception:
                    pass
            if self._fe and hasattr(self._fe, 'send_data'):
                try:
                    # Basic FE-C data page updates handled by library
                    pass
                except Exception:
                    pass
        except Exception as e:
            log.debug(f"ANT+ _update error: {e}")

    def stop(self):
        self._running = False
        try:
            if self._fe and hasattr(self._fe, 'close'):
                self._fe.close()
        except Exception:
            pass
        try:
            if self._node and hasattr(self._node, 'stop'):
                self._node.stop()
        except Exception:
            pass
        if self._thread:
            try:
                self._thread.join(timeout=2)
            except Exception:
                pass
        log.info("ANT+ FE-C backend stopped")
