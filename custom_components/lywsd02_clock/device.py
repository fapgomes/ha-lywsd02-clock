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
from typing import Any, Final, Literal

from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import DEFAULT_TIMEOUT, UUID_BATTERY, UUID_TIME, UUID_UNIT

_LOGGER = logging.getLogger(__name__)

# The LYWSD02 intermittently drops the BLE link right after connect (BlueZ
# surfaces this mid-write as UNLIKELY_ERROR 0x0E, or as a "Service Discovery
# has not been performed yet" BleakError on the next write to the now-dead
# connection). Retrying on a FRESH connection — the same tactic the legacy
# pygatt path relied on — reliably works around it.
WRITE_ATTEMPTS: Final = 3
WRITE_RETRY_DELAY_SECONDS: float = 2.0

# The device sometimes applies a write even though it drops the link before
# sending the Write-Response back — so a lost ACK is a false negative, not
# proof the write failed. A read-back within this many seconds of the
# intended timestamp is treated as confirmation.
VERIFY_TOLERANCE_SECONDS: Final = 30


class DeviceNotFoundError(Exception):
    """Raised when no connectable advertisement was seen within the timeout."""


class DeviceCommunicationError(Exception):
    """Raised on any BLE connection or GATT write failure."""


class DeviceConnectionError(DeviceCommunicationError):
    """Raised when establish_connection itself fails (no write was attempted).

    Internal: a subclass of DeviceCommunicationError, so existing callers that
    catch the public error keep working unchanged. Used to skip the
    read-back-verification step, which only makes sense when a write may
    actually have reached the device.
    """


def _build_time_payload(timestamp_utc: int, tz_offset_hours: int) -> bytes:
    return struct.pack("<Ib", timestamp_utc, tz_offset_hours)


def _build_unit_payload(temp_unit: str) -> bytes:
    value = 0x01 if temp_unit.upper() == "F" else 0xFF
    return struct.pack("B", value)


def _build_mode_payload(clock_mode: int) -> bytes:
    value = 0xAA if int(clock_mode) == 12 else 0x00
    return struct.pack("<IHB", 0, 0, value)


def _parse_battery(value: Any) -> int | None:
    """Parse the battery characteristic value (1 byte, percent)."""
    try:
        level = int(value[0])
    except Exception:  # noqa: BLE001 — malformed/absent value is a soft failure
        return None
    return level if 0 <= level <= 100 else None


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
) -> int | None:
    """Connect once and write the payloads with Write-Request semantics.

    The client returned by establish_connection is ALREADY connected — do not
    wrap it in `async with`, which would call connect() a second time. Both
    characteristics advertise `write` only (no write-without-response), and
    the LYWSD02 firmware ignores unacknowledged writes, so response=True is
    explicit.

    On success, also reads the battery level (percent) on the same
    connection, best-effort — a failed battery read never fails the sync.
    """
    time_payload, unit_payload, mode_payload = payloads
    try:
        client = await establish_connection(
            BleakClientWithServiceCache, ble_device, name=mac, max_attempts=3
        )
    except Exception as exc:
        raise DeviceConnectionError(f"Connection failed: {exc}") from exc

    try:
        await client.write_gatt_char(UUID_TIME, time_payload, response=True)
        await client.write_gatt_char(UUID_UNIT, unit_payload, response=True)
        if mode_payload is not None:
            await client.write_gatt_char(UUID_TIME, mode_payload, response=True)
    except Exception as exc:
        raise DeviceCommunicationError(f"GATT write failed: {exc}") from exc
    else:
        # Battery is read best-effort on the connection we already have; a
        # failure here must never fail the sync that just succeeded.
        battery: int | None = None
        try:
            battery = _parse_battery(await client.read_gatt_char(UUID_BATTERY))
        except Exception as exc:  # noqa: BLE001 — best-effort read
            _LOGGER.debug("Battery read failed for %s: %s", mac, exc)
        return battery
    finally:
        try:
            await client.disconnect()
        except Exception as exc:  # noqa: BLE001 — must not mask a write error
            _LOGGER.debug("Disconnect failed for %s: %s", mac, exc)


