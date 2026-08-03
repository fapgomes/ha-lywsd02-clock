"""Service-schema validation tests for lywsd02_clock.set_time."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol

from homeassistant.setup import async_setup_component

from custom_components.lywsd02_clock.const import DOMAIN, SERVICE_SET_TIME
from custom_components.lywsd02_clock.coordinator import LYWSD02Coordinator


async def test_invalid_mac_rejected_by_schema(hass):
    assert await async_setup_component(hass, DOMAIN, {})
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, SERVICE_SET_TIME, {"mac": "not-a-mac"}, blocking=True
        )


async def test_tz_offset_out_of_range_rejected_by_schema(hass):
    assert await async_setup_component(hass, DOMAIN, {})
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_TIME,
            {"mac": "e7:2e:01:42:60:ff", "tz_offset": 200},
            blocking=True,
        )


async def test_valid_mac_normalized_before_set_time(hass):
    assert await async_setup_component(hass, DOMAIN, {})
    with patch(
        "custom_components.lywsd02_clock.set_time", new=AsyncMock()
    ) as mock_set_time:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_TIME,
            {"mac": "E7:2E:01:42:60:FF", "timestamp": 1700000000},
            blocking=True,
        )
    assert mock_set_time.await_count == 1
    assert mock_set_time.await_args.args[1] == "e7:2e:01:42:60:ff"


async def test_service_handler_feeds_coordinator_battery(hass):
    """The handler must push the battery level returned by set_time onto the
    matching coordinator, mimicking what async_setup_entry wires up."""
    assert await async_setup_component(hass, DOMAIN, {})

    entry = MagicMock()
    entry.options = {}
    entry.data = {}
    coord = LYWSD02Coordinator(hass, entry, "e7:2e:01:42:60:ff")
    hass.data[DOMAIN]["test_entry"] = coord

    with patch(
        "custom_components.lywsd02_clock.set_time",
        new=AsyncMock(return_value=42),
    ):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_TIME,
            {"mac": "E7:2E:01:42:60:FF", "timestamp": 1700000000},
            blocking=True,
        )
    assert coord.battery_level == 42
