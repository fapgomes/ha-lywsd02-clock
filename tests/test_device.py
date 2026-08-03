"""Regression tests for the three defects that killed the HA-stack path.

Defect 1: lowercase MAC lookups against habluetooth's uppercase-keyed history.
Defect 2: the advertisement wait existed but was never invoked; and HA's
          async_register_callback fires immediately for known devices, so the
          callback must re-query instead of trusting the first fire.
Defect 3: `async with` on the already-connected client from
          establish_connection triggered a second connect().
"""
import asyncio
import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bleak.exc import BleakError

from custom_components.lywsd02_clock.device import (
    DeviceCommunicationError,
    DeviceNotFoundError,
    _resolve_ble_device,
    set_time,
)

MAC = "e7:2e:01:42:60:ff"
DEVICE_NS = "custom_components.lywsd02_clock.device"


async def test_lookup_uses_uppercase_mac(hass):
    """Defect 1: habluetooth's dict is keyed by uppercase addresses."""
    device = MagicMock()
    with patch(
        f"{DEVICE_NS}.bluetooth.async_ble_device_from_address",
        return_value=device,
    ) as mock_lookup:
        result = await _resolve_ble_device(hass, MAC, 5.0)
    assert result is device
    mock_lookup.assert_called_once_with(hass, "E7:2E:01:42:60:FF", connectable=True)


async def test_wait_requeries_on_immediate_fire(hass):
    """Defect 2: an immediate callback fire with no connectable device must
    NOT resolve the wait; a later fire that re-queries successfully must."""
    device = MagicMock()
    registered = {}

    def fake_register(hass_arg, cb, matcher, mode):
        registered["cb"] = cb
        registered["matcher"] = matcher
        cb(MagicMock(), MagicMock())  # HA fires immediately for known devices
        return MagicMock()

    with patch(
        f"{DEVICE_NS}.bluetooth.async_ble_device_from_address",
        side_effect=[None, None, device],
        # 1st: initial lookup; 2nd: re-query on immediate fire (still None);
        # 3rd: re-query on the real advertisement (device found).
    ), patch(
        f"{DEVICE_NS}.bluetooth.async_register_callback",
        side_effect=fake_register,
    ):
        task = asyncio.create_task(_resolve_ble_device(hass, MAC, 5.0))
        await asyncio.sleep(0.05)  # let the task register and immediate-fire
        assert not task.done(), "immediate fire with no device must not resolve"
        registered["cb"](MagicMock(), MagicMock())  # real advertisement
        result = await asyncio.wait_for(task, timeout=1.0)
    assert result is device
    assert registered["matcher"]["address"] == "E7:2E:01:42:60:FF"


async def test_wait_times_out_to_none(hass):
    with patch(
        f"{DEVICE_NS}.bluetooth.async_ble_device_from_address",
        return_value=None,
    ), patch(
        f"{DEVICE_NS}.bluetooth.async_register_callback",
        return_value=MagicMock(),
    ):
        result = await _resolve_ble_device(hass, MAC, 0.1)
    assert result is None


async def test_set_time_raises_not_found(hass):
    with patch(
        f"{DEVICE_NS}._resolve_ble_device", new=AsyncMock(return_value=None)
    ):
        with pytest.raises(DeviceNotFoundError):
            await set_time(hass, MAC, timeout=0.1)


async def test_write_connects_once_with_response(hass):
    """Defect 3: exactly one connection — establish_connection only — and
    every GATT write is an acknowledged Write-Request."""
    client = AsyncMock()
    with patch(
        f"{DEVICE_NS}._resolve_ble_device", new=AsyncMock(return_value=MagicMock())
    ), patch(
        f"{DEVICE_NS}.establish_connection", new=AsyncMock(return_value=client)
    ):
        await set_time(hass, MAC, timestamp_utc=1700000000, tz_offset_hours=0)

    client.connect.assert_not_awaited()
    client.__aenter__.assert_not_called()
    writes = client.write_gatt_char.await_args_list
    assert len(writes) == 2  # time + unit; no clock-mode by default
    assert writes[0].args[1] == b"\x00\xf1\x53\x65\x00"
    for call in writes:
        assert call.kwargs.get("response") is True
    client.disconnect.assert_awaited_once()


