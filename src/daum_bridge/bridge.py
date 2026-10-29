from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .serial.daum import DaumProtocol, DaumState
from .serial.port import auto_detect_daum_port, open_serial

log = logging.getLogger(__name__)


class DaumBridge:
    #: Seconds between recorded trackpoints (used for Strava/TCX export).
    SAMPLE_INTERVAL = 1.0
    #: Hard limit for in-memory samples (~27 h at 1 Hz).
    MAX_SAMPLES = 100_000

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
        self._target_resistance_pct = 0.0
        self._target_grade_pct: Optional[float] = None
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
        self._logs = []
        self._ride_history = []
        self._current_ride = None
        self._ride_start = None
        self._ride_work = 0.0
        self._last_power_time = None
        self._ride_max_power = 0.0
        self._ride_avg_power = 0.0
        self._ride_power_sum = 0.0
        self._ride_power_count = 0
        self._ride_samples = []
        self._last_sample_time = 0.0
        self._ride_paused = False
        self._ride_hr_sum = 0.0
        self._ride_hr_count = 0
        self._ride_max_hr = 0.0
        self._ride_cadence_sum = 0.0
        self._ride_cadence_count = 0
        self._ride_distance = 0.0
        self._last_odometer = None
        self._last_strava_result = None
        self._last_email_result = None
        self._strava_thread = None
        self._email_thread = None
        self._inputs = []
        self._input_problems = []
        self._last_shift_source: Optional[str] = None
        self._last_shift_at = 0.0


    def add_state_callback(self, cb: Callable[[DaumState], None]):
        self._callbacks.append(cb)

    def _notify(self):
        for cb in self._callbacks:
            try:
                cb(self.state)
            except Exception as e:
                log.debug("Callback error: %s", e)
        try:
            self._update_ride_stats()
        except Exception:
            pass

    def _update_ride_stats(self):
        try:
            connected = bool(getattr(self.state, "connected", False))
            if not connected:
                # Re-arm recording for the next session after a manual finish.
                self._ride_paused = False
            if self._ride_paused:
                return
            if self._current_ride is None:
                if not connected:
                    return
                self._start_ride()
            if not connected:
                self.finish_ride()
                return

            now = time.time()
            dt = (now - self._last_power_time) if self._last_power_time else 0.0
            power = max(0.0, float(getattr(self.state, 'power', 0) or 0))
            if power > 0 and 0 < dt < 5:
                self._ride_work += power * dt / 3600.0  # kJ
            self._last_power_time = now
            self._ride_max_power = max(self._ride_max_power, power)
            self._ride_power_sum += power
            self._ride_power_count += 1
            self._ride_avg_power = self._ride_power_sum / self._ride_power_count

            heart_rate = float(getattr(self.state, 'heart_rate', 0) or 0)
            if heart_rate > 0:
                self._ride_hr_sum += heart_rate
                self._ride_hr_count += 1
                self._ride_max_hr = max(self._ride_max_hr, heart_rate)
            cadence = max(0.0, float(getattr(self.state, 'cadence', 0) or 0))
            if cadence > 0:
                self._ride_cadence_sum += cadence
                self._ride_cadence_count += 1

            self._update_ride_distance(dt)
            self._record_ride_sample(now, power, cadence, heart_rate)
        except Exception:
            pass

    def _start_ride(self):
        now = time.time()
        self._current_ride = now
        self._ride_start = now
        self._ride_work = 0.0
        self._last_power_time = now
        self._ride_max_power = 0.0
        self._ride_avg_power = 0.0
        self._ride_power_sum = 0.0
        self._ride_power_count = 0
        self._ride_samples = []
        self._last_sample_time = 0.0
        self._ride_hr_sum = 0.0
        self._ride_hr_count = 0
        self._ride_max_hr = 0.0
        self._ride_cadence_sum = 0.0
        self._ride_cadence_count = 0
        self._ride_distance = 0.0
        self._last_odometer = None
        log.info("Ride recording started")

    def _update_ride_distance(self, dt: float) -> float:
        """Track distance in km from the cockpit odometer, else from speed."""
        total = float(getattr(self.state, 'total_distance', 0) or 0)
        if total > 0:
            if self._last_odometer is None:
                self._last_odometer = total
            else:
                delta = total - self._last_odometer
                # Odometer has 0.1 km resolution; ignore resets/jumps.
                if 0 <= delta <= 2.0:
                    self._ride_distance += delta
                self._last_odometer = total
        else:
            speed = float(getattr(self.state, 'speed', 0) or 0)
            if 0 < speed < 120 and 0 < dt < 60:
                self._ride_distance += speed * dt / 3600.0
        return self._ride_distance

    def _record_ride_sample(self, now: float, power: float, cadence: float, heart_rate: float):
        if self._last_sample_time and now - self._last_sample_time < self.SAMPLE_INTERVAL:
            return
        self._last_sample_time = now
        if self._ride_samples and len(self._ride_samples) >= self.MAX_SAMPLES:
            del self._ride_samples[:1000]
        self._ride_samples.append({
            "t": round(now - (self._ride_start or now), 3),
            "power": round(power, 1),
            "cadence": round(cadence, 1),
            "speed": round(float(getattr(self.state, 'speed', 0) or 0), 1),
            "heart_rate": int(heart_rate),
            "distance": round(self._ride_distance, 3),
        })

    def finish_ride(self) -> Optional[dict]:
        """Finish and persist the current ride. Safe to call repeatedly."""
        if self._current_ride is None:
            return None
        end = time.time()
        start = self._ride_start or self._current_ride
        ride = {
            "start": start,
            "end": end,
            "duration": max(0.0, end - start),
            "distance": round(self._ride_distance, 2),
            "work_kj": round(self._ride_work, 2),
            "avg_power": round(self._ride_avg_power, 1),
            "max_power": round(self._ride_max_power, 1),
            "avg_heart_rate": round(self._ride_hr_sum / self._ride_hr_count, 1) if self._ride_hr_count else 0,
            "max_heart_rate": round(self._ride_max_hr, 1),
            "avg_cadence": round(self._ride_cadence_sum / self._ride_cadence_count, 1) if self._ride_cadence_count else 0,
            "samples": self._ride_samples,
        }
        summary = {k: v for k, v in ride.items() if k != "samples"}
        summary["sample_count"] = len(ride["samples"])
        try:
            from . import history
            ride["id"] = history.save_ride(ride)
            summary["id"] = ride["id"]
            self._export_ride_tcx(ride)
        except Exception as e:
            log.warning("Could not save ride history: %s", e)
        ride["id"] = ride.get("id") or summary.get("id")
        self._ride_history.append(summary)
        if len(self._ride_history) > 200:
            del self._ride_history[:-200]
        self._current_ride = None
        self._ride_start = None
        log.info(
            "Ride finished: %.1f km, %.0f W avg, %.0f kJ, %d samples",
            summary["distance"], summary["avg_power"], summary["work_kj"], summary["sample_count"],
        )
        self._maybe_auto_upload_strava(ride)
        self._maybe_email_ride(ride)
        return ride

    def _export_ride_tcx(self, ride: dict) -> Optional[Path]:
        """Write ``rides/<id>.tcx`` next to the JSON (ready for manual upload)."""
        ride_id = ride.get("id")
        if not ride_id:
            return None
        try:
            from . import history
            from .integrations.tcx import build_tcx
            target = history.rides_dir() / f"{ride_id}.tcx"
            target.write_text(build_tcx(ride), encoding="utf-8")
            log.info("Exported TCX %s", target)
            return target
        except Exception as e:
            log.warning("Could not export TCX for %s: %s", ride_id, e)
            return None

    def finish_current_ride(self) -> Optional[dict]:
        """Finish the ride now and pause recording until resumed or reconnected.

        Used by the web UI: stopping a workout should not require stopping the
        bridge. Recording restarts automatically after a serial disconnect or
        when :meth:`resume_ride_recording` is called.
        """
        ride = self.finish_ride()
        if ride is not None:
            self._ride_paused = True
        return ride

    def resume_ride_recording(self) -> None:
        """Start a new ride immediately after a manual finish."""
        self._ride_paused = False
        if getattr(self.state, "connected", False) and self._current_ride is None:
            self._start_ride()

    def upload_ride_to_strava(
        self,
        ride: dict,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> dict:
        """Upload ``ride`` to Strava using the configured credentials."""
        from .integrations.strava import StravaClient
        strava_cfg = getattr(self.config, "strava", None)
        if strava_cfg is None:
            return {"ok": False, "error": "Strava is not configured"}
        try:
            client = StravaClient.from_config(strava_cfg)
            result = client.upload_ride(
                ride,
                name=name,
                description=description,
                private=bool(getattr(strava_cfg, "private", False)),
            )
        except Exception as e:
            log.exception("Strava upload failed")
            result = {"ok": False, "error": str(e)}
        self._last_strava_result = result
        return result

    def _maybe_auto_upload_strava(self, ride: dict):
        strava_cfg = getattr(self.config, "strava", None)
        if not strava_cfg or not getattr(strava_cfg, "auto_upload", False):
            return
        self._strava_thread = threading.Thread(
            target=self.upload_ride_to_strava,
            args=(ride,),
            daemon=True,
            name="strava-upload",
        )
        self._strava_thread.start()

    def email_ride(self, ride: dict, to: Optional[str] = None) -> dict:
        """Email ``ride`` as a TCX attachment using the configured SMTP server."""
        from .integrations.emailer import send_ride_email
        email_cfg = getattr(self.config, "email", None)
        try:
            result = send_ride_email(ride, email_cfg, to=to)
        except Exception as e:
            log.exception("Email send failed")
            result = {"ok": False, "error": str(e)}
        self._last_email_result = result
        return result

    def _maybe_email_ride(self, ride: dict):
        email_cfg = getattr(self.config, "email", None)
        if not email_cfg or not getattr(email_cfg, "auto_send", False):
            return
        self._email_thread = threading.Thread(
            target=self.email_ride,
            args=(ride,),
            daemon=True,
            name="ride-email",
        )
        self._email_thread.start()

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
                    if not self._ant_backend.start():
                        log.warning(
                            "ANT+ FE-C requested but unavailable: %s",
                            self._ant_backend.last_error,
                        )
                except Exception as e:
                    log.warning("Failed to start ANT+ backend: %s", e)
        except Exception as e:
            log.debug("ANT+ backend not started: %s", e)
        # Start handlebar shift buttons (best effort; missing hardware is logged)
        self._start_inputs()

    def _start_inputs(self):
        """Start the configured handlebar shift buttons, if any."""
        try:
            from .inputs import build_inputs

            self._inputs, self._input_problems = build_inputs(self.config, self._on_input_shift)
        except Exception as e:
            self._inputs = []
            self._input_problems = [str(e)]
            log.warning("Shift inputs not started: %s", e)

    def _stop_inputs(self):
        """Stop all shift inputs (safe to call more than once)."""
        for item in self._inputs:
            try:
                item.stop()
            except Exception as e:
                log.debug("Could not stop shift input %s: %s", item, e)
        self._inputs = []

    def _on_input_shift(self, delta: int, source: str):
        """Callback used by the shift-button backends."""
        self.shift(delta, source)

    def input_status(self) -> dict:
        """Status of the physical shift buttons for the web UI/CLI."""
        cfg = getattr(self.config, "input", None)
        return {
            "enabled": bool(getattr(cfg, "enabled", False)),
            "backend": getattr(cfg, "backend", "none"),
            "shift_clears_erg": bool(getattr(cfg, "shift_clears_erg", True)),
            "active": [item.status() for item in self._inputs],
            "problems": list(self._input_problems),
            "last_source": self._last_shift_source,
            "last_shift_at": self._last_shift_at or None,
        }

    def stop(self):
        self._running = False
        self._stop_inputs()
        try:
            self.finish_ride()
        except Exception as e:
            log.debug("Could not finish ride on stop: %s", e)
        thread = getattr(self, "_strava_thread", None)
        if thread is not None and thread.is_alive():
            # Give an in-flight auto-upload a chance to finish on shutdown.
            thread.join(timeout=15)
        email_thread = getattr(self, "_email_thread", None)
        if email_thread is not None and email_thread.is_alive():
            # Give an in-flight auto-email a chance to finish on shutdown.
            email_thread.join(timeout=15)
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
            if self._ant_backend:
                self._ant_backend.stop()
        except Exception as e:
            log.debug("ANT+ stop error: %s", e)
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
            # ERG takes over: a previously requested resistance/grade no longer
            # describes the load, so drop it from the reported state.
            self._target_resistance_pct = 0.0
            self._target_grade_pct = None
            # Requesting a target power means the app controls load in ERG mode.
            self._erg_control_granted = True
        if self.protocol and getattr(self.protocol, '_address_found', False):
            try:
                self.protocol.set_watt(self._target_watt)
                self._last_target_set = time.time()
            except Exception as e:
                log.debug("set_watt error: %s", e)

    def shift(self, delta: int, source: str = "manual"):
        """Shift gears by ``delta`` steps (+1 harder, -1 easier).

        Handlebar buttons, the web UI and the CLI all go through here so they
        behave identically. When ``input.shift_clears_erg`` is enabled (the
        default) an active ERG target is released first: otherwise the cockpit
        keeps holding the last target power and the gear change has no effect
        on the load.
        """
        try:
            step = int(delta)
        except (TypeError, ValueError):
            return
        if step == 0:
            return
        input_cfg = getattr(self.config, "input", None)
        if getattr(input_cfg, "shift_clears_erg", True) and (
            self._target_watt != 0 or self._erg_control_granted
        ):
            self.set_target_watt(0)
            self._erg_control_granted = False
        self.set_gear(self._target_gear + step)
        self._last_shift_source = str(source or "manual")
        self._last_shift_at = time.time()

    def shift_up(self):
        self.shift(1, "api")

    def shift_down(self):
        self.shift(-1, "api")

    @property
    def max_gear(self) -> int:
        """Highest usable gear (the Daum protocol accepts 1..28)."""
        try:
            value = int(getattr(self.config.bridge, "max_gear", 20) or 20)
        except (TypeError, ValueError):
            value = 20
        return max(2, min(28, value))

    def gear_to_resistance_percent(self, gear: int) -> float:
        """Map a Daum gear (1..max_gear) to a 0-100 % resistance level."""
        gear = max(1, min(self.max_gear, int(gear)))
        return round((gear - 1) / (self.max_gear - 1) * 100.0, 1)

    def resistance_to_gear(self, percent: float) -> int:
        """Map a 0-100 % resistance level to the nearest Daum gear."""
        try:
            pct = float(percent)
        except (TypeError, ValueError):
            pct = 0.0
        pct = max(0.0, min(100.0, pct))
        gear = 1 + int(round(pct / 100.0 * (self.max_gear - 1)))
        return max(1, min(self.max_gear, gear))

    def set_resistance_percent(self, percent: float):
        """Apply a 0-100 % resistance level (FTMS/FE-C simulation mode).

        Resistance is emulated with the Daum gear, so ERG mode is left first:
        otherwise the cockpit keeps holding the last target power and gear
        changes have no effect.
        """
        try:
            pct = float(percent)
        except (TypeError, ValueError):
            return
        pct = max(0.0, min(100.0, pct))
        self._target_resistance_pct = round(pct, 1)
        self._target_grade_pct = None
        if self._target_watt != 0 or self._erg_control_granted:
            self.set_target_watt(0)
            self._erg_control_granted = False
        self._apply_gear(self.resistance_to_gear(pct))

    def set_grade_percent(self, grade: float):
        """Apply a road grade in percent (FTMS/FE-C simulation mode).

        The Daum has no incline motor, so the grade is translated into a
        resistance level: 0 % maps to half of the gear range and every 1 %
        of grade adds 5 percentage points (clamped to 0-100 %).
        """
        try:
            value = float(grade)
        except (TypeError, ValueError):
            return
        value = max(-25.0, min(25.0, value))
        self.set_resistance_percent(50.0 + value * 5.0)
        self._target_grade_pct = round(value, 2)

    def _apply_gear(self, gear: int):
        self._target_gear = max(1, min(self.max_gear, int(gear)))
        if self.protocol and getattr(self.protocol, '_address_found', False):
            try:
                self.protocol.set_gear(self._target_gear)
                self._last_target_set = time.time()
            except Exception as e:
                log.debug("set_gear error: %s", e)

    def set_gear(self, gear: int):
        self._apply_gear(gear)
        self._target_resistance_pct = self.gear_to_resistance_percent(self._target_gear)
        self._target_grade_pct = None
