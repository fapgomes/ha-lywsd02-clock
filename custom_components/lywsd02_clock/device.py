"""BLE protocol layer for the LYWSD02 clock."""
from __future__ import annotations

import asyncio
import inspect
import logging
import struct
from typing import Any, Literal

from bleak import BleakClient, BleakError
from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

try:
    from bleak.backends.bluezdbus.client import BleakClientBlueZDBus as _BluezBackendClient
except Exception:  # noqa: BLE001 — non-Linux or missing backend
    _BluezBackendClient = None  # type: ignore[assignment]

try:
    from bleak.backends.bluezdbus.scanner import BleakScannerBlueZDBus as _BluezBackendScanner
except Exception:  # noqa: BLE001 — non-Linux or missing backend
    _BluezBackendScanner = None  # type: ignore[assignment]

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import DEFAULT_TIMEOUT, UUID_TIME, UUID_UNIT

_LOGGER = logging.getLogger(__name__)

ADVERTISEMENT_WAIT_SECONDS: float = 30.0
DIRECT_CLIENT_TIMEOUT_SECONDS: float = 30.0


class DeviceNotFoundError(Exception):
    """Raised when no BLE path could reach the device."""


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


async def _resolve_ble_device_via_ha(
    hass: HomeAssistant, mac: str, timeout: float
) -> BLEDevice | None:
    """Return a BLEDevice for mac from HA's Bluetooth stack, waiting briefly if needed."""
    ble_device = bluetooth.async_ble_device_from_address(hass, mac, connectable=True)
    if ble_device is not None:
        return ble_device
    _LOGGER.debug("No cached advertisement for %s; waiting up to %.0fs via HA BT stack", mac, timeout)
    return await _wait_for_ha_advertisement(hass, mac, timeout)


async def _write_via_retry_connector(
    ble_device: BLEDevice,
    mac: str,
    payloads: tuple[bytes, bytes, bytes],
) -> None:
    """Connect through HA's Bluetooth stack (supports BLE proxies) and write the payloads."""
    time_payload, unit_payload, mode_payload = payloads
    try:
        client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            name=mac,
            max_attempts=3,
        )
    except Exception as exc:
        raise DeviceCommunicationError(f"HA connection failed: {exc}") from exc

    try:
        async with client:
            await client.write_gatt_char(UUID_TIME, time_payload)
            await client.write_gatt_char(UUID_UNIT, unit_payload)
            await client.write_gatt_char(UUID_TIME, mode_payload)
    except Exception as exc:
        raise DeviceCommunicationError(f"HA GATT write failed: {exc}") from exc


async def _write_via_direct_client(
    mac: str,
    payloads: tuple[bytes, bytes, bytes],
    timeout: float,
) -> None:
    """Connect via BleakClient (goes through habluetooth wrapper in HA)."""
    time_payload, unit_payload, mode_payload = payloads
    client = BleakClient(mac, timeout=timeout)
    try:
        async with client:
            await client.write_gatt_char(UUID_TIME, time_payload)
            await client.write_gatt_char(UUID_UNIT, unit_payload)
            await client.write_gatt_char(UUID_TIME, mode_payload)
    except BleakError as exc:
        raise DeviceCommunicationError(f"BleakClient failed: {exc}") from exc
    except Exception as exc:
        raise DeviceCommunicationError(f"BleakClient error: {exc}") from exc