async def test_write_clock_mode_adds_third_write(hass):
    client = AsyncMock()
    with patch(
        f"{DEVICE_NS}._resolve_ble_device", new=AsyncMock(return_value=MagicMock())
    ), patch(
        f"{DEVICE_NS}.establish_connection", new=AsyncMock(return_value=client)
    ):
        await set_time(
            hass, MAC, timestamp_utc=1700000000, tz_offset_hours=0,
            clock_mode=12, write_clock_mode=True,
        )
    writes = client.write_gatt_char.await_args_list
    assert len(writes) == 3
    assert writes[2].args[1] == b"\x00\x00\x00\x00\x00\x00\xaa"
    assert writes[2].kwargs.get("response") is True


async def test_write_failure_raises_and_still_disconnects(hass):
    """A persistently failing device is retried WRITE_ATTEMPTS times, and
    every fresh connection — both the failing write attempts and the
    read-back verification after each one — is disconnected; no link is
    ever left dangling. (The reused client's read_gatt_char has no
    side_effect configured, so it returns a MagicMock that is not `bytes`;
    struct.unpack raises inside _read_back_matches, which is swallowed and
    treated as "could not confirm", so every attempt keeps failing.)"""
    client = AsyncMock()
    client.write_gatt_char.side_effect = RuntimeError("boom")
    with patch(
        f"{DEVICE_NS}.WRITE_RETRY_DELAY_SECONDS", 0
    ), patch(
        f"{DEVICE_NS}._resolve_ble_device", new=AsyncMock(return_value=MagicMock())
    ), patch(
        f"{DEVICE_NS}.establish_connection", new=AsyncMock(return_value=client)
    ) as mock_establish:
        with pytest.raises(DeviceCommunicationError):
            await set_time(hass, MAC, timestamp_utc=1700000000, tz_offset_hours=0)
    assert mock_establish.await_count == 6  # 3 writes + 3 verifies
    assert client.disconnect.await_count == 6


async def test_connect_failure_skips_read_back(hass):
    """A connection failure (establish_connection itself raises) means no
    write ever reached the device, so read-back verification would be
    pointless — set_time must retry WRITE_ATTEMPTS times with no extra
    verification connections in between."""
    with patch(
        f"{DEVICE_NS}.WRITE_RETRY_DELAY_SECONDS", 0
    ), patch(
        f"{DEVICE_NS}._resolve_ble_device", new=AsyncMock(return_value=MagicMock())
    ), patch(
        f"{DEVICE_NS}.establish_connection",
        new=AsyncMock(side_effect=[BleakError("no route"), RuntimeError("boom"), BleakError("no route")]),
    ) as mock_establish:
        with pytest.raises(DeviceCommunicationError):
            await set_time(hass, MAC, timestamp_utc=1700000000, tz_offset_hours=0)
    assert mock_establish.await_count == 3  # only the 3 write attempts, no verify


async def test_write_retries_with_fresh_connection(hass):
    """A dropped link on the first attempt must not be reused — the failed
    write's read-back verification (mismatched here) gets its own
    establish_connection call, then the retry gets another; every client is
    cleanly disconnected."""
    client1 = AsyncMock()
    client1.write_gatt_char.side_effect = RuntimeError("boom")
    verify_client = AsyncMock()
    verify_client.read_gatt_char.side_effect = [
        struct.pack("<Ib", 999, 0),  # far off the expected 1700000000
        b"\xff",
    ]
    client2 = AsyncMock()
    with patch(
        f"{DEVICE_NS}.WRITE_RETRY_DELAY_SECONDS", 0
    ), patch(
        f"{DEVICE_NS}._resolve_ble_device", new=AsyncMock(return_value=MagicMock())
    ), patch(
        f"{DEVICE_NS}.establish_connection",
        new=AsyncMock(side_effect=[client1, verify_client, client2]),
    ) as mock_establish:
        await set_time(hass, MAC, timestamp_utc=1700000000, tz_offset_hours=0)
    assert mock_establish.await_count == 3
    client1.disconnect.assert_awaited_once()
    verify_client.disconnect.assert_awaited_once()
    client2.disconnect.assert_awaited_once()


async def test_write_fails_after_all_attempts(hass):
    """All WRITE_ATTEMPTS write connections fail, and every read-back
    verification also fails to confirm (read_gatt_char raises): a
    DeviceCommunicationError is raised, chained from the last write error,
    after exactly 2 * WRITE_ATTEMPTS establish_connection calls (one write +
    one verify per attempt)."""
    write_clients = [AsyncMock() for _ in range(3)]
    for c in write_clients:
        c.write_gatt_char.side_effect = RuntimeError("boom")
    verify_clients = [AsyncMock() for _ in range(3)]
    for c in verify_clients:
        c.read_gatt_char.side_effect = RuntimeError("read failed")
    connections = [
        client for pair in zip(write_clients, verify_clients) for client in pair
    ]
    with patch(
        f"{DEVICE_NS}.WRITE_RETRY_DELAY_SECONDS", 0
    ), patch(
        f"{DEVICE_NS}._resolve_ble_device", new=AsyncMock(return_value=MagicMock())
    ), patch(
        f"{DEVICE_NS}.establish_connection", new=AsyncMock(side_effect=connections)
    ) as mock_establish:
        with pytest.raises(DeviceCommunicationError):
            await set_time(hass, MAC, timestamp_utc=1700000000, tz_offset_hours=0)
    assert mock_establish.await_count == 6


