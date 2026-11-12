from daum_bridge.bridge import DaumBridge
from daum_bridge.config import Config
from unittest.mock import Mock

import json


def test_bridge_init():
    cfg = Config()
    b = DaumBridge(cfg)
    assert b.config is cfg
    assert b._running is False
    assert b._target_watt == 0
    assert b._target_gear == 1


def test_bridge_callbacks():
    cfg = Config()
    b = DaumBridge(cfg)
    called = []
    def cb(s):
        called.append(s)
    b.add_state_callback(cb)
    assert cb in b._callbacks


def test_bridge_notify():
    cfg = Config()
    b = DaumBridge(cfg)
    called = []
    b.add_state_callback(lambda s: called.append(True))
    b._notify()
    assert len(called) >= 1


def test_bridge_set_target_watt():
    cfg = Config()
    b = DaumBridge(cfg)
    b.protocol = Mock()
    b.protocol._address_found = True
    b.set_target_watt(200)
    assert b._target_watt == 200


def test_bridge_set_target_watt_clamped():
    cfg = Config()
    b = DaumBridge(cfg)
    b.protocol = Mock()
    b.protocol._address_found = True
    b.set_target_watt(1000)
    assert b._target_watt == 800
    b.set_target_watt(-10)
    assert b._target_watt == 0


def test_bridge_shift_up():
    cfg = Config()
    b = DaumBridge(cfg)
    b.protocol = Mock()
    b.protocol._address_found = True
    b._target_gear = 1
    b.shift_up()
    assert b._target_gear == 2


def test_bridge_shift_down():
    cfg = Config()
    b = DaumBridge(cfg)
    b.protocol = Mock()
    b.protocol._address_found = True
    b._target_gear = 5
    b.shift_down()
    assert b._target_gear == 4


def test_bridge_set_gear():
    cfg = Config()
    b = DaumBridge(cfg)
    b.protocol = Mock()
    b.protocol._address_found = True
    b.set_gear(10)
    assert b._target_gear == 10


def test_resistance_gear_mapping():
    b = DaumBridge(Config())
    assert b.max_gear == 20
    assert b.resistance_to_gear(0) == 1
    assert b.resistance_to_gear(100) == 20
    assert b.resistance_to_gear(-10) == 1
    assert b.resistance_to_gear(250) == 20
    assert b.resistance_to_gear(50) == 11
    assert b.gear_to_resistance_percent(1) == 0.0
    assert b.gear_to_resistance_percent(20) == 100.0
    assert b.gear_to_resistance_percent(10) == 47.4


def test_max_gear_is_clamped_and_configurable():
    cfg = Config()
    cfg.bridge.max_gear = 28
    b = DaumBridge(cfg)
    assert b.max_gear == 28
    assert b.resistance_to_gear(100) == 28

    cfg.bridge.max_gear = 99
    assert b.max_gear == 28
    cfg.bridge.max_gear = 1
    assert b.max_gear == 2


def test_set_resistance_percent_leaves_erg_and_sets_gear():
    b = DaumBridge(Config())
    b.protocol = Mock()
    b.protocol._address_found = True
    b._erg_control_granted = True
    b._target_watt = 200

    b.set_resistance_percent(50)

    assert b._target_watt == 0
    assert b._erg_control_granted is False
    assert b._target_resistance_pct == 50.0
    assert b._target_gear == 11
    b.protocol.set_watt.assert_called_with(0)
    b.protocol.set_gear.assert_called_with(11)


def test_set_grade_percent_uses_simulated_power():
    b = DaumBridge(Config())
    b.protocol = Mock()
    b.protocol._address_found = True
    b.state.speed = 30.0
    b.state.cadence = 80.0

    b.set_grade_percent(3.0)

    assert b._target_grade_pct == 3.0
    assert b._sim_active is True
    assert b._target_resistance_pct == 0.0
    # 30 km/h up 3 % is a real climb: well above the 25 W idle floor.
    assert b._sim_watt > 100
    b.protocol.set_watt.assert_called_with(b._sim_watt)
    # Entering simulation only re-asserts the current gear (manual program 0 +
    # set_Gear), it never selects a different one.
    b.protocol.set_program.assert_called_with(0)
    b.protocol.set_gear.assert_called_once_with(1)
    assert b._target_gear == 1


def test_set_grade_percent_asserts_gear_mode_only_on_entry():
    b = DaumBridge(Config())
    b.protocol = Mock()
    b.protocol._address_found = True
    b.state.speed = 30.0
    b.state.cadence = 80.0

    b.set_grade_percent(3.0)
    b.set_grade_percent(4.0)
    b.set_grade_percent(5.0)

    assert b.protocol.set_gear.call_count == 1
    assert b.protocol.set_program.call_count == 1


