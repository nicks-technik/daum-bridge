"""Tests for the BLE heart-rate central (:mod:`daum_bridge.backends.hr_ble`)."""

from daum_bridge.backends import hr_ble
from daum_bridge.config import Config, HeartRateConfig


def test_decode_heart_rate_8_bit():
    # flags=0 -> 8-bit value in the second byte
    assert hr_ble.decode_heart_rate(bytes([0x00, 72])) == 72


def test_decode_heart_rate_16_bit():
    # flags bit 0 set -> little-endian uint16
    assert hr_ble.decode_heart_rate(bytes([0x01, 0x91, 0x00])) == 145


def test_decode_heart_rate_ignores_sensor_contact_bits():
    # Sensor-contact bits (0x06) must not change the value width.
    assert hr_ble.decode_heart_rate(bytes([0x07, 0x91, 0x00])) == 145


def test_decode_heart_rate_rejects_short_and_implausible_values():
    assert hr_ble.decode_heart_rate(b"") is None
    assert hr_ble.decode_heart_rate(b"\x00") is None
    assert hr_ble.decode_heart_rate(bytes([0x01, 0x91])) is None
    assert hr_ble.decode_heart_rate(bytes([0x00, 0x00])) is None
    assert hr_ble.decode_heart_rate(bytes([0x00, 0xFF])) is None
    assert hr_ble.decode_heart_rate(None) is None


def _objects(*devices):
    result = {}
    for path, address, name, uuids in devices:
        result[path] = {
            "org.bluez.Device1": {
                "Address": address,
                "Name": name,
                "UUIDs": list(uuids),
            }
        }
    return result


def test_find_device_by_heart_rate_service():
    objects = _objects(
        ("/dev/tv", "AA:BB:CC:DD:EE:01", "Living room TV", []),
        (
            "/dev/belt",
            "AA:BB:CC:DD:EE:02",
            "H10-1234",
            [hr_ble.HEART_RATE_SERVICE_UUID],
        ),
    )
    path, info = hr_ble.find_device(objects)
    assert path == "/dev/belt"
    assert info["address"] == "AA:BB:CC:DD:EE:02"


def test_find_device_by_known_name_when_uuids_are_missing():
    objects = _objects(("/dev/belt", "AA:BB:CC:DD:EE:03", "Polar H10", []))
    path, _ = hr_ble.find_device(objects)
    assert path == "/dev/belt"


def test_find_device_by_address_or_name_fragment():
    objects = _objects(
        ("/dev/a", "AA:BB:CC:DD:EE:04", "Wahoo TICKR", []),
        ("/dev/b", "AA:BB:CC:DD:EE:05", "Polar H10", []),
    )
    assert hr_ble.find_device(objects, "aa:bb:cc:dd:ee:04")[0] == "/dev/a"
    assert hr_ble.find_device(objects, "polar")[0] == "/dev/b"


def test_find_device_returns_none_without_a_belt():
    objects = _objects(("/dev/tv", "AA:BB:CC:DD:EE:06", "Living room TV", []))
    assert hr_ble.find_device(objects) is None


def test_find_device_prefers_a_real_heart_rate_service():
    objects = _objects(
        ("/dev/watch", "AA:BB:CC:DD:EE:07", "Garmin Watch", []),
        (
            "/dev/belt",
            "AA:BB:CC:DD:EE:08",
            "Unknown strap",
            [hr_ble.HEART_RATE_SERVICE_UUID],
        ),
    )
    assert hr_ble.find_device(objects)[0] == "/dev/belt"


def test_find_heart_rate_characteristic_under_the_hr_service():
    objects = {
        "/svc/hr": {
            "org.bluez.GattService1": {
                "UUID": hr_ble.HEART_RATE_SERVICE_UUID,
            }
        },
        "/svc/hr/char0": {
            "org.bluez.GattCharacteristic1": {
                "UUID": hr_ble.HEART_RATE_MEASUREMENT_UUID,
                "Service": "/svc/hr",
            }
        },
    }
    assert hr_ble.find_heart_rate_characteristic(objects) == "/svc/hr/char0"


def test_find_heart_rate_characteristic_ignores_other_services():
    objects = {
        "/svc/other": {
            "org.bluez.GattService1": {
                "UUID": "0000180a-0000-1000-8000-00805f9b34fb",
            }
        },
        "/svc/other/char0": {
            "org.bluez.GattCharacteristic1": {
                "UUID": hr_ble.HEART_RATE_MEASUREMENT_UUID,
                "Service": "/svc/other",
            }
        },
    }
    # No Heart Rate service at all: nothing to subscribe to.
    assert hr_ble.find_heart_rate_characteristic(objects) is None


def test_heart_rate_config_defaults():
    cfg = HeartRateConfig()
    assert cfg.enabled is False
    assert cfg.device == ""
    assert cfg.scan_timeout == 30.0


def test_config_from_dict_parses_heart_rate_section():
    cfg = Config.from_dict(
        {
            "heart_rate": {
                "enabled": True,
                "device": "Polar H10",
                "adapter": "hci1",
                "scan_timeout": 10,
                "reconnect_delay": 2,
            }
        }
    )
    assert cfg.heart_rate.enabled is True
    assert cfg.heart_rate.device == "Polar H10"
    assert cfg.heart_rate.adapter == "hci1"
    assert cfg.heart_rate.scan_timeout == 10.0
    assert cfg.heart_rate.reconnect_delay == 2.0
