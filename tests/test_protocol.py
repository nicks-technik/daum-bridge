from daum_bridge.serial.daum import DaumProtocol, DaumCmd
from unittest.mock import Mock


def test_build_command_get_address():
    ser = Mock()
    proto = DaumProtocol(ser)
    cmd = proto.build_command(DaumCmd.GET_ADDRESS)
    assert cmd == bytes([0xA1])


def test_build_command_set_watt():
    ser = Mock()
    proto = DaumProtocol(ser)
    proto._address = 0x01
    proto._address_found = True
    cmd = proto.build_command(DaumCmd.SET_WATT, 0x01, 200)
    assert cmd == bytes([0xA6, 0x01, 200])


def test_build_command_set_gear():
    ser = Mock()
    proto = DaumProtocol(ser)
    cmd = proto.build_command(DaumCmd.SET_GEAR, 0x05, 3)
    assert cmd == bytes([0xA7, 0x05, 3])