def test_cockpit_gear_change_is_adopted_in_sim():
    b = DaumBridge(Config())
    b.protocol = Mock()
    b.protocol._address_found = True
    b.state.cadence = 80.0
    b.set_grade_percent(3.0)
    b._last_gear_command = 0.0  # long ago: run data is authoritative again

    b.state.gear = 7
    b._sync_gear_from_cockpit()

    assert b._target_gear == 7
    assert b._target_resistance_pct == 0.0
    assert b._last_shift_source == "cockpit"


def test_cockpit_gear_sync_ignores_stale_frame_after_bridge_shift():
    b = DaumBridge(Config())
    b.protocol = Mock()
    b.protocol._address_found = True
    b.state.cadence = 80.0
    b.set_grade_percent(3.0)

    b.set_gear(9)
    b.state.gear = 1  # cockpit has not caught up yet
    b._sync_gear_from_cockpit()

    assert b._target_gear == 9


def test_cockpit_gear_sync_is_inactive_outside_sim():
    b = DaumBridge(Config())
    b.protocol = Mock()
    b.protocol._address_found = True
    b.state.connected = True

    b.state.gear = 12
    b._sync_gear_from_cockpit()

    assert b._target_gear == 1


def test_enter_manual_gear_mode_sends_program_then_gear():
    from unittest.mock import call

    b = DaumBridge(Config())
    b.protocol = Mock()
    b.protocol._address_found = True
    b.state.gear = 6

    b._enter_manual_gear_mode()

    # Order matters: program 0 first, then set_Gear switches the cockpit to
    # gear mode, where its buttons and jog wheel shift gears.
    assert b.protocol.mock_calls[:2] == [call.set_program(0), call.set_gear(6)]
    assert b._target_gear == 6


def test_enter_manual_gear_mode_without_address_is_noop():
    b = DaumBridge(Config())
    b.protocol = Mock()
    b.protocol._address_found = False

    b._enter_manual_gear_mode()

    b.protocol.set_program.assert_not_called()
    b.protocol.set_gear.assert_not_called()


def test_sim_uses_headwind_and_tailwind_from_the_app():
    b = DaumBridge(Config())
    b.protocol = Mock()
    b.protocol._address_found = True
    b.state.speed = 30.0
    b.state.cadence = 80.0

    b.set_grade_percent(0.0, wind_mps=5.0)
    headwind = b._sim_watt
    b.set_sim_conditions(wind_mps=-5.0)
    tailwind = b._sim_watt

    assert headwind > tailwind


def test_app_environment_reaches_the_power_model_and_clears_on_erg():
    b = DaumBridge(Config())
    b.protocol = Mock()
    b.protocol._address_found = True

    b.set_grade_percent(0.0, wind_mps=5.0, crr=0.006, cw=0.6)

    assert b._sim_wind_mps == 5.0
    assert b._sim_crr == 0.006
    assert b._sim_cw == 0.6

    b.set_target_watt(200)

    assert b._sim_wind_mps == 0.0
    assert b._sim_crr is None
    assert b._sim_cw is None


def test_grade_update_keeps_environment_from_a_separate_page():
    b = DaumBridge(Config())
    b.protocol = Mock()
    b.protocol._address_found = True

    b.set_grade_percent(0.0, wind_mps=4.0)
    b.set_grade_percent(2.0)  # FE-C grade page without a wind field

    assert b._sim_wind_mps == 4.0


def test_implausible_environment_values_are_ignored():
    b = DaumBridge(Config())
    b.protocol = Mock()
    b.protocol._address_found = True

    # Some apps leave unused fields at zero; that must not remove air drag.
    b.set_grade_percent(0.0, crr=0.0, cw=0.0)

    assert b._sim_crr is None
    assert b._sim_cw is None


def test_set_grade_percent_falls_back_to_gear_when_sim_disabled():
    cfg = Config()
    cfg.sim.enabled = False
    b = DaumBridge(cfg)
    b.protocol = Mock()
    b.protocol._address_found = True

    b.set_grade_percent(3.0)

    assert b._target_grade_pct == 3.0
    assert b._sim_active is False
    assert b._target_resistance_pct == 65.0
    assert b._target_gear == 13
    b.protocol.set_gear.assert_called_with(13)


def test_set_gear_clears_grade_outside_sim():
    cfg = Config()
    cfg.sim.enabled = False
    b = DaumBridge(cfg)
    b.protocol = Mock()
    b.protocol._address_found = True
    b.set_grade_percent(2.0)
    assert b._target_grade_pct == 2.0

    b.set_gear(5)

    assert b._target_grade_pct is None
    assert b._target_resistance_pct == b.gear_to_resistance_percent(5)


def test_set_gear_keeps_grade_in_sim():
    b = DaumBridge(Config())
    b.protocol = Mock()
    b.protocol._address_found = True
    b.state.speed = 30.0
    b.set_grade_percent(4.0)

    b.set_gear(5)

    assert b._sim_active is True
    assert b._target_grade_pct == 4.0


