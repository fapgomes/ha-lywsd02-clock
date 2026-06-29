"""Select entity: sync frequency (daily / weekly / monthly / DST-only)."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_FREQUENCY, DOMAIN, FREQUENCIES
from .coordinator import LYWSD02Coordinator
from .entity import LYWSD02Entity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: LYWSD02Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([FrequencySelect(coordinator)])


class FrequencySelect(LYWSD02Entity, SelectEntity):
    _attr_translation_key = "frequency"
    _attr_options = FREQUENCIES

    def __init__(self, coordinator: LYWSD02Coordinator) -> None:
        super().__init__(coordinator, "frequency")

    @property
    def current_option(self) -> str:
        return self.coordinator.frequency

    async def async_select_option(self, option: str) -> None:
        entry = self.coordinator.entry
        new_options = {**entry.options, CONF_FREQUENCY: option}
        self.hass.config_entries.async_update_entry(entry, options=new_options)
