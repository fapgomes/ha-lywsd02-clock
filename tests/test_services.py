"""Service-schema validation tests for lywsd02_clock.set_time."""
from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol

from homeassistant.setup import async_setup_component

from custom_components.lywsd02_clock.const import DOMAIN, SERVICE_SET_TIME


async def test_invalid_mac_rejected_by_schema(hass):
    assert await async_setup_component(hass, DOMAIN, {})
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, SERVICE_SET_TIME, {"mac": "not-a-mac"}, blocking=True
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
