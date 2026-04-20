"""Base entity for the LYWSD02 Clock integration."""
from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import LYWSD02Coordinator


class LYWSD02Entity(CoordinatorEntity[LYWSD02Coordinator]):
    """Shared device wiring and unique_id prefix for all LYWSD02 entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: LYWSD02Coordinator, suffix: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_{suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.mac)},
            connections={(CONNECTION_BLUETOOTH, coordinator.mac)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=coordinator.entry.title,
        )
