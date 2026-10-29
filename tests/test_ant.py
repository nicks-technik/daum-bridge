import pytest

from daum_bridge.backends import ant_fe
from daum_bridge.backends.ant_fe import (
    ANTPLUS_NETWORK_KEY,
    CAPABILITIES_DISTANCE,
    COMMAND_STATUS_PASS,
    FE_CAPABILITIES_ALL,
    FE_STATE_IN_USE,
    FE_STATE_READY,
    PAGE_BASIC_RESISTANCE,
    PAGE_COMMAND_STATUS,
    PAGE_FE_CAPABILITIES,
    PAGE_GENERAL_FE,
    PAGE_GENERAL_SETTINGS,
    PAGE_SPECIFIC_TRAINER,
    PAGE_TARGET_POWER,
    PAGE_TRACK_RESISTANCE,
    PAGE_WIND_RESISTANCE,
    ANTFEBackend,
    FECPageBuilder,
    decode_control_page,
    encode_command_status,
    encode_fe_capabilities,
    encode_general_fe_data,
    encode_general_settings,
    encode_specific_trainer_data,
)
from daum_bridge.bridge import DaumBridge
from daum_bridge.config import ANTConfig, Config


def test_ant_config_defaults():
    a = ANTConfig()
    assert a.enabled is False
    assert a.device_id == 0
    assert a.network_key == ""


def test_ant_backend_init():
    cfg = Config()
    bridge = DaumBridge(cfg)
    b = ANTFEBackend(bridge, cfg)
    assert b.bridge is bridge
    assert b.running is False
    assert b.available is ant_fe.OPENANT_AVAILABLE


def test_ant_backend_start_reports_missing_openant(monkeypatch):
    monkeypatch.setattr(ant_fe, "OPENANT_AVAILABLE", False)
    b = ANTFEBackend(DaumBridge(Config()), Config())
    assert b.start() is False
    assert b.running is False
    assert "openant" in (b.last_error or "")
    b.stop()
    assert b.running is False


@pytest.mark.parametrize(
    "value",
    ["B9 A5 21 FB BD 72 C3 45", "b9a521fbbd72c345", "0xB9, 0xA5, 0x21, 0xFB, 0xBD, 0x72, 0xC3, 0x45"],
)
def test_network_key_parsing(value):
    assert ANTFEBackend._parse_network_key(value) == ANTPLUS_NETWORK_KEY


def test_network_key_default_and_invalid():
    assert ANTFEBackend._parse_network_key("") == ANTPLUS_NETWORK_KEY
    assert ANTFEBackend._parse_network_key("not-a-key") == ANTPLUS_NETWORK_KEY


def test_encode_general_fe_data():
    page = encode_general_fe_data(
        elapsed_time=10.0,
        distance_m=300,
        speed_mps=10.0,
        heart_rate=140,
        fe_state=FE_STATE_IN_USE,
    )
    assert len(page) == 8
    assert page[0] == PAGE_GENERAL_FE == 16
    assert page[1] == 25  # trainer
    assert page[2] == 40  # 10 s * 4
    assert page[3] == 300 & 0xFF  # distance rolls over
    assert page[4] | (page[5] << 8) == 10_000  # 0.001 m/s
    assert page[6] == 140
    # capabilities (distance) + FE state (in use)
    assert page[7] == CAPABILITIES_DISTANCE | (FE_STATE_IN_USE << 4) == 0x34


def test_encode_general_fe_data_invalid_heart_rate():
    page = encode_general_fe_data(heart_rate=None)
    assert page[6] == 0xFF


def test_encode_general_settings():
    page = encode_general_settings(
        cycle_length=210,
        incline_percent=2.5,
        resistance_percent=50.0,
        fe_state=FE_STATE_READY,
    )
    assert page[0] == PAGE_GENERAL_SETTINGS == 17
    assert page[1:3] == b"\xff\xff"
    assert page[3] == 210
    assert page[4] | (page[5] << 8) == 250  # 0.01 %
    assert page[6] == 100  # 0.5 % units
    assert page[7] == FE_STATE_READY << 4


def test_encode_general_settings_marks_invalid_values():
    page = encode_general_settings()
    assert page[4] | (page[5] << 8) == 0x7FFF
    assert page[6] == 0xFF


