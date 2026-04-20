"""The LYWSD02 Clock integration."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_CLOCK_MODE,
    CONF_MAC,
    CONF_TEMP_UNIT,
    CLOCK_MODES,
    DEFAULT_CLOCK_MODE,
    DEFAULT_TEMP_UNIT,
    DEFAULT_TIMEOUT,
    DOMAIN,
    SERVICE_SET_TIME,
    TEMP_UNITS,
)
from .coordinator import LYWSD02Coordinator
from .device import DeviceCommunicationError, DeviceNotFoundError, set_time

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SWITCH,
]

SET_TIME_SCHEMA = vol.Schema(
    {
        vol.Required("mac"): cv.string,
        vol.Optional("timestamp"): vol.Coerce(int),
        vol.Optional("tz_offset"): vol.Coerce(int),
        vol.Optional("temp_mode"): vol.In(TEMP_UNITS),
        vol.Optional("clock_mode"): vol.All(vol.Coerce(int), vol.In(CLOCK_MODES)),
        vol.Optional("timeout", default=DEFAULT_TIMEOUT): vol.Coerce(float),
    }
)


def _normalize_mac(mac: str) -> str:
    return mac.strip().lower()


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the domain-level service (shared across all entries)."""
    hass.data.setdefault(DOMAIN, {})

    async def _handle_set_time(call: ServiceCall) -> None:
        mac = _normalize_mac(call.data["mac"])
        coordinator: LYWSD02Coordinator | None = None
        for coord in hass.data.get(DOMAIN, {}).values():
            if isinstance(coord, LYWSD02Coordinator) and coord.mac == mac:
                coordinator = coord
                break

        if coordinator is not None and all(
            key not in call.data for key in ("timestamp", "tz_offset", "temp_mode", "clock_mode")
        ):
            success = await coordinator.async_sync()
            if not success:
                raise HomeAssistantError(
                    f"Sync failed for {mac}: {coordinator.last_error}"
                )
            return

        temp_unit = call.data.get(
            "temp_mode",
            coordinator.temp_unit if coordinator else DEFAULT_TEMP_UNIT,
        )
        clock_mode = int(
            call.data.get(
                "clock_mode",
                coordinator.clock_mode if coordinator else DEFAULT_CLOCK_MODE,
            )
        )
        timestamp_utc = call.data.get("timestamp")
        tz_offset_hours = call.data.get("tz_offset")
        timeout = call.data.get("timeout", DEFAULT_TIMEOUT)

        try:
            await set_time(
                hass,
                mac,
                temp_unit=temp_unit,
                clock_mode=clock_mode,
                timestamp_utc=timestamp_utc,
                tz_offset_hours=tz_offset_hours,
                timeout=timeout,
            )
        except (DeviceNotFoundError, DeviceCommunicationError) as exc:
            raise HomeAssistantError(str(exc)) from exc

        if coordinator is not None:
            from homeassistant.util import dt as dt_util

            coordinator.last_attempt = dt_util.utcnow()
            coordinator.last_sync = dt_util.utcnow()
            coordinator.last_status = "success"
            coordinator.last_error = None
            coordinator.last_utcoffset = dt_util.now().utcoffset()
            coordinator.async_update_listeners()

    if not hass.services.has_service(DOMAIN, SERVICE_SET_TIME):
        hass.services.async_register(
            DOMAIN, SERVICE_SET_TIME, _handle_set_time, schema=SET_TIME_SCHEMA
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry: build coordinator, register schedule, forward platforms."""
    mac = _normalize_mac(entry.data[CONF_MAC])
    coordinator = LYWSD02Coordinator(hass, entry, mac)
    coordinator.start_schedule()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry: stop schedule, unload platforms."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    coordinator: LYWSD02Coordinator | None = hass.data.get(DOMAIN, {}).pop(
        entry.entry_id, None
    )
    if coordinator is not None:
        coordinator.shutdown()
    return unload_ok
