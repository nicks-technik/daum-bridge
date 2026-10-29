import xml.etree.ElementTree as ET

from daum_bridge.integrations.tcx import ACTIVITY_EXT_NS, TCX_NS, build_tcx

NS = {"t": TCX_NS, "a": ACTIVITY_EXT_NS}


def _ride(**overrides):
    ride = {
        "id": "test-ride",
        "start": 1761732000.0,  # 2025-10-29T10:00:00Z
        "duration": 30.0,
        "distance": 0.3,
        "avg_power": 200.0,
        "max_power": 300.0,
        "avg_cadence": 85.0,
        "avg_heart_rate": 140.0,
        "max_heart_rate": 150.0,
        "work_kj": 10.0,
    }
    ride.update(overrides)
    return ride


SAMPLES = [
    {"t": 0, "power": 100, "cadence": 80, "speed": 30, "heart_rate": 130, "distance": 0.0},
    {"t": 10, "power": 200, "cadence": 90, "speed": 35, "heart_rate": 140, "distance": 0.1},
    {"t": 30, "power": 300, "cadence": 95, "speed": 35, "heart_rate": 150, "distance": 0.3},
]


def test_build_tcx_structure():
    root = ET.fromstring(build_tcx(_ride(), SAMPLES))

    activity = root.find("t:Activities/t:Activity", NS)
    assert activity is not None
    assert activity.get("Sport") == "Biking"
    assert activity.findtext("t:Id", namespaces=NS) == "2025-10-29T10:00:00Z"

    lap = activity.find("t:Lap", NS)
    assert lap is not None
    assert lap.get("StartTime") == "2025-10-29T10:00:00Z"
    assert float(lap.findtext("t:TotalTimeSeconds", namespaces=NS)) == 30.0
    assert float(lap.findtext("t:DistanceMeters", namespaces=NS)) == 300.0
    assert lap.findtext("t:Calories", namespaces=NS) == "10"
    assert lap.findtext("t:Cadence", namespaces=NS) == "85"
    assert lap.findtext("t:TriggerMethod", namespaces=NS) == "Manual"

    points = root.findall(".//t:Trackpoint", NS)
    assert len(points) == 3
    assert points[0].findtext("t:Time", namespaces=NS) == "2025-10-29T10:00:00Z"
    assert points[2].findtext("t:Time", namespaces=NS) == "2025-10-29T10:00:30Z"
    assert points[2].findtext("t:DistanceMeters", namespaces=NS) == "300.0"
    assert points[1].findtext("t:HeartRateBpm/t:Value", namespaces=NS) == "140"
    assert points[1].findtext("t:Cadence", namespaces=NS) == "90"
    assert points[1].findtext("t:Extensions/a:TPX/a:Watts", namespaces=NS) == "200"
    assert points[1].findtext("t:Extensions/a:TPX/a:Speed", namespaces=NS) is not None


def test_build_tcx_uses_samples_from_ride():
    ride = _ride(samples=SAMPLES)
    root = ET.fromstring(build_tcx(ride))
    assert len(root.findall(".//t:Trackpoint", NS)) == 3


def test_build_tcx_without_samples_synthesizes_track():
    root = ET.fromstring(build_tcx(_ride()))
    points = root.findall(".//t:Trackpoint", NS)
    assert len(points) == 2
    assert points[-1].findtext("t:DistanceMeters", namespaces=NS) == "300.0"
    # Average power is used for the synthetic points.
    watts = [el.text for el in root.findall(".//a:Watts", NS)]
    assert watts and set(watts) == {"200"}


def test_build_tcx_distance_from_speed_when_odometer_missing():
    samples = [
        {"t": 0, "power": 150, "speed": 36},
        {"t": 10, "power": 150, "speed": 36},
    ]
    root = ET.fromstring(build_tcx(_ride(distance=0), samples))
    assert root.findall(".//t:Trackpoint", NS)[-1].findtext(
        "t:DistanceMeters", namespaces=NS
    ) == "100.0"


def test_build_tcx_ignores_invalid_samples():
    samples = [{"power": 100}, {"t": -5, "power": 100}, "nope", {"t": 5, "power": 120}]
    root = ET.fromstring(build_tcx(_ride(), samples))
    points = root.findall(".//t:Trackpoint", NS)
    assert len(points) == 1
    assert points[0].findtext("t:Time", namespaces=NS) == "2025-10-29T10:00:05Z"


def test_build_tcx_distance_is_monotonic():
    samples = [
        {"t": 0, "distance": 0.2},
        {"t": 5, "distance": 0.1},  # reset / stale value
        {"t": 10, "distance": 0.4},
    ]
    root = ET.fromstring(build_tcx(_ride(), samples))
    distances = [
        float(el.text) for el in root.findall(".//t:Trackpoint/t:DistanceMeters", NS)
    ]
    assert distances == sorted(distances)
    assert distances[-1] == 400.0