async def test_retry_recomputes_default_timestamp(hass):
    """When the caller does not pass an explicit timestamp, each retry must
    recompute it fresh — a slow first attempt must not write a stale time on
    the successful retry. A mismatching read-back is interleaved between the
    two write attempts so the loop actually proceeds to the retry."""
    client1 = AsyncMock()
    client1.write_gatt_char.side_effect = RuntimeError("boom")
    verify_client = AsyncMock()
    verify_client.read_gatt_char.side_effect = [
        struct.pack("<Ib", 1000, 0),  # time matches attempt 1's timestamp...
        b"\x01",  # ...but the unit doesn't, so read-back does not confirm
    ]
    client2 = AsyncMock()
    with patch(
        f"{DEVICE_NS}.WRITE_RETRY_DELAY_SECONDS", 0
    ), patch(
        f"{DEVICE_NS}._resolve_ble_device", new=AsyncMock(return_value=MagicMock())
    ), patch(
        f"{DEVICE_NS}.establish_connection",
        new=AsyncMock(side_effect=[client1, verify_client, client2]),
    ), patch(
        f"{DEVICE_NS}._current_time_and_offset",
        side_effect=[(1000, 0), (2000, 0)],
    ):
        await set_time(hass, MAC)
    first_write = client2.write_gatt_char.await_args_list[0]
    assert first_write.args[1] == struct.pack("<Ib", 2000, 0)


async def test_lost_ack_confirmed_by_read_back(hass):
    """Defect: the device can apply a write and still drop the link before
    the Write-Response arrives. When the read-back confirms the value landed
    (within tolerance), set_time must succeed rather than retry/raise."""
    w1 = AsyncMock()
    w1.write_gatt_char.side_effect = RuntimeError("boom")
    v1 = AsyncMock()
    v1.read_gatt_char.side_effect = [
        struct.pack("<Ib", 1700000005, 0),  # within VERIFY_TOLERANCE_SECONDS
        b"\xff",
    ]
    with patch(
        f"{DEVICE_NS}.WRITE_RETRY_DELAY_SECONDS", 0
    ), patch(
        f"{DEVICE_NS}._resolve_ble_device", new=AsyncMock(return_value=MagicMock())
    ), patch(
        f"{DEVICE_NS}.establish_connection",
        new=AsyncMock(side_effect=[w1, v1]),
    ) as mock_establish:
        await set_time(
            hass, MAC, timestamp_utc=1700000000, tz_offset_hours=0, temp_unit="C"
        )
    assert mock_establish.await_count == 2
    w1.disconnect.assert_awaited_once()
    v1.disconnect.assert_awaited_once()


async def test_read_back_mismatch_keeps_retrying(hass):
    """A read-back that does not match must not short-circuit the retry
    loop: with every write AND every verification failing, set_time still
    raises DeviceCommunicationError after WRITE_ATTEMPTS full cycles."""
    write_clients = [AsyncMock() for _ in range(3)]
    for c in write_clients:
        c.write_gatt_char.side_effect = RuntimeError("boom")
    verify_clients = [AsyncMock() for _ in range(3)]
    for c in verify_clients:
        c.read_gatt_char.side_effect = [
            struct.pack("<Ib", 999, 0),  # time far off
            b"\xff",
        ]
    connections = [
        client for pair in zip(write_clients, verify_clients) for client in pair
    ]
    with patch(
        f"{DEVICE_NS}.WRITE_RETRY_DELAY_SECONDS", 0
    ), patch(
        f"{DEVICE_NS}._resolve_ble_device", new=AsyncMock(return_value=MagicMock())
    ), patch(
        f"{DEVICE_NS}.establish_connection", new=AsyncMock(side_effect=connections)
    ) as mock_establish:
        with pytest.raises(DeviceCommunicationError):
            await set_time(hass, MAC, timestamp_utc=1700000000, tz_offset_hours=0)
    assert mock_establish.await_count == 6  # 3 writes + 3 verifies