def test_encode_specific_trainer_data():
    page = encode_specific_trainer_data(
        event_count=7,
        cadence=90,
        accumulated_power=1000,
        instant_power=250,
        trainer_status=0,
        target_power_limits=1,
        fe_state=FE_STATE_IN_USE,
    )
    assert page[0] == PAGE_SPECIFIC_TRAINER == 25
    assert page[1] == 7
    assert page[2] == 90
    assert page[3] | (page[4] << 8) == 1000
    assert page[5] | ((page[6] & 0x0F) << 8) == 250
    assert page[6] >> 4 == 0  # trainer status OK
    assert page[7] == 0x31  # target power limits flag + in-use state


def test_encode_specific_trainer_data_power_uses_twelve_bits():
    page = encode_specific_trainer_data(instant_power=800)
    assert page[5] | ((page[6] & 0x0F) << 8) == 800
    assert page[6] >> 4 == 0


def test_encode_specific_trainer_data_invalid_cadence():
    page = encode_specific_trainer_data(cadence=None)
    assert page[2] == 0xFF


def test_encode_fe_capabilities():
    page = encode_fe_capabilities()
    assert page == bytes([PAGE_FE_CAPABILITIES, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x07])
    assert FE_CAPABILITIES_ALL == 0x07

    page = encode_fe_capabilities(max_resistance_n=1000)
    assert page[5] | (page[6] << 8) == 1000


def test_encode_command_status():
    page = encode_command_status(
        command_id=PAGE_TARGET_POWER,
        sequence=3,
        status=COMMAND_STATUS_PASS,
        data=bytes([0x00, 0x00, 0x34, 0x12]),
    )
    assert page == bytes([PAGE_COMMAND_STATUS, 49, 3, 0, 0x00, 0x00, 0x34, 0x12])


def test_decode_basic_resistance():
    decoded = decode_control_page(bytes([PAGE_BASIC_RESISTANCE, 0, 0, 0, 0, 0, 0, 100]))
    assert decoded["mode"] == "basic_resistance"
    assert decoded["resistance_percent"] == 50.0

    invalid = decode_control_page(bytes([PAGE_BASIC_RESISTANCE, 0, 0, 0, 0, 0, 0, 0xFF]))
    assert invalid["resistance_percent"] is None


def test_decode_target_power():
    raw = 800  # 200 W in 0.25 W units
    page = bytes([PAGE_TARGET_POWER, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, raw & 0xFF, raw >> 8])
    decoded = decode_control_page(page)
    assert decoded["mode"] == "target_power"
    assert decoded["target_power_w"] == 200.0


def test_decode_track_resistance():
    grade_raw = 20_500  # 5 % = raw * 0.01 - 200
    page = bytes(
        [
            PAGE_TRACK_RESISTANCE,
            0xFF,
            0xFF,
            0xFF,
            0xFF,
            grade_raw & 0xFF,
            grade_raw >> 8,
            200,  # crr 0.01
        ]
    )
    decoded = decode_control_page(page)
    assert decoded["mode"] == "track"
    assert decoded["grade_percent"] == pytest.approx(5.0)
    assert decoded["crr"] == pytest.approx(0.01)


def test_decode_wind_resistance():
    page = bytes([PAGE_WIND_RESISTANCE, 0xFF, 0xFF, 0xFF, 0xFF, 50, 127 + 10, 75])
    decoded = decode_control_page(page)
    assert decoded["mode"] == "wind"
    assert decoded["wind_resistance_kg_m"] == pytest.approx(0.5)
    assert decoded["wind_speed_kmh"] == 10
    assert decoded["drafting_factor"] == pytest.approx(0.75)


def test_decode_unknown_or_short_page():
    assert decode_control_page(bytes([0x99, 0, 0, 0, 0, 0, 0, 0])) is None
    assert decode_control_page(b"\x30\x00") is None
    assert decode_control_page(b"") is None


