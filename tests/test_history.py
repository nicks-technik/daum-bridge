import json

from daum_bridge import history


def _ride(start=1761732000.0, **overrides):
    ride = {
        "start": start,
        "end": start + 60,
        "duration": 60.0,
        "distance": 0.5,
        "avg_power": 200.0,
        "max_power": 300.0,
        "work_kj": 10.0,
        "samples": [{"t": 0, "power": 100}, {"t": 60, "power": 200}],
    }
    ride.update(overrides)
    return ride


def test_save_and_load_ride(tmp_path):
    ride_id = history.save_ride(_ride(), directory=tmp_path)
    assert ride_id == history.make_ride_id(_ride())

    loaded = history.load_ride(ride_id, directory=tmp_path)
    assert loaded is not None
    assert loaded["id"] == ride_id
    assert loaded["avg_power"] == 200.0
    assert len(loaded["samples"]) == 2

    # The file is valid JSON and contains the id.
    data = json.loads((tmp_path / f"{ride_id}.json").read_text())
    assert data["id"] == ride_id


def test_list_rides_newest_first_and_strips_samples(tmp_path):
    history.save_ride(_ride(start=1761732000.0), directory=tmp_path)
    history.save_ride(_ride(start=1761735600.0), directory=tmp_path)

    rides = history.list_rides(directory=tmp_path)
    assert len(rides) == 2
    assert rides[0]["start"] > rides[1]["start"]
    assert "samples" not in rides[0]
    assert rides[0]["has_samples"] is True
    assert rides[0]["sample_count"] == 2


def test_list_rides_with_samples(tmp_path):
    history.save_ride(_ride(), directory=tmp_path)
    rides = history.list_rides(directory=tmp_path, include_samples=True)
    assert len(rides[0]["samples"]) == 2


def test_save_ride_avoids_overwriting(tmp_path):
    first = history.save_ride(_ride(), directory=tmp_path)
    second = history.save_ride(_ride(), directory=tmp_path)
    assert first != second
    assert (tmp_path / f"{first}.json").exists()
    assert (tmp_path / f"{second}.json").exists()


def test_load_ride_rejects_path_traversal(tmp_path):
    assert history.load_ride("../secret", directory=tmp_path) is None
    assert history.load_ride("", directory=tmp_path) is None
    assert history.load_ride("does-not-exist", directory=tmp_path) is None


def test_latest_ride_empty(tmp_path):
    assert history.latest_ride(directory=tmp_path) is None


def test_rides_dir_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("DAUM_RIDES_DIR", str(tmp_path))
    assert history.rides_dir() == tmp_path
    ride_id = history.save_ride(_ride())
    assert (tmp_path / f"{ride_id}.json").exists()


def test_corrupt_ride_file_is_skipped(tmp_path):
    (tmp_path / "broken.json").write_text("{not json")
    ride_id = history.save_ride(_ride(), directory=tmp_path)
    ids = [r["id"] for r in history.list_rides(directory=tmp_path)]
    assert ids == [ride_id]
