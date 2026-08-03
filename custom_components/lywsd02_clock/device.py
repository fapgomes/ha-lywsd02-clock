"""BLE protocol layer for the LYWSD02 clock.

Single write path through Home Assistant's Bluetooth stack
(`homeassistant.components.bluetooth` + `bleak-retry-connector`), which works
with local adapters and ESPHome BLE proxies alike.

Three defects made the previous HA-stack path dead code (see
docs/superpowers/specs/2026-08-03-ble-stack-rewrite-design.md):
  1. lowercase MAC lookups against habluetooth's uppercase-keyed history;
  2. an advertisement wait that existed but was never invoked;
  3. `async with` on the already-connected client returned by
     establish_connection, triggering a second connect().
"""
from __future__ import annotations

import asyncio
import logging
import struct
from typing import Literal

from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import DEFAULT_TIMEOUT, UUID_TIME, UUID_UNIT

_LOGGER = logging.getLogger(__name__)


class DeviceNotFoundError(Exception):
    """Raised when no connectable advertisement was seen within the timeout."""


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


async def _resolve_ble_device(
    hass: HomeAssistant, mac: str, timeout: float
) -> BLEDevice | None:
    """Return a connectable BLEDevice for mac, waiting for an advertisement.

    habluetooth's history lookup is a plain case-sensitive dict.get() against
    uppercase keys, so the address must be uppercased here. (The config entry
    and unique_id keep the lowercase convention.)
    """
    address = mac.upper()
    ble_device = bluetooth.async_ble_device_from_address(
        hass, address, connectable=True
    )
    if ble_device is not None:
        return ble_device

    _LOGGER.debug(
        "No connectable BLEDevice cached for %s; waiting up to %.0fs "
        "for an advertisement",
        address,
        timeout,
    )
    future: asyncio.Future[BLEDevice] = asyncio.get_running_loop().create_future()

    @callback
    def _on_advertisement(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        # async_register_callback fires immediately for devices HA already
        # knows, even when no connectable BLEDevice is available yet — so
        # re-query the history instead of trusting the callback itself.
        device = bluetooth.async_ble_device_from_address(
            hass, address, connectable=True
        )
        if device is not None and not future.done():
            future.set_result(device)

    unsub = bluetooth.async_register_callback(
        hass,
        _on_advertisement,
        bluetooth.BluetoothCallbackMatcher(address=address, connectable=True),
        bluetooth.BluetoothScanningMode.ACTIVE,
    )
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except TimeoutError:
        return None
    finally:
        unsub()


async def _write_payloads(
    ble_device: BLEDevice,
    mac: str,
    payloads: tuple[bytes, bytes, bytes | None],
) -> None:
    """Connect once and write the payloads with Write-Request semantics.

    The client returned by establish_connection is ALREADY connected — do not
    wrap it in `async with`, which would call connect() a second time. Both
    characteristics advertise `write` only (no write-without-response), and
    the LYWSD02 firmware ignores unacknowledged writes, so response=True is
    explicit.
    """
    time_payload, unit_payload, mode_payload = payloads
    try:
        client = await establish_connection(
            BleakClientWithServiceCache, ble_device, name=mac, max_attempts=3
        )
    except Exception as exc:
        raise DeviceCommunicationError(f"Connection failed: {exc}") from exc

    try:
        await client.write_gatt_char(UUID_TIME, time_payload, response=True)
        await client.write_gatt_char(UUID_UNIT, unit_payload, response=True)
        if mode_payload is not None:
            await client.write_gatt_char(UUID_TIME, mode_payload, response=True)
    except Exception as exc:
        raise DeviceCommunicationError(f"GATT write failed: {exc}") from exc
    finally:
        try:
            await client.disconnect()
        except Exception as exc:  # noqa: BLE001 — must not mask a write error
            _LOGGER.debug("Disconnect failed for %s: %s", mac, exc)


async def set_time(
    hass: HomeAssistant,
    mac: str,
    *,
    temp_unit: Literal["C", "F"] = "C",
    clock_mode: Literal[12, 24] = 24,
    timestamp_utc: int | None = None,
    tz_offset_hours: int | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    write_clock_mode: bool = False,
) -> None:
    """Write time, temperature unit and (optionally) clock mode to the device.

    Uses Home Assistant's Bluetooth stack exclusively: works with the host's
    own adapter and with ESPHome BLE proxies.

    Raises DeviceNotFoundError if no connectable advertisement is seen within
    `timeout`, DeviceCommunicationError on connection or GATT write failure.
    """
    ble_device = await _resolve_ble_device(hass, mac, timeout)
    if ble_device is None:
        raise DeviceNotFoundError(
            f"No advertisement from {mac} within {timeout:.0f}s. Press any "
            "button on the clock to wake it, and make sure it is in range of "
            "the Home Assistant host's Bluetooth adapter or an ESPHome "
            "Bluetooth proxy."
        )

    # Capture the timestamp only now, immediately before the write — not
    # before the advertisement wait above, which can block up to `timeout`
    # (plus establish_connection's own retries) and would otherwise leave
    # the clock set that many seconds slow.
    if timestamp_utc is None or tz_offset_hours is None:
        ts_now, tz_now = _current_time_and_offset()
        if timestamp_utc is None:
            timestamp_utc = ts_now
        if tz_offset_hours is None:
            tz_offset_hours = tz_now

    payloads = (
        _build_time_payload(timestamp_utc, tz_offset_hours),
        _build_unit_payload(temp_unit),
        _build_mode_payload(clock_mode) if write_clock_mode else None,
    )

    await _write_payloads(ble_device, mac, payloads)
    _LOGGER.debug("Wrote time/unit/mode to %s via HA Bluetooth", mac)