def test_decode_invalid_target_power():
    page = bytes([PAGE_TARGET_POWER, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
    assert decode_control_page(page)["target_power_w"] is None


def test_backend_translates_control_pages_to_bridge():
    backend = ANTFEBackend(DaumBridge(Config()), Config())

    backend._on_control({"mode": "target_power", "target_power_w": 180.0})
    assert backend.bridge._target_watt == 180

    backend._on_control({"mode": "basic_resistance", "resistance_percent": 50.0})
    assert backend.bridge._target_resistance_pct == 50.0
    assert backend.bridge._target_watt == 0

    backend._on_control({"mode": "track", "grade_percent": 3.0})
    assert backend.bridge._target_grade_pct == 3.0
    assert backend.bridge._target_resistance_pct == 65.0


class _State:
    power = 240
    cadence = 88
    speed = 32.4  # km/h
    total_distance = 1.5  # km
    elapsed_time = 600
    heart_rate = 145
    connected = True


def test_page_builder_rotation_covers_all_pages():
    builder = FECPageBuilder(state_provider=lambda: _State())
    pages = {}
    for slot in range(1, 130):
        page = builder.next_page(slot)
        assert isinstance(page, list)
        assert len(page) == 8
        assert all(isinstance(byte, int) and 0 <= byte <= 0xFF for byte in page)
        pages.setdefault(page[0], 0)
        pages[page[0]] += 1

    # All four required pages are broadcast, and page 25 carries the live
    # power/cadence from the bridge state.
    assert set(pages) == {
        PAGE_GENERAL_FE,
        PAGE_GENERAL_SETTINGS,
        PAGE_SPECIFIC_TRAINER,
        PAGE_FE_CAPABILITIES,
    }
    trainer = builder.next_page(1)
    assert trainer[0] == PAGE_SPECIFIC_TRAINER
    assert trainer[2] == 88
    assert trainer[5] | ((trainer[6] & 0x0F) << 8) == 240


def test_page_builder_general_fe_data_uses_kmh_to_mps():
    builder = FECPageBuilder(state_provider=lambda: _State())
    page = builder.next_page(2)
    assert page[0] == PAGE_GENERAL_FE
    speed_raw = page[4] | (page[5] << 8)
    assert speed_raw == pytest.approx(9000, abs=1)  # 32.4 km/h = 9 m/s
    assert page[6] == 145
    assert page[3] == int(1500) & 0xFF


def test_page_builder_answers_target_power_with_status_page():
    received = []
    builder = FECPageBuilder(on_control=received.append)
    request = bytes([PAGE_TARGET_POWER, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x20, 0x03])

    reply = builder.handle_ack(request)

    assert reply[0] == PAGE_COMMAND_STATUS
    assert reply[1] == PAGE_TARGET_POWER
    assert reply[3] == COMMAND_STATUS_PASS
    assert reply[4:8] == list(request[4:8])
    assert received and received[0]["mode"] == "target_power"
    assert received[0]["target_power_w"] == 200.0


def test_page_builder_reports_wind_as_not_supported():
    received = []
    builder = FECPageBuilder(on_control=received.append)
    request = bytes([PAGE_WIND_RESISTANCE, 0xFF, 0xFF, 0xFF, 0xFF, 50, 137, 100])

    reply = builder.handle_ack(request)

    assert reply[3] == ant_fe.COMMAND_STATUS_NOT_SUPPORTED
    assert received == []


def test_page_builder_reports_failed_control_application():
    def boom(_control):
        raise RuntimeError("nope")

    builder = FECPageBuilder(on_control=boom)
    request = bytes([PAGE_BASIC_RESISTANCE, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 100])

    reply = builder.handle_ack(request)

    assert reply[3] == ant_fe.COMMAND_STATUS_FAIL


def test_page_builder_replies_to_request_data_page():
    builder = FECPageBuilder()
    builder.last_command_id = PAGE_TRACK_RESISTANCE
    builder.last_status = COMMAND_STATUS_PASS

    # Request page 71, one transmission.
    reply = builder.handle_ack(bytes([0x46, 0xFF, 0xFF, 0xFF, 0xFF, 0x01, PAGE_COMMAND_STATUS, 0x01]))
    assert reply is not None and reply[0] == PAGE_COMMAND_STATUS

    # Any other requested page is ignored.
    assert builder.handle_ack(bytes([0x46, 0xFF, 0xFF, 0xFF, 0xFF, 0x01, 0x19, 0x01])) is None


def test_page_builder_ignores_short_and_unknown_frames():
    builder = FECPageBuilder()
    assert builder.handle_ack(b"\x31\x00") is None
    assert builder.handle_ack(bytes([0x99, 0, 0, 0, 0, 0, 0, 0])) is None