def test_target_power_grants_erg_and_clears_grade():
    b = DaumBridge(Config())
    b.protocol = Mock()
    b.protocol._address_found = True
    b.set_grade_percent(4.0)
    assert b._erg_control_granted is False

    b.set_target_watt(220)

    assert b._target_watt == 220
    assert b._erg_control_granted is True
    assert b._target_grade_pct is None
    assert b._target_resistance_pct == 0.0
    b.protocol.set_watt.assert_called_with(220)


def test_stop_stops_ant_backend():
    from types import SimpleNamespace

    b = DaumBridge(Config())
    stopped = []
    b._ant_backend = SimpleNamespace(stop=lambda: stopped.append(True))
    b.stop()
    assert stopped == [True]



def test_ride_recording_and_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("DAUM_RIDES_DIR", str(tmp_path))
    b = DaumBridge(Config())
    b.state.connected = True
    b.state.power = 200
    b.state.cadence = 90
    b.state.speed = 30
    b.state.heart_rate = 140
    b.state.total_distance = 0.1

    b._update_ride_stats()  # starts the ride, records the first sample

    b.state.total_distance = 0.2
    b.state.power = 250
    b.state.heart_rate = 145
    b._update_ride_stats()  # odometer advances by 0.1 km

    b.state.connected = False
    b._update_ride_stats()  # ends and saves the ride

    assert b._current_ride is None
    assert len(b._ride_history) == 1
    summary = b._ride_history[0]
    assert summary["distance"] == 0.1
    assert summary["max_power"] == 250
    assert summary["avg_heart_rate"] == 142.5
    assert summary["sample_count"] >= 1

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data["id"] == files[0].stem
    assert data["samples"][0]["power"] == 200
    assert data["samples"][0]["heart_rate"] == 140


def test_finish_ride_without_ride_is_noop():
    b = DaumBridge(Config())
    assert b.finish_ride() is None
    assert b._ride_history == []


def test_finish_ride_writes_tcx(tmp_path, monkeypatch):
    monkeypatch.setenv("DAUM_RIDES_DIR", str(tmp_path))
    b = DaumBridge(Config())
    b.state.connected = True
    b.state.power = 180
    b.state.speed = 30
    b._update_ride_stats()
    ride = b.finish_ride()

    assert ride is not None
    tcx_path = tmp_path / f"{ride['id']}.tcx"
    assert tcx_path.exists()
    content = tcx_path.read_text(encoding="utf-8")
    assert "<TrainingCenterDatabase" in content
    assert "garmin:Watts" in content


def test_finish_current_ride_pauses_until_resume(tmp_path, monkeypatch):
    monkeypatch.setenv("DAUM_RIDES_DIR", str(tmp_path))
    b = DaumBridge(Config())
    b.state.connected = True
    b.state.power = 150
    b._update_ride_stats()

    ride = b.finish_current_ride()
    assert ride is not None
    assert b._ride_paused is True

    # Samples from the continued session must not start a new ride.
    b.state.power = 160
    b._update_ride_stats()
    assert b._current_ride is None
    assert len(b._ride_history) == 1

    b.resume_ride_recording()
    assert b._ride_paused is False
    assert b._current_ride is not None


def test_stop_finishes_ride(tmp_path, monkeypatch):
    monkeypatch.setenv("DAUM_RIDES_DIR", str(tmp_path))
    b = DaumBridge(Config())
    b.state.connected = True
    b.state.power = 150
    b._update_ride_stats()
    b.stop()
    assert b._current_ride is None
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_auto_email_starts_on_ride_finish(tmp_path, monkeypatch):
    monkeypatch.setenv("DAUM_RIDES_DIR", str(tmp_path))
    cfg = Config()
    cfg.email.auto_send = True
    cfg.email.host = "smtp.example.com"
    cfg.email.from_addr = "from@example.com"
    cfg.email.to_addr = "to@example.com"
    b = DaumBridge(cfg)
    emailed = []
    b.email_ride = lambda ride, to=None: emailed.append(ride) or {"ok": True}

    b.state.connected = True
    b.state.power = 150
    b._update_ride_stats()
    b.state.connected = False
    b._update_ride_stats()

    b._email_thread.join(timeout=5)
    assert len(emailed) == 1
    assert emailed[0]["samples"]


def test_auto_upload_starts_on_ride_finish(tmp_path, monkeypatch):
    monkeypatch.setenv("DAUM_RIDES_DIR", str(tmp_path))
    cfg = Config()
    cfg.strava.auto_upload = True
    b = DaumBridge(cfg)
    uploaded = []
    b.upload_ride_to_strava = lambda ride: uploaded.append(ride) or {"ok": True}

    b.state.connected = True
    b.state.power = 150
    b._update_ride_stats()
    b.state.connected = False
    b._update_ride_stats()

    if b._strava_thread is not None:
        b._strava_thread.join(timeout=5)
    assert uploaded
    assert uploaded[0]["id"] == b._ride_history[0]["id"]
