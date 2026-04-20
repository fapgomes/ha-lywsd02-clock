"""Switch entity: auto-sync on/off."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_AUTO_SYNC, DOMAIN
from .coordinator import LYWSD02Coordinator
from .entity import LYWSD02Entity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: LYWSD02Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AutoSyncSwitch(coordinator)])


class AutoSyncSwitch(LYWSD02Entity, SwitchEntity):
    _attr_translation_key = "auto_sync"

    def __init__(self, coordinator: LYWSD02Coordinator) -> None:
        super().__init__(coordinator, "auto_sync")

    @property
    def is_on(self) -> bool:
        return self.coordinator.auto_sync_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set_option(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set_option(False)

    async def _set_option(self, value: bool) -> None:
        entry = self.coordinator.entry
        new_options = {**entry.options, CONF_AUTO_SYNC: value}
        self.hass.config_entries.async_update_entry(entry, options=new_options)
