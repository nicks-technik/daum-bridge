from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Callable, Optional

from .serial.daum import DaumProtocol, DaumState
from .serial.port import auto_detect_daum_port, open_serial

log = logging.getLogger(__name__)


class DaumBridge:
    def __init__(self, config):
        self.config = config
        self.serial_port = None
        self.protocol: Optional[DaumProtocol] = None
        self.state = DaumState()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callbacks = []
        self._target_watt = 0
        self._target_gear = 1
        self._ble_backend = None
        self._ble_loop = None
        self._ble_thread = None
        self._ant_backend = None
        self._erg_control_granted = False
        self._last_target_set = 0.0
        self._consecutive_errors = 0
        self._last_reconnect = 0.0
        self._client_connected = False
        self._app_connected = False
        self._virtual_shifting_enabled = True
        self._start_time = time.time()
        self._serial_connected_time = None
        self._app_connected_time = None
        self._erg_retry_count = 0
        self._last_erg_attempt = 0.0

    def add_state_callback(self, cb: Callable[[DaumState], None]):
        self._callbacks.append(cb)

    def _notify(self):
        for cb in self._callbacks:
            try:
                cb(self.state)
            except Exception as e:
                log.debug("Callback error: %s", e)

    def connect(self):
        cfg = self.config.serial
        port = cfg.port or auto_detect_daum_port()
        if not port:
            raise RuntimeError("No serial port found")
        log.info("Opening serial port %s", port)
        try:
            self.serial_port = open_serial(port, cfg.baudrate, cfg.timeout, cfg.bytesize, cfg.parity, cfg.stopbits)
            self.protocol = DaumProtocol(self.serial_port, log_raw=getattr(self.config.logging, 'log_raw_frames', False))
        except Exception as e:
            log.error(f"Failed to open serial port {port}: {e}")
            raise
        return self

    def start(self):
        if not self.protocol:
            self.connect()
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        log.info("Bridge started")
        # Start BLE backend if enabled
        try:
            if getattr(self.config, "ble", None) and getattr(self.config.ble, "enabled", False):
                from .backends.ble_ftms import BLEFTMSBackend
                self._ble_backend = BLEFTMSBackend(self, self.config)
                def _run_ble():
                    loop = asyncio.new_event_loop()
                    self._ble_loop = loop
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(self._ble_backend.start())
                    except Exception as e:
                        log.error("BLE backend error: %s", e)
                    finally:
                        try:
                            loop.close()
                        except Exception:
                            pass
                self._ble_thread = threading.Thread(target=_run_ble, daemon=True)
                self._ble_thread.start()
        except Exception as e:
            log.warning("Failed to start BLE backend: %s", e)
        # Start ANT+ backend if enabled
        try:
            if getattr(self.config, "ant", None) and getattr(self.config.ant, "enabled", False):
                from .backends.ant_fe import ANTFEBackend
                self._ant_backend = ANTFEBackend(self, self.config)
                try:
                    self._ant_backend.start()
                except Exception as e:
                    log.warning("Failed to start ANT+ backend: %s", e)
        except Exception as e:
            log.debug("ANT+ backend not started: %s", e)

    def stop(self):
        self._running = False
        if self._thread:
            try:
                self._thread.join(timeout=2)
            except Exception:
                pass
        try:
            if self._ble_backend:
                if self._ble_loop and self._ble_loop.is_running():
                    try:
                        fut = asyncio.run_coroutine_threadsafe(self._ble_backend.stop(), self._ble_loop)
                        fut.result(timeout=2)
                    except Exception as e:
                        log.debug("BLE stop error: %s", e)
        except Exception as e:
            log.debug("BLE stop error: %s", e)
        try:
            if self.serial_port and hasattr(self.serial_port, 'is_open') and self.serial_port.is_open:
                self.serial_port.close()
        except Exception:
            pass
        log.info("Bridge stopped")

    def _run_loop(self):
        if not self.protocol:
            try:
                self.connect()
            except Exception as e:
                log.error(f"Initial connect failed: {e}")
        assert self.protocol is not None
        try:
            self.protocol.request_address()
        except Exception as e:
            log.debug(f"Initial address request error: {e}")
        last_run_data = 0.0
        last_addr_req = time.time()
        last_watt_apply = 0.0
        last_target_watt_sent = -1
        last_health_check = time.time()
        while self._running:
            try:
                # Read
                try:
                    data = self.protocol._read_available()
                    if data:
                        self.protocol.parse(data)
                        self.state = self.protocol.state
                        self._consecutive_errors = 0
                        self._notify()
                except Exception as e:
                    self._consecutive_errors += 1
                    log.debug(f"Serial read/parse error: {e}")
                # Discovery/reconnect
                if not getattr(self.protocol, '_address_found', False):
                    if time.time() - last_addr_req > 2.0:
                        try:
                            self.protocol.request_address()
                            last_addr_req = time.time()
                        except Exception as e:
                            log.debug(f"Address request error: {e}")
                            self._consecutive_errors += 1
                else:
                    if self._serial_connected_time is None:
                        self._serial_connected_time = time.time()
                    # Poll run data
                    if time.time() - last_run_data > getattr(self.config.bridge, 'poll_interval', 0.5):
                        try:
                            self.protocol.request_run_data()
                            self.protocol.request_person_data()
                            last_run_data = time.time()
                            self._consecutive_errors = 0
                        except Exception as e:
                            log.debug(f"Run data request error: {e}")
                            self._consecutive_errors += 1
                    # Re-apply target watt aggressively for ERG with auto-engage fallback
                    if self._target_watt >= 0:
                        interval = 0.4 if self._erg_control_granted else 0.8
                        if time.time() - last_watt_apply > interval:
                            try:
                                if self._target_watt > 0 and not self._erg_control_granted and time.time() - self._last_erg_attempt > 3.0 and self._erg_retry_count < 5:
                                    try:
                                        if hasattr(self.protocol, 'set_program'):
                                            self.protocol.set_program(1)
                                    except Exception:
                                        pass
                                    self._last_erg_attempt = time.time()
                                    self._erg_retry_count += 1
                                if last_target_watt_sent != self._target_watt:
                                    self.protocol.set_watt(self._target_watt)
                                    last_target_watt_sent = self._target_watt
                                    self._last_target_set = time.time()
                                else:
                                    self.protocol.set_watt(self._target_watt)
                                    self._last_target_set = time.time()
                                last_watt_apply = time.time()
                            except Exception as e:
                                log.debug(f"Re-apply watt error: {e}")
                # Health check & auto-reconnect
                if self._consecutive_errors > 15 and time.time() - self._last_reconnect > 3.0:
                    log.warning("Too many serial errors, attempting reconnect...")
                    try:
                        if self.serial_port and hasattr(self.serial_port, 'close'):
                            try:
                                self.serial_port.close()
                            except Exception:
                                pass
                    except Exception:
                        pass
                    self.protocol = None
                    self.serial_port = None
                    try:
                        self.connect()
                        if self.protocol:
                            try:
                                self.protocol.request_address()
                            except Exception:
                                pass
                        self._consecutive_errors = 0
                        self._last_reconnect = time.time()
                        log.info("Reconnected successfully")
                    except Exception as e:
                        log.error(f"Reconnect failed: {e}")
                        self._last_reconnect = time.time()
                time.sleep(0.01)
            except Exception as e:
                log.error("Bridge loop error: %s", e)
                self._consecutive_errors += 1
                time.sleep(getattr(self.config.bridge, 'reconnect_delay', 2.0))

    def set_target_watt(self, watts: int):
        self._target_watt = max(0, min(800, int(watts)))
        if self._target_watt > 0:
            self._last_erg_attempt = time.time()
        if self.protocol and getattr(self.protocol, '_address_found', False):
            try:
                self.protocol.set_watt(self._target_watt)
                self._last_target_set = time.time()
            except Exception as e:
                log.debug("set_watt error: %s", e)

    def shift_up(self):
        self._target_gear = max(1, self._target_gear + 1)
        if self.protocol and self.protocol._address_found:
            try:
                self.protocol.set_gear(self._target_gear)
            except Exception as e:
                log.debug("set_gear error: %s", e)

    def shift_down(self):
        self._target_gear = max(1, self._target_gear - 1)
        if self.protocol and self.protocol._address_found:
            try:
                self.protocol.set_gear(self._target_gear)
            except Exception as e:
                log.debug("set_gear error: %s", e)

    def set_gear(self, gear: int):
        self._target_gear = max(1, int(gear))
        if self.protocol and getattr(self.protocol, '_address_found', False):
            try:
                self.protocol.set_gear(self._target_gear)
                self._last_target_set = time.time()
            except Exception as e:
                log.debug("set_gear error: %s", e)
