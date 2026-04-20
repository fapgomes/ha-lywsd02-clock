"""Sensor entities: last_sync, next_sync, last_sync_status."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, STATUS_FAILED, STATUS_NEVER, STATUS_SUCCESS
from .coordinator import LYWSD02Coordinator
from .entity import LYWSD02Entity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: LYWSD02Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            LastSyncSensor(coordinator),
            NextSyncSensor(coordinator),
            LastSyncStatusSensor(coordinator),
        ]
    )


class LastSyncSensor(LYWSD02Entity, SensorEntity):
    _attr_translation_key = "last_sync"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: LYWSD02Coordinator) -> None:
        super().__init__(coordinator, "last_sync")

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.last_sync


class NextSyncSensor(LYWSD02Entity, SensorEntity):
    _attr_translation_key = "next_sync"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: LYWSD02Coordinator) -> None:
        super().__init__(coordinator, "next_sync")

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.compute_next_sync()


class LastSyncStatusSensor(LYWSD02Entity, SensorEntity):
    _attr_translation_key = "last_sync_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [STATUS_SUCCESS, STATUS_FAILED, STATUS_NEVER]

    def __init__(self, coordinator: LYWSD02Coordinator) -> None:
        super().__init__(coordinator, "last_sync_status")

    @property
    def native_value(self) -> str:
        return self.coordinator.last_status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "error_message": self.coordinator.last_error,
            "attempted_at": self.coordinator.last_attempt,
        }