async def _read_back_matches(
    ble_device: BLEDevice,
    mac: str,
    expected_timestamp: int,
    expected_tz: int,
    expected_unit: bytes,
) -> tuple[bool, int | None]:
    """Read back the time/unit characteristics to confirm a write landed even
    though its Write-Response was lost.

    Opens its OWN fresh connection (never reuses the doomed link from the
    failed write attempt). Never raises: any failure here — connection or
    read — just means "could not confirm", so the caller's normal
    sleep-and-retry proceeds. The optional clock-mode payload shares the
    TIME characteristic with the time payload and cannot be distinguished
    from it on read-back, so it is assumed delivered alongside the time
    write whenever the time read-back matches. When the read-back confirms a
    match, also piggybacks a best-effort battery read on the same connection.
    """
    try:
        client = await establish_connection(
            BleakClientWithServiceCache, ble_device, name=mac, max_attempts=3
        )
    except Exception as exc:
        _LOGGER.debug("Read-back connection failed for %s: %s", mac, exc)
        return False, None

    try:
        time_value = await client.read_gatt_char(UUID_TIME)
        unit_value = await client.read_gatt_char(UUID_UNIT)
        if len(time_value) < 5:
            return False, None
        ts, tz = struct.unpack("<Ib", time_value[:5])
        matched = (
            abs(ts - expected_timestamp) <= VERIFY_TOLERANCE_SECONDS
            and tz == expected_tz
            and unit_value[:1] == expected_unit
        )
        battery: int | None = None
        if matched:
            try:
                battery = _parse_battery(
                    await client.read_gatt_char(UUID_BATTERY)
                )
            except Exception as exc:  # noqa: BLE001 — best-effort read
                _LOGGER.debug("Battery read failed for %s: %s", mac, exc)
        return matched, battery
    except Exception as exc:
        _LOGGER.debug("Read-back failed for %s: %s", mac, exc)
        return False, None
    finally:
        try:
            await client.disconnect()
        except Exception as exc:  # noqa: BLE001 — must not mask the read result
            _LOGGER.debug("Read-back disconnect failed for %s: %s", mac, exc)


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
) -> int | None:
    """Write time, temperature unit and (optionally) clock mode to the device.

    Uses Home Assistant's Bluetooth stack exclusively: works with the host's
    own adapter and with ESPHome BLE proxies.

    The device intermittently drops the BLE link right after connect, so the
    write is retried up to WRITE_ATTEMPTS times, each on a FRESH connection
    (a new `establish_connection` call) — a single dead link is never reused.

    Returns the battery level (percent) when it could be read, else None.

    Raises DeviceNotFoundError if no connectable advertisement is seen within
    `timeout`, DeviceCommunicationError if every write attempt fails.
    """
    ble_device = await _resolve_ble_device(hass, mac, timeout)
    if ble_device is None:
        raise DeviceNotFoundError(
            f"No advertisement from {mac} within {timeout:.0f}s. Press any "
            "button on the clock to wake it, and make sure it is in range of "
            "the Home Assistant host's Bluetooth adapter or an ESPHome "
            "Bluetooth proxy."
        )

    last_exc: Exception | None = None
    for attempt in range(1, WRITE_ATTEMPTS + 1):
        # Capture the timestamp fresh on every attempt, immediately before
        # the write — not before the advertisement wait above, which can
        # block up to `timeout` and would otherwise leave the clock set that
        # many seconds slow. Explicit caller-provided values stay fixed
        # across attempts.
        attempt_timestamp_utc = timestamp_utc
        attempt_tz_offset_hours = tz_offset_hours
        if attempt_timestamp_utc is None or attempt_tz_offset_hours is None:
            ts_now, tz_now = _current_time_and_offset()
            if attempt_timestamp_utc is None:
                attempt_timestamp_utc = ts_now
            if attempt_tz_offset_hours is None:
                attempt_tz_offset_hours = tz_now

        payloads = (
            _build_time_payload(attempt_timestamp_utc, attempt_tz_offset_hours),
            _build_unit_payload(temp_unit),
            _build_mode_payload(clock_mode) if write_clock_mode else None,
        )

        try:
            battery = await _write_payloads(ble_device, mac, payloads)
            _LOGGER.debug("Wrote time/unit/mode to %s via HA Bluetooth", mac)
            return battery
        except DeviceCommunicationError as exc:
            last_exc = exc
            _LOGGER.debug(
                "GATT write attempt %d/%d failed for %s: %s",
                attempt,
                WRITE_ATTEMPTS,
                mac,
                exc,
            )
            # A dropped link can eat the Write-Response even though the
            # device applied the write, so a raised DeviceCommunicationError
            # is not proof of failure — read back before giving up on this
            # attempt. (The optional clock-mode payload cannot be read back
            # on its own; a matching time read-back is treated as evidence
            # it landed too, since both share the TIME characteristic.)
            # A DeviceConnectionError means establish_connection itself never
            # succeeded, so no write reached the device — read-back would
            # only waste a connection attempt and delay the retry.
            if not isinstance(exc, DeviceConnectionError):
                unit_payload = payloads[1]
                matched, battery = await _read_back_matches(
                    ble_device,
                    mac,
                    attempt_timestamp_utc,
                    attempt_tz_offset_hours,
                    unit_payload,
                )
                if matched:
                    _LOGGER.info(
                        "write response lost but read-back confirms the "
                        "device applied it"
                    )
                    return battery
            if attempt < WRITE_ATTEMPTS:
                await asyncio.sleep(WRITE_RETRY_DELAY_SECONDS)

    raise DeviceCommunicationError(
        f"GATT write failed after {WRITE_ATTEMPTS} attempts"
    ) from last_exc
