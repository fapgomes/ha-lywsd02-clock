"""Byte-exact characterization tests for the GATT payload builders."""
from custom_components.lywsd02_clock.device import (
    _build_mode_payload,
    _build_time_payload,
    _build_unit_payload,
)


def test_time_payload_positive_offset():
    assert _build_time_payload(1700000000, 1) == b"\x00\xf1\x53\x65\x01"


def test_time_payload_negative_offset():
    assert _build_time_payload(1700000000, -3) == b"\x00\xf1\x53\x65\xfd"


def test_unit_payload_celsius():
    assert _build_unit_payload("C") == b"\xff"


def test_unit_payload_fahrenheit_any_case():
    assert _build_unit_payload("F") == b"\x01"
    assert _build_unit_payload("f") == b"\x01"


def test_mode_payload_12h():
    assert _build_mode_payload(12) == b"\x00\x00\x00\x00\x00\x00\xaa"


def test_mode_payload_24h():
    assert _build_mode_payload(24) == b"\x00\x00\x00\x00\x00\x00\x00"
