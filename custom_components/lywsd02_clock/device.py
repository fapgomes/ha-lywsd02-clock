"""BLE protocol layer for the LYWSD02 clock."""
from __future__ import annotations

import asyncio
import logging
import struct
from typing import Literal

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import DEFAULT_TIMEOUT, UUID_TIME, UUID_UNIT

_LOGGER = logging.getLogger(__name__)

ADVERTISEMENT_WAIT_SECONDS: float = 30.0
DIRECT_SCAN_SECONDS: float = 15.0


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


async def _wait_for_ha_advertisement(
    hass: HomeAssistant, mac: str, timeout: float
) -> BLEDevice | None:
    """Wait for HA's Bluetooth stack to see a connectable advertisement from mac."""
    event = asyncio.Event()

    @callback
    def _on_advertisement(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        event.set()

    unsub = bluetooth.async_register_callback(
        hass,
        _on_advertisement,
        bluetooth.BluetoothCallbackMatcher(address=mac.upper(), connectable=True),
        bluetooth.BluetoothScanningMode.ACTIVE,
    )
    try:
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
    finally:
        unsub()

    return bluetooth.async_ble_device_from_address(hass, mac, connectable=True)


async def _direct_bleak_scan(mac: str, timeout: float) -> BLEDevice | None:
    """Fall back to a direct bleak scan on the local OS Bluetooth adapter."""
    try:
        return await BleakScanner.find_device_by_address(mac, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — any scanner failure is a soft miss
        _LOGGER.debug("Direct bleak scan for %s failed: %s", mac, exc)
        return None


async def _resolve_ble_device(
    hass: HomeAssistant, mac: str, total_timeout: float
) -> BLEDevice | None:
    """Find a BLEDevice for mac, trying HA's cache, HA advertisement wait, then direct bleak scan."""
    ble_device = bluetooth.async_ble_device_from_address(hass, mac, connectable=True)
    if ble_device is not None:
        return ble_device

    ha_wait = max(1.0, total_timeout - DIRECT_SCAN_SECONDS)
    _LOGGER.debug(
        "No cached advertisement for %s; waiting up to %.0fs via HA BT stack", mac, ha_wait
    )
    ble_device = await _wait_for_ha_advertisement(hass, mac, ha_wait)
    if ble_device is not None:
        return ble_device

    _LOGGER.debug(
        "HA BT stack did not see %s; falling back to direct bleak scan for %.0fs",
        mac,
        DIRECT_SCAN_SECONDS,
    )
    return await _direct_bleak_scan(mac, DIRECT_SCAN_SECONDS)


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

    total_wait = min(float(timeout), ADVERTISEMENT_WAIT_SECONDS + DIRECT_SCAN_SECONDS)
    ble_device = await _resolve_ble_device(hass, mac, total_wait)
    if ble_device is None:
        raise DeviceNotFoundError(
            f"Could not find {mac} via HA Bluetooth or direct scan within {total_wait:.0f}s. "
            "Press any button on the clock to wake it, then try again. "
            "If this keeps failing, verify the MAC is correct and make sure "
            "a Bluetooth adapter or active BLE proxy is in range."
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
