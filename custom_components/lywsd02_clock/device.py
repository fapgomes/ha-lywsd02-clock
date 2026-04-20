"""BLE protocol layer for the LYWSD02 clock."""
from __future__ import annotations

import logging
import struct
from typing import Literal

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DEFAULT_TIMEOUT, UUID_TIME, UUID_UNIT

_LOGGER = logging.getLogger(__name__)


class DeviceNotFoundError(Exception):
    """Raised when the BLE stack has no record of the MAC."""


class DeviceCommunicationError(Exception):
    """Raised on any BLE connection or GATT write failure."""


def _build_time_payload(timestamp_utc: int, tz_offset_hours: int) -> bytes:
    return struct.pack("<Ib", timestamp_utc, tz_offset_hours)


def _build_unit_payload(temp_unit: str) -> bytes:
    value = 0x01 if temp_unit.upper() == "F" else 0xFF
    return struct.pack("B", value)


def _build_mode_payload(clock_mode: int) -> bytes:
    value = 0xAA if int(clock_mode) == 12 else 0x00
    return struct.pack("<IHB", 0, 0, value)


def _current_time_and_offset() -> tuple[int, int]:
    local_now = dt_util.now()
    timestamp_utc = int(local_now.timestamp())
    utcoffset = local_now.utcoffset()
    tz_offset_hours = int(utcoffset.total_seconds() / 3600) if utcoffset else 0
    return timestamp_utc, tz_offset_hours


async def set_time(
    hass: HomeAssistant,
    mac: str,
    *,
    temp_unit: Literal["C", "F"] = "C",
    clock_mode: Literal[12, 24] = 24,
    timestamp_utc: int | None = None,
    tz_offset_hours: int | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> None:
    """Write time, temperature unit and clock mode to the device.

    Raises DeviceNotFoundError if the BLE stack doesn't know the MAC, or
    DeviceCommunicationError on any connect / GATT failure.
    """
    if timestamp_utc is None or tz_offset_hours is None:
        ts_now, tz_now = _current_time_and_offset()
        if timestamp_utc is None:
            timestamp_utc = ts_now
        if tz_offset_hours is None:
            tz_offset_hours = tz_now

    ble_device = bluetooth.async_ble_device_from_address(hass, mac, connectable=True)
    if ble_device is None:
        raise DeviceNotFoundError(
            f"No BLE device with MAC {mac} known to the Bluetooth stack"
        )

    time_payload = _build_time_payload(timestamp_utc, tz_offset_hours)
    unit_payload = _build_unit_payload(temp_unit)
    mode_payload = _build_mode_payload(clock_mode)

    try:
        client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            name=mac,
            max_attempts=3,
        )
    except Exception as exc:
        raise DeviceCommunicationError(f"Connection failed: {exc}") from exc

    try:
        async with client:
            await client.write_gatt_char(UUID_TIME, time_payload)
            await client.write_gatt_char(UUID_UNIT, unit_payload)
            await client.write_gatt_char(UUID_TIME, mode_payload)
    except Exception as exc:
        raise DeviceCommunicationError(f"GATT write failed: {exc}") from exc

    _LOGGER.debug(
        "Wrote time=%s tz=%+d temp=%s mode=%s to %s",
        timestamp_utc,
        tz_offset_hours,
        temp_unit,
        clock_mode,
        mac,
    )
