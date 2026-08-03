# BLE Stack Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the five-path BLE fallback ladder in `device.py` with a single write path through Home Assistant's Bluetooth stack, validate the service's `mac` parameter, and add a focused test suite — addressing the HA core review (@frenck).

**Architecture:** `set_time()` keeps its public signature and exceptions; internally it resolves a connectable `BLEDevice` via `bluetooth.async_ble_device_from_address` (uppercase MAC), waits for an advertisement when not cached (re-querying from the callback), connects once with `establish_connection`, writes with `response=True`, and disconnects in `finally`. A new `mac.py` module centralizes MAC normalization/validation for the config flow, setup, and the service schema.

**Tech Stack:** Python 3.14, `homeassistant.components.bluetooth`, `bleak-retry-connector`, `pytest-homeassistant-custom-component`.

**Spec:** `docs/superpowers/specs/2026-08-03-ble-stack-rewrite-design.md`

## Global Constraints

- `manifest.json` `requirements` must end as exactly `["bleak-retry-connector>=3.0"]`.
- MAC addresses are stored lowercase in config entries and `unique_id`; uppercase conversion happens ONLY at the `bluetooth.async_ble_device_from_address` / `BluetoothCallbackMatcher` boundary.
- `UUID_TIME` / `UUID_UNIT` in `const.py` stay as-is (uppercase; bleak normalizes specifiers).
- All GATT writes use `response=True` (both characteristics advertise `write` only).
- Never wrap the client returned by `establish_connection` in `async with` — it is already connected.
- Python packages are installed ONLY inside the project venv `.venv/` (never system-wide).
- `git pull --ff-only` before every commit. Never push without an explicit user instruction.
- Release version: `0.15.0`, in a dedicated final commit (CHANGELOG + manifest version together).

---

### Task 1: Test infrastructure + shared `mac.py` module

**Files:**
- Create: `requirements_test.txt`
- Create: `pytest.ini`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `custom_components/lywsd02_clock/mac.py`
- Create: `tests/test_mac.py`
- Modify: `custom_components/lywsd02_clock/config_flow.py:4,47-60` (drop local helpers, import from `mac.py`)
- Modify: `custom_components/lywsd02_clock/__init__.py:50-51` (drop local `_normalize_mac`, import from `mac.py`)

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `normalize_mac(mac: str) -> str` and `is_valid_mac(mac: str) -> bool` in `custom_components/lywsd02_clock/mac.py` — Tasks 3 and 4 import these. Also the working pytest environment every later task runs in.

- [ ] **Step 1: Create the venv and test config files**

`requirements_test.txt`:
```
pytest-homeassistant-custom-component
```

`pytest.ini`:
```ini
[pytest]
testpaths = tests
asyncio_mode = auto
```

`tests/__init__.py`: empty file.

`tests/conftest.py`:
```python
"""Shared fixtures for the lywsd02_clock test suite."""
import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading the custom integration in every test."""
    yield
```

Run:
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
```
Expected: installs cleanly (pulls `homeassistant`, `pytest`, `bleak`, etc.). `.gitignore` already covers `.venv/` — no change needed.

- [ ] **Step 2: Write the failing test for the MAC helpers**

`tests/test_mac.py`:
```python
"""Tests for MAC normalization and validation helpers."""
from custom_components.lywsd02_clock.mac import is_valid_mac, normalize_mac


def test_normalize_lowercases_and_strips():
    assert normalize_mac(" E7:2E:01:42:60:FF ") == "e7:2e:01:42:60:ff"


def test_normalize_is_idempotent():
    assert normalize_mac("e7:2e:01:42:60:ff") == "e7:2e:01:42:60:ff"


def test_valid_macs_accepted_any_case():
    assert is_valid_mac("e7:2e:01:42:60:ff")
    assert is_valid_mac("E7:2E:01:42:60:FF")
    assert is_valid_mac(" AA:BB:CC:DD:EE:0f ")


def test_invalid_macs_rejected():
    assert not is_valid_mac("")
    assert not is_valid_mac("banana")
    assert not is_valid_mac("e7:2e:01:42:60")          # 5 octets
    assert not is_valid_mac("e7:2e:01:42:60:ff:aa")    # 7 octets
    assert not is_valid_mac("e72e014260ff")            # no separators
    assert not is_valid_mac("g7:2e:01:42:60:ff")       # non-hex
