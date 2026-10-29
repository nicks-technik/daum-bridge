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


def test_set_grade_percent_maps_to_resistance():
    b = DaumBridge(Config())
    b.protocol = Mock()
    b.protocol._address_found = True

    b.set_grade_percent(3.0)

    assert b._target_grade_pct == 3.0
    assert b._target_resistance_pct == 65.0
    assert b._target_gear == 13
    b.protocol.set_gear.assert_called_with(13)


def test_set_gear_clears_grade():
    b = DaumBridge(Config())
    b.protocol = Mock()
    b.protocol._address_found = True
    b.set_grade_percent(2.0)
    assert b._target_grade_pct == 2.0

    b.set_gear(5)

    assert b._target_grade_pct is None
    assert b._target_resistance_pct == b.gear_to_resistance_percent(5)


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