async def _discover_via_raw_bluez(mac: str, timeout: float) -> BLEDevice | None:
    """Start an active scan with the bluezdbus backend scanner (bypassing HA's patch)
    and wait for an advertisement from the requested MAC.
    """
    if _BluezBackendScanner is None:
        return None

    found = asyncio.Event()
    found_device: dict[str, BLEDevice] = {}
    upper_mac = mac.upper()

    def _on_detection(device: BLEDevice, advertisement_data: Any) -> None:
        if device.address.upper() == upper_mac:
            found_device["device"] = device
            found.set()

    scanner = None
    for attempt in (
        # Current bleak (≥0.22): all three required
        lambda: _BluezBackendScanner(
            detection_callback=_on_detection,
            service_uuids=None,
            scanning_mode="active",
        ),
        # Positional-only signature
        lambda: _BluezBackendScanner(_on_detection, None, "active"),
        # Older bleak: only callback kwarg
        lambda: _BluezBackendScanner(detection_callback=_on_detection),
        # Oldest: no args, use register_detection_callback afterwards
        lambda: _BluezBackendScanner(),
    ):
        try:
            scanner = attempt()
            break
        except TypeError:
            continue
    if scanner is None:
        _LOGGER.debug("Could not construct BleakScannerBlueZDBus with any known signature")
        return None
    if hasattr(scanner, "register_detection_callback") and not hasattr(scanner, "_callback"):
        scanner.register_detection_callback(_on_detection)

    try:
        await scanner.start()
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("Raw bluez scan start failed for %s: %s", mac, exc)
        return None

    try:
        try:
            await asyncio.wait_for(found.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            _LOGGER.debug("Raw bluez scan did not see %s within %.0fs", mac, timeout)
            return None
    finally:
        try:
            await scanner.stop()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Raw bluez scan stop failed for %s: %s", mac, exc)

    return found_device.get("device")


async def _write_via_bluezdbus_direct(
    mac: str,
    payloads: tuple[bytes, bytes, bytes],
    timeout: float,
) -> None:
    """Connect by importing the bluezdbus backend class directly.

    This bypasses `habluetooth`'s wrapper (which replaces the top-level
    `bleak.BleakClient`) and talks to `bluez` over D-Bus, like the
    `pygatt`/`bluepy`-based plugins (`ashald/home-assistant-lywsd02`,
    `h4/lywsd02`) do.

    Starts its own active scan with the raw backend scanner first so that
    bluez has a fresh D-Bus device object to connect to.
    """
    if _BluezBackendClient is None:
        raise DeviceCommunicationError(
            "bluez D-Bus backend unavailable (non-Linux host or missing dependency)"
        )

    # Proactively scan for the device via the raw backend scanner.
    scan_timeout = min(timeout, 20.0)
    fresh_device = await _discover_via_raw_bluez(mac, scan_timeout)
    if fresh_device is not None:
        _LOGGER.debug("Raw bluez scan found %s", mac)
        client_target: BLEDevice | str = fresh_device
    else:
        _LOGGER.debug(
            "Raw bluez scan missed %s; trying bluezdbus connect by MAC anyway", mac
        )
        client_target = mac

    time_payload, unit_payload, mode_payload = payloads
    client = _BluezBackendClient(client_target, timeout=timeout)

    connect_kwargs: dict[str, Any] = {}
    try:
        sig = inspect.signature(client.connect)
        if "pair" in sig.parameters:
            connect_kwargs["pair"] = False
        if "timeout" in sig.parameters:
            connect_kwargs["timeout"] = timeout
    except (TypeError, ValueError):
        pass

    try:
        await client.connect(**connect_kwargs)
    except TypeError:
        # Fallback for signatures we couldn't introspect (e.g. C-extension wrappers)
        try:
            await client.connect(False, timeout)  # (pair, timeout) positional
        except TypeError:
            try:
                await client.connect()
            except BleakError as exc:
                raise DeviceCommunicationError(f"bluezdbus connect failed: {exc}") from exc
            except Exception as exc:
                raise DeviceCommunicationError(f"bluezdbus connect error: {exc}") from exc
        except BleakError as exc:
            raise DeviceCommunicationError(f"bluezdbus connect failed: {exc}") from exc
    except BleakError as exc:
        raise DeviceCommunicationError(f"bluezdbus connect failed: {exc}") from exc
    except Exception as exc:
        raise DeviceCommunicationError(f"bluezdbus connect error: {exc}") from exc

    try:
        try:
            await client.write_gatt_char(UUID_TIME, time_payload, response=True)
            await client.write_gatt_char(UUID_UNIT, unit_payload, response=True)
            await client.write_gatt_char(UUID_TIME, mode_payload, response=True)
        except BleakError as exc:
            raise DeviceCommunicationError(f"bluezdbus write failed: {exc}") from exc
        except Exception as exc:
            raise DeviceCommunicationError(f"bluezdbus write error: {exc}") from exc
    finally:
        try:
            await client.disconnect()
        except Exception as exc:  # noqa: BLE001 — disconnect failure shouldn't mask real error
            _LOGGER.debug("bluezdbus disconnect failed for %s: %s", mac, exc)


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

    Tries two paths in order:
      1. Home Assistant's Bluetooth stack (works with local adapters *and* BLE proxies).
      2. Direct `BleakClient(mac)` via the OS bluez cache (local adapter only, but
         works even when HA's cache has no fresh advertisement).

    Raises DeviceNotFoundError if both paths fail.
    """
    if timestamp_utc is None or tz_offset_hours is None:
        ts_now, tz_now = _current_time_and_offset()
        if timestamp_utc is None:
            timestamp_utc = ts_now
        if tz_offset_hours is None:
            tz_offset_hours = tz_now

    payloads = (
        _build_time_payload(timestamp_utc, tz_offset_hours),
        _build_unit_payload(temp_unit),
        _build_mode_payload(clock_mode),
    )

    ha_wait = min(float(timeout), ADVERTISEMENT_WAIT_SECONDS)
    ha_error: str

    ble_device = await _resolve_ble_device_via_ha(hass, mac, ha_wait)
    if ble_device is not None:
        try:
            await _write_via_retry_connector(ble_device, mac, payloads)
            _LOGGER.debug("Wrote time/unit/mode to %s via HA Bluetooth", mac)
            return
        except DeviceCommunicationError as exc:
            ha_error = str(exc)
            _LOGGER.debug("HA path failed for %s (%s); falling back to direct", mac, ha_error)
    else:
        ha_error = f"no advertisement received within {ha_wait:.0f}s"
        _LOGGER.debug("HA path found no advertisement for %s; trying direct", mac)

    direct_timeout = min(float(timeout), DIRECT_CLIENT_TIMEOUT_SECONDS)
    direct_error: str
    try:
        await _write_via_direct_client(mac, payloads, direct_timeout)
        _LOGGER.debug("Wrote time/unit/mode to %s via BleakClient", mac)
        return
    except DeviceCommunicationError as exc:
        direct_error = str(exc)
        _LOGGER.debug(
            "BleakClient path failed for %s (%s); trying bluezdbus backend directly",
            mac,
            direct_error,
        )

    try:
        await _write_via_bluezdbus_direct(mac, payloads, direct_timeout)
        _LOGGER.debug("Wrote time/unit/mode to %s via bluezdbus backend", mac)
        return
    except DeviceCommunicationError as bluezdbus_exc:
        raise DeviceNotFoundError(
            f"Could not reach {mac}. "
            f"HA Bluetooth path: {ha_error}. "
            f"BleakClient: {direct_error}. "
            f"bluezdbus direct: {bluezdbus_exc}. "
            "Press any button on the clock to wake it and try again. "
            "If you rely exclusively on a BLE proxy (no local adapter), check "
            "Settings → Devices & Services → Bluetooth to confirm the proxy is "
            "seeing advertisements from the device."
        ) from bluezdbus_exc