```

- [ ] **Step 3: Run it to verify it fails**

Run: `.venv/bin/pytest tests/test_mac.py -v`
Expected: FAIL at collection — `ModuleNotFoundError: No module named 'custom_components.lywsd02_clock.mac'`

- [ ] **Step 4: Create `mac.py`**

`custom_components/lywsd02_clock/mac.py`:
```python
"""MAC address helpers shared by the config flow, setup and service schema."""
from __future__ import annotations

import re

MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


def normalize_mac(mac: str) -> str:
    """Normalize a MAC address to lowercase colon-separated form."""
    return mac.strip().lower()


def is_valid_mac(mac: str) -> bool:
    """Return True if mac is a colon-separated MAC address (any case)."""
    return bool(MAC_RE.match(normalize_mac(mac)))
```

- [ ] **Step 5: Run the tests and make sure they pass**

Run: `.venv/bin/pytest tests/test_mac.py -v`
Expected: 4 PASS

- [ ] **Step 6: Point `config_flow.py` at the shared module**

In `custom_components/lywsd02_clock/config_flow.py`:

1. Delete line 4 (`import re`) — `MAC_RE` was its only use.
2. Delete lines 47–55 (the `MAC_RE`, `_normalize_mac`, `_is_valid_mac` definitions).
3. Add to the relative imports (after the `from .const import (...)` block):
```python
from .mac import is_valid_mac, normalize_mac
```
4. Replace every remaining use: `_normalize_mac(` → `normalize_mac(` (lines 59, 114, 171, 182 in the original numbering) and `_is_valid_mac(` → `is_valid_mac(` (line 179). `_friendly_default` stays in `config_flow.py` (only used there) but now calls `normalize_mac`.

Verify no stragglers: `grep -n "_normalize_mac\|_is_valid_mac\|MAC_RE\|^import re" custom_components/lywsd02_clock/config_flow.py` → no matches.

- [ ] **Step 7: Point `__init__.py` at the shared module**

In `custom_components/lywsd02_clock/__init__.py`:

1. Delete the local helper (lines 50–51):
```python
def _normalize_mac(mac: str) -> str:
    return mac.strip().lower()
```
2. Add import (after the `from .coordinator import ...` line):
```python
from .mac import normalize_mac
```
3. Replace both uses: `_normalize_mac(call.data["mac"])` → `normalize_mac(call.data["mac"])` (line 59) and `_normalize_mac(entry.data[CONF_MAC])` → `normalize_mac(entry.data[CONF_MAC])` (line 124).

- [ ] **Step 8: Run the full suite (checks the refactor didn't break imports)**

Run: `.venv/bin/pytest -v`
Expected: all PASS (test_mac only, so far)

- [ ] **Step 9: Commit**

```bash
git pull --ff-only
git add requirements_test.txt pytest.ini tests/ custom_components/lywsd02_clock/mac.py custom_components/lywsd02_clock/config_flow.py custom_components/lywsd02_clock/__init__.py
git commit -m "refactor: extract shared MAC helpers into mac.py, add test infra"
```

---

### Task 2: Payload characterization tests

**Files:**
- Create: `tests/test_payloads.py`

**Interfaces:**
- Consumes: `_build_time_payload`, `_build_unit_payload`, `_build_mode_payload` from `custom_components.lywsd02_clock.device` (they exist today and survive the Task 3 rewrite unchanged).
- Produces: a byte-exact safety net that must stay green through Task 3.

- [ ] **Step 1: Write the characterization tests**

These pass against the CURRENT code — they pin down the wire format so the Task 3 rewrite cannot silently change it. (Reference: `1700000000 == 0x6553F100`, little-endian `00 F1 53 65`; tz `-3` as signed byte is `0xFD`.)

`tests/test_payloads.py`:
```python
"""Byte-exact characterization tests for the GATT payload builders."""
from custom_components.lywsd02_clock.device import (
    _build_mode_payload,
    _build_time_payload,
    _build_unit_payload,
)


def test_time_payload_positive_offset():
    assert _build_time_payload(1700000000, 1) == b"\x00\xf1\x53\x65\x01"


def test_time_payload_negative_offset():
    assert _build_time_payload(1700000000, -3) == b"\x00\xf1\x53\x65\xfd"


def test_unit_payload_celsius():
    assert _build_unit_payload("C") == b"\xff"


def test_unit_payload_fahrenheit_any_case():
    assert _build_unit_payload("F") == b"\x01"
    assert _build_unit_payload("f") == b"\x01"


def test_mode_payload_12h():
    assert _build_mode_payload(12) == b"\x00\x00\x00\x00\x00\x00\xaa"


def test_mode_payload_24h():
    assert _build_mode_payload(24) == b"\x00\x00\x00\x00\x00\x00\x00"
```

- [ ] **Step 2: Run them — they must pass already**

Run: `.venv/bin/pytest tests/test_payloads.py -v`
Expected: 6 PASS (against the current `device.py` — that is the point of a characterization test)

- [ ] **Step 3: Commit**

```bash
git pull --ff-only
git add tests/test_payloads.py
git commit -m "test: pin payload builders byte-exact before the BLE rewrite"
```

---

### Task 3: Rewrite `device.py` to the HA Bluetooth stack only

**Files:**
- Create: `tests/test_device.py`
- Modify: `custom_components/lywsd02_clock/device.py` (full rewrite, ~1040 → ~190 lines)
- Modify: `custom_components/lywsd02_clock/manifest.json` (drop `pygatt` from `requirements`)

**Interfaces:**
- Consumes: `UUID_TIME`, `UUID_UNIT`, `DEFAULT_TIMEOUT` from `const.py`.
- Produces (unchanged externally, so `coordinator.py`/`button.py` compile untouched):
  - `async set_time(hass: HomeAssistant, mac: str, *, temp_unit: Literal["C","F"] = "C", clock_mode: Literal[12,24] = 24, timestamp_utc: int | None = None, tz_offset_hours: int | None = None, timeout: float = DEFAULT_TIMEOUT, write_clock_mode: bool = False) -> None`
  - `DeviceNotFoundError(Exception)`, `DeviceCommunicationError(Exception)`
  - internals used by tests: `async _resolve_ble_device(hass, mac: str, timeout: float) -> BLEDevice | None`, plus the three payload builders from Task 2.

- [ ] **Step 1: Write the failing regression tests**

`tests/test_device.py`:
```python
"""Regression tests for the three defects that killed the HA-stack path.

Defect 1: lowercase MAC lookups against habluetooth's uppercase-keyed history.
Defect 2: the advertisement wait existed but was never invoked; and HA's
          async_register_callback fires immediately for known devices, so the
          callback must re-query instead of trusting the first fire.
Defect 3: `async with` on the already-connected client from
          establish_connection triggered a second connect().
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
    client = AsyncMock()
    client.write_gatt_char.side_effect = RuntimeError("boom")
    with patch(
        f"{DEVICE_NS}._resolve_ble_device", new=AsyncMock(return_value=MagicMock())
    ), patch(
        f"{DEVICE_NS}.establish_connection", new=AsyncMock(return_value=client)
    ):
        with pytest.raises(DeviceCommunicationError):
            await set_time(hass, MAC, timestamp_utc=1700000000, tz_offset_hours=0)
    client.disconnect.assert_awaited_once()
```

- [ ] **Step 2: Run them to verify they fail against the current code**

Run: `.venv/bin/pytest tests/test_device.py -v`
Expected: FAIL at collection — `ImportError: cannot import name '_resolve_ble_device'` (the function does not exist in the current `device.py`; the old code has `_resolve_ble_device_via_ha`, which is dead code).

- [ ] **Step 3: Rewrite `device.py`**

Replace the ENTIRE contents of `custom_components/lywsd02_clock/device.py` with:

```python
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

    ble_device = await _resolve_ble_device(hass, mac, timeout)
    if ble_device is None:
        raise DeviceNotFoundError(
            f"No advertisement from {mac} within {timeout:.0f}s. Press any "
            "button on the clock to wake it, and make sure it is in range of "
            "the Home Assistant host's Bluetooth adapter or an ESPHome "
            "Bluetooth proxy."
        )
    await _write_payloads(ble_device, mac, payloads)
    _LOGGER.debug("Wrote time/unit/mode to %s via HA Bluetooth", mac)
```

- [ ] **Step 4: Drop `pygatt` from the manifest**

In `custom_components/lywsd02_clock/manifest.json` change:
```json
  "requirements": ["bleak-retry-connector>=3.0", "pygatt>=4.0.5"],
```
to:
```json
  "requirements": ["bleak-retry-connector>=3.0"],
```

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: ALL PASS — test_device (7), test_payloads (6, unchanged — proves the wire format survived), test_mac (4).

- [ ] **Step 6: Grep for leftovers**

Run: `grep -rn "pygatt\|bluetoothctl\|hciconfig\|lywsd02_lib\|bluezdbus\|BleakScannerBlueZDBus\|BleakClientBlueZDBus\|ADVERTISEMENT_WAIT\|DIRECT_CLIENT_TIMEOUT" custom_components/`
Expected: no matches.

- [ ] **Step 7: Commit**

```bash
git pull --ff-only
git add custom_components/lywsd02_clock/device.py custom_components/lywsd02_clock/manifest.json tests/test_device.py
git commit -m "feat!: single BLE write path via HA Bluetooth stack

Fixes the three defects that made the HA path dead code (lowercase MAC
lookups, never-invoked advertisement wait, double connect) and removes
the pygatt/gatttool, bluetoothctl, raw-bluezdbus and lywsd02-library
fallbacks, per HA core review."
```

---

### Task 4: Validate the service's `mac` parameter

**Files:**
- Create: `tests/test_services.py`
- Modify: `custom_components/lywsd02_clock/__init__.py:38-47` (schema) and `:59` (handler)

**Interfaces:**
- Consumes: `normalize_mac`, `is_valid_mac` from Task 1; `set_time` from Task 3.
- Produces: `SET_TIME_SCHEMA` whose `mac` value arrives at the handler already validated and normalized (lowercase).

- [ ] **Step 1: Write the failing tests**

`tests/test_services.py`:
```python
"""Service-schema validation tests for lywsd02_clock.set_time."""
from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol

from homeassistant.setup import async_setup_component

from custom_components.lywsd02_clock.const import DOMAIN, SERVICE_SET_TIME


async def test_invalid_mac_rejected_by_schema(hass):
    assert await async_setup_component(hass, DOMAIN, {})
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, SERVICE_SET_TIME, {"mac": "not-a-mac"}, blocking=True
        )


async def test_valid_mac_normalized_before_set_time(hass):
    assert await async_setup_component(hass, DOMAIN, {})
    with patch(
        "custom_components.lywsd02_clock.set_time", new=AsyncMock()
    ) as mock_set_time:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_TIME,
            {"mac": "E7:2E:01:42:60:FF", "timestamp": 1700000000},
            blocking=True,
        )
    assert mock_set_time.await_count == 1
    assert mock_set_time.await_args.args[1] == "e7:2e:01:42:60:ff"
```

- [ ] **Step 2: Run to verify the first test fails**

Run: `.venv/bin/pytest tests/test_services.py -v`
Expected: `test_invalid_mac_rejected_by_schema` FAILS (current schema is `cv.string` — accepts anything, so no `vol.Invalid` is raised and the call proceeds to a `DeviceNotFoundError`/`HomeAssistantError` instead). `test_valid_mac_normalized_before_set_time` may already pass (the handler normalizes today) — that is fine; the schema test is the regression proof.

- [ ] **Step 3: Add the validator and tighten the schema**

In `custom_components/lywsd02_clock/__init__.py`:

1. Change the `.mac` import (from Task 1) to bring both helpers:
```python
from .mac import is_valid_mac, normalize_mac
```
2. Add the validator right above `SET_TIME_SCHEMA`:
```python
def _validated_mac(value: str) -> str:
    """Validate and normalize a MAC address for the service schema."""
    mac = normalize_mac(cv.string(value))
    if not is_valid_mac(mac):
        raise vol.Invalid(f"invalid MAC address: {value!r}")
    return mac
```
3. In `SET_TIME_SCHEMA`, replace:
```python
        vol.Required("mac"): cv.string,
```
with:
```python
        vol.Required("mac"): _validated_mac,
```
4. In `_handle_set_time`, the value now arrives normalized; replace:
```python
        mac = normalize_mac(call.data["mac"])
```
with:
```python
        mac = call.data["mac"]
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: ALL PASS (19 tests: 4 mac + 6 payloads + 7 device + 2 services).

- [ ] **Step 5: Commit**

```bash
git pull --ff-only
git add custom_components/lywsd02_clock/__init__.py tests/test_services.py
git commit -m "feat: validate the set_time service mac parameter as a MAC address"
```

---

### Task 5: `tests` job in CI

**Files:**
- Modify: `.github/workflows/validate.yml`

**Interfaces:**
- Consumes: `requirements_test.txt` and the suite from Tasks 1–4.
- Produces: CI gate for every push/PR.

- [ ] **Step 1: Add the job**

Append to `.github/workflows/validate.yml` (same indentation as the existing `hassfest`/`hacs` jobs):
```yaml
  tests:
    name: Tests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.14"
      - run: pip install -r requirements_test.txt
      - run: pytest -q
```

- [ ] **Step 2: Sanity-check the YAML**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/validate.yml')); print('YAML OK')"`
Expected: `YAML OK` (if PyYAML is missing on the system Python, use `.venv/bin/python` — the venv has it via the HA dependency tree).

- [ ] **Step 3: Commit**

```bash
git pull --ff-only
git add .github/workflows/validate.yml
git commit -m "ci: run the test suite in the validation workflow"
```

---

### Task 6: Live verification on the maintainer's HAOS instance

**Files:** none (deployment of the working tree to `/config/custom_components/lywsd02_clock/` on host `ha`).

**Interfaces:**
- Consumes: the completed integration from Tasks 1–4.
- Produces: the spec's verification evidence — the log line `Wrote time/unit/mode to … via HA Bluetooth`.

This task requires the user (core restart + pressing *Sync now*): coordinate each step.

- [ ] **Step 1: Deploy the rewritten integration**

```bash
ssh ha 'cp -a /config/custom_components/lywsd02_clock /config/lywsd02_clock.bak-rewrite'
scp custom_components/lywsd02_clock/*.py ha:/config/custom_components/lywsd02_clock/
scp custom_components/lywsd02_clock/manifest.json ha:/config/custom_components/lywsd02_clock/
ssh ha 'rm -f /config/custom_components/lywsd02_clock/device.py.bak-spike'
```

- [ ] **Step 2: Restart core (ask the user first) and re-enable debug logging**

```bash
ssh ha 'ha core restart' &
# poll until up, then:
ssh ha 'curl -s -X POST -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"custom_components.lywsd02_clock\":\"debug\"}" \
  http://supervisor/core/api/services/logger/set_level'
```

- [ ] **Step 3: User presses *Sync now*; read the log**

```bash
ssh ha 'grep -i "lywsd02_clock" /config/home-assistant.log | tail -20'
```
Expected: `Wrote time/unit/mode to e7:2e:01:42:60:ff via HA Bluetooth` and NO pygatt/bluetoothctl lines. `sensor.lywsd02_escritorio` state `success`.

- [ ] **Step 4: On success, remove the deploy backup**

```bash
ssh ha 'rm -rf /config/lywsd02_clock.bak-rewrite'
```
(On failure: restore the backup, collect the debug log, and return to the plan.)

---

### Task 7: Release v0.15.0

**Files:**
- Modify: `CHANGELOG.md` (new entry at the top, after line 6)
- Modify: `custom_components/lywsd02_clock/manifest.json` (`"version": "0.15.0"`)

**Interfaces:**
- Consumes: verified integration from Task 6.
- Produces: the release the HA core re-review will be requested against.

- [ ] **Step 1: Add the changelog entry**

Insert after the header block (line 6), before `## [0.14.2]`, following the Keep a Changelog style already in the file:

```markdown
## [0.15.0] - 2026-08-03

### Changed
- **Bluetooth handling rewritten to use Home Assistant's Bluetooth APIs
  exclusively** (`homeassistant.components.bluetooth` +
  `bleak-retry-connector`), per Home Assistant core review. Works with
  local adapters and ESPHome BLE proxies. Three defects had made the
  HA-stack path dead code: lowercase MAC lookups against habluetooth's
  uppercase-keyed history, an advertisement wait that was never invoked,
  and a double `connect()` via `async with` on the already-connected
  client returned by `establish_connection`.

### Added
- The `mac` parameter of the `set_time` service is validated as a MAC
  address.
- Test suite (`pytest-homeassistant-custom-component`): MAC helpers,
  byte-exact payload builders, device resolution and write sequence,
  service-schema validation. New `tests` job in the validation workflow.

### Removed
- pygatt/gatttool path (incl. the `hciconfig` adapter reset and the sudo
  monkeypatch), `bluetoothctl` subprocess paths, raw bluezdbus backend
  path, and the never-installed `lywsd02`/bluepy path. `pygatt` dropped
  from `requirements`.
```

- [ ] **Step 2: Bump the manifest version**

In `custom_components/lywsd02_clock/manifest.json`: `"version": "0.14.2"` → `"version": "0.15.0"`.

- [ ] **Step 3: Full suite one last time**

Run: `.venv/bin/pytest -q`
Expected: all PASS.

- [ ] **Step 4: Dedicated release commit**

```bash
git pull --ff-only
git add CHANGELOG.md custom_components/lywsd02_clock/manifest.json
git commit -m "release: v0.15.0"
```

Do NOT push or tag without an explicit user instruction. After the user pushes/releases, they re-request the HA core review.
