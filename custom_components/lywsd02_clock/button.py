"""Button entity: manual sync trigger."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import LYWSD02Coordinator
from .entity import LYWSD02Entity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: LYWSD02Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SyncNowButton(coordinator)])


class SyncNowButton(LYWSD02Entity, ButtonEntity):
    _attr_translation_key = "sync_now"

    def __init__(self, coordinator: LYWSD02Coordinator) -> None:
        super().__init__(coordinator, "sync_now")

    async def async_press(self) -> None:
        await self.coordinator.async_sync()
