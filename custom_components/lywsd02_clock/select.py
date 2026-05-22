"""Select entity: clock display mode (12h / 24h)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CLOCK_MODE, DOMAIN
from .coordinator import LYWSD02Coordinator
from .entity import LYWSD02Entity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: LYWSD02Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ClockModeSelect(coordinator)])


class ClockModeSelect(LYWSD02Entity, SelectEntity):
    _attr_translation_key = "clock_mode"
    _attr_options = ["24", "12"]

    def __init__(self, coordinator: LYWSD02Coordinator) -> None:
        super().__init__(coordinator, "clock_mode")

    @property
    def current_option(self) -> str:
        return str(self.coordinator.clock_mode)

    async def async_select_option(self, option: str) -> None:
        mode = int(option)
        entry = self.coordinator.entry
        new_options = {**entry.options, CONF_CLOCK_MODE: mode}
        self.hass.config_entries.async_update_entry(entry, options=new_options)

        await self.hass.services.async_call(
            DOMAIN,
            "set_time",
            {"mac": self.coordinator.mac, "clock_mode": mode},
            blocking=True,
        )
