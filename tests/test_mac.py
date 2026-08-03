"""Tests for MAC normalization and validation helpers."""
from custom_components.lywsd02_clock.mac import is_valid_mac, normalize_mac


def test_normalize_lowercases_and_strips():
    assert normalize_mac(" E7:2E:01:42:60:FF ") == "e7:2e:01:42:60:ff"


def test_normalize_is_idempotent():
    assert normalize_mac("e7:2e:01:42:60:ff") == "e7:2e:01:42:60:ff"


def test_valid_macs_accepted_any_case():
    assert is_valid_mac("e7:2e:01:42:60:ff")
    assert is_valid_mac("E7:2E:01:42:60:FF")
    assert is_valid_mac(" AA:BB:CC:DD:EE:0f ")


def test_invalid_macs_rejected():
    assert not is_valid_mac("")
    assert not is_valid_mac("banana")
    assert not is_valid_mac("e7:2e:01:42:60")          # 5 octets
    assert not is_valid_mac("e7:2e:01:42:60:ff:aa")    # 7 octets
    assert not is_valid_mac("e72e014260ff")            # no separators
    assert not is_valid_mac("g7:2e:01:42:60:ff")       # non-hex
