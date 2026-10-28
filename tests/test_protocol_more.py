from daum_bridge.serial.daum import DaumProtocol, DaumState, DaumCmd
from unittest.mock import Mock


def test_build_command_address():
    ser = Mock()
    proto = DaumProtocol(ser)
    cmd = proto.build_command(DaumCmd.GET_ADDRESS)
    assert cmd[0] == 0xA1


def test_build_command_with_address():
    ser = Mock()
    proto = DaumProtocol(ser)
    proto._address = 0x01
    cmd = proto.build_command(DaumCmd.GET_PERSON_DATA, 0x01)
    assert cmd[0] == 0xA2
    assert cmd[1] == 0x01


def test_build_command_with_data():
    ser = Mock()
    proto = DaumProtocol(ser)
    proto._address = 0x01
    cmd = proto.build_command(DaumCmd.SET_WATT, 0x01, 200)
    assert cmd[0] == 0xA6
    assert cmd[1] == 0x01
    assert cmd[2] == 200


def test_set_watt():
    ser = Mock()
    proto = DaumProtocol(ser)
    proto._address_found = True
    proto._address = 0x01
    proto.set_watt(150)
    assert ser.write.called


def test_set_watt_clamped():
    ser = Mock()
    proto = DaumProtocol(ser)
    proto._address_found = True
    proto._address = 0x01
    proto.set_watt(1000)
    # Should clamp to 800
    assert ser.write.called


def test_set_gear():
    ser = Mock()
    proto = DaumProtocol(ser)
    proto._address_found = True
    proto._address = 0x01
    proto.set_gear(5)
    assert ser.write.called


def test_set_program():
    ser = Mock()
    proto = DaumProtocol(ser)
    proto._address_found = True
    proto._address = 0x01
    proto.set_program(1)
    assert ser.write.called


def test_request_address():
    ser = Mock()
    proto = DaumProtocol(ser)
    proto.request_address()
    assert ser.write.called


def test_request_person_data():
    ser = Mock()
    proto = DaumProtocol(ser)
    proto._address_found = True
    proto._address = 0x01
    proto.request_person_data()
    assert ser.write.called


def test_request_run_data():
    ser = Mock()
    proto = DaumProtocol(ser)
    proto._address_found = True
    proto._address = 0x01
    proto.request_run_data()
    assert ser.write.called


def test_parse_empty():
    ser = Mock()
    proto = DaumProtocol(ser)
    result = proto.parse(b"")
    assert result is False


def test_state_defaults():
    s = DaumState()
    assert s.power == 0.0
    assert s.cadence == 0.0
    assert s.gear == 1
    assert s.heart_rate == 0
    assert s.connected is False
