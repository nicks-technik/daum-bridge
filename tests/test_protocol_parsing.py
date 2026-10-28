from daum_bridge.serial.daum import DaumProtocol, DaumState
from unittest.mock import Mock


def test_address_discovery():
    ser = Mock()
    proto = DaumProtocol(ser)
    # Simulate address response
    data = bytes([0xA1, 0x01])
    found = proto.parse(data)
    assert found is True
    assert proto._address == 0x01


def test_run_data_parsing():
    ser = Mock()
    proto = DaumProtocol(ser)
    proto._address_found = True
    proto._address = 0x01
    proto.state = DaumState()
    # Build minimal run_data frame: A4 addr 00 ... rpm at +6, power_raw at +5
    frame = bytearray(20)
    frame[0] = 0xA4
    frame[1] = 0x01  # addr
    frame[2] = 0x00
    frame[5] = 10   # power raw
    frame[6] = 90   # rpm
    frame[16] = 3   # gear
    proto.parse(bytes(frame))
    assert proto.state.cadence == 90.0
    assert proto.state.gear == 3


def test_person_data_hr():
    ser = Mock()
    proto = DaumProtocol(ser)
    proto._address_found = True
    proto._address = 0x01
    proto.state = DaumState()
    frame = bytearray(15)
    frame[0] = 0xA2
    frame[1] = 0x01
    frame[6] = 145
    proto.parse(bytes(frame))
    assert proto.state.heart_rate == 145
