"""Coordinator battery-state tests."""
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.lywsd02_clock.coordinator import LYWSD02Coordinator

MAC = "e7:2e:01:42:60:ff"
COORD_NS = "custom_components.lywsd02_clock.coordinator"


def _make_entry():
    entry = MagicMock()
    entry.options = {}
    entry.data = {}
    return entry


async def test_battery_level_stored_on_successful_sync(hass):
    coord = LYWSD02Coordinator(hass, _make_entry(), MAC)
    with patch(f"{COORD_NS}.set_time", new=AsyncMock(return_value=88)):
        assert await coord.async_sync() is True
    assert coord.battery_level == 88


async def test_battery_level_kept_when_read_returns_none(hass):
    coord = LYWSD02Coordinator(hass, _make_entry(), MAC)
    coord.battery_level = 77
    with patch(f"{COORD_NS}.set_time", new=AsyncMock(return_value=None)):
        assert await coord.async_sync() is True
    assert coord.battery_level == 77


async def test_battery_level_untouched_on_failed_sync(hass):
    from custom_components.lywsd02_clock.device import DeviceCommunicationError

    coord = LYWSD02Coordinator(hass, _make_entry(), MAC)
    coord.battery_level = 55
    with patch(
        f"{COORD_NS}.set_time",
        new=AsyncMock(side_effect=DeviceCommunicationError("boom")),
    ):
        assert await coord.async_sync() is False
    assert coord.battery_level == 55
