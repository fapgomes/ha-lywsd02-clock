# Battery Sensor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the LYWSD02's battery level (%) as a diagnostic sensor, read during the sync connection.

**Architecture:** `_write_payloads` gains a best-effort battery read on the connection it already opens and returns `int | None`; `set_time` propagates it; the coordinator stores it (never blanking on a failed read); a new diagnostic `BatterySensor` exposes it.

**Tech Stack:** existing stack (bleak-retry-connector, pytest-homeassistant-custom-component; venv at `.venv/`).

**Spec:** `docs/superpowers/specs/2026-08-03-battery-sensor-design.md`

## Global Constraints

- Battery characteristic UUID: exactly `EBE0CCC4-7A0A-4B0C-8A1A-6FF2997DA3A6`.
- A battery-read failure must NEVER fail a sync — best-effort only, valid range 0–100, anything else → `None`.
- A `None` battery result leaves `coordinator.battery_level` unchanged.
- Public exceptions and `set_time`'s keyword signature unchanged (only the return type changes, additively, to `int | None`).
- Use only `.venv/bin/pytest` to run tests. `git pull --ff-only` before commits (skip if the branch has no upstream). Never push.
- Release `0.16.0` in a dedicated final commit (CHANGELOG + manifest version together).

---

### Task 1: Battery read in the device layer

**Files:**
- Modify: `custom_components/lywsd02_clock/const.py` (add UUID)
- Modify: `custom_components/lywsd02_clock/device.py`
- Test: `tests/test_device.py`

**Interfaces:**
- Consumes: existing `_write_payloads`, `_read_back_matches`, `set_time`.
- Produces: `set_time(...) -> int | None` (battery percent or None); `_write_payloads(...) -> int | None`; `_read_back_matches(...) -> tuple[bool, int | None]`; `_parse_battery(value) -> int | None`. Task 2 relies on `set_time`'s return value.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_device.py` (imports of `AsyncMock`, `MagicMock`, `patch`, `pytest`, `struct`, `set_time`, `DEVICE_NS` already exist):

```python
async def test_battery_returned_on_success(hass):
    client = AsyncMock()
    client.read_gatt_char.return_value = b"\x5a"  # 90 %
    with patch(
        f"{DEVICE_NS}._resolve_ble_device", new=AsyncMock(return_value=MagicMock())
    ), patch(
        f"{DEVICE_NS}.establish_connection", new=AsyncMock(return_value=client)
    ):
        result = await set_time(
            hass, MAC, timestamp_utc=1700000000, tz_offset_hours=0
        )
    assert result == 90
    client.read_gatt_char.assert_awaited_once()


async def test_battery_read_failure_does_not_fail_sync(hass):
    client = AsyncMock()
    client.read_gatt_char.side_effect = RuntimeError("battery read boom")
    with patch(
        f"{DEVICE_NS}._resolve_ble_device", new=AsyncMock(return_value=MagicMock())
    ), patch(
        f"{DEVICE_NS}.establish_connection", new=AsyncMock(return_value=client)
    ):
        result = await set_time(
            hass, MAC, timestamp_utc=1700000000, tz_offset_hours=0
        )
    assert result is None  # sync succeeded, battery unknown
    assert client.write_gatt_char.await_count == 2  # writes unaffected


async def test_battery_out_of_range_returns_none(hass):
    client = AsyncMock()
    client.read_gatt_char.return_value = b"\xff"  # 255 — invalid percent
    with patch(
        f"{DEVICE_NS}._resolve_ble_device", new=AsyncMock(return_value=MagicMock())
    ), patch(
        f"{DEVICE_NS}.establish_connection", new=AsyncMock(return_value=client)
    ):
        result = await set_time(
            hass, MAC, timestamp_utc=1700000000, tz_offset_hours=0
        )
    assert result is None
```

Also UPDATE `test_lost_ack_confirmed_by_read_back`: the verify client now performs a third read (battery) after time+unit match. Give its `read_gatt_char` a three-item `side_effect` — `[struct.pack("<Ib", 1700000005, 0), b"\xff", b"\x5a"]` — and assert the `set_time` call returns `90`.

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/test_device.py -v`
Expected: the three new tests FAIL (`set_time` currently returns `None` always — `assert result == 90` fails; the failure-path tests may pass trivially, that is fine as long as `test_battery_returned_on_success` and the updated read-back test fail).

- [ ] **Step 3: Implement**

`custom_components/lywsd02_clock/const.py` — after `UUID_UNIT`:
```python
UUID_BATTERY: Final = "EBE0CCC4-7A0A-4B0C-8A1A-6FF2997DA3A6"
```

`custom_components/lywsd02_clock/device.py`:

1. Import `UUID_BATTERY` from `.const`; add `Any` to the `typing` import.
2. Add after `_build_mode_payload`:
```python
def _parse_battery(value: Any) -> int | None:
    """Parse the battery characteristic value (1 byte, percent)."""
    try:
        level = int(value[0])
    except Exception:  # noqa: BLE001 — malformed/absent value is a soft failure
        return None
    return level if 0 <= level <= 100 else None
```
3. `_write_payloads` — return type `int | None`; restructure the write block as try/except/else/finally so the battery read runs only after the writes succeeded and its failure cannot raise:
```python
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
```
4. `_read_back_matches` — return type `tuple[bool, int | None]`; every early `return False` becomes `return False, None`; the final comparison becomes:
```python
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
```
Update its docstring to mention the piggybacked battery read.
5. `set_time` — return type `int | None`; docstring gains "Returns the battery level (percent) when it could be read, else None."; the two success paths become:
```python
            battery = await _write_payloads(ble_device, mac, payloads)
            _LOGGER.debug("Wrote time/unit/mode to %s via HA Bluetooth", mac)
            return battery
```
and, in the read-back branch:
```python
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
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: 29 passed (26 existing — of which the read-back test was updated — plus 3 new). If any pre-existing test broke, fix the code, not the pinned expectations.

- [ ] **Step 5: Commit**

```bash
git pull --ff-only
git add custom_components/lywsd02_clock/const.py custom_components/lywsd02_clock/device.py tests/test_device.py
git commit -m "feat: read battery level during the sync connection"
```

---

### Task 2: Coordinator state + battery sensor entity

**Files:**
- Modify: `custom_components/lywsd02_clock/coordinator.py`
- Modify: `custom_components/lywsd02_clock/__init__.py`
- Modify: `custom_components/lywsd02_clock/sensor.py`
- Modify: `custom_components/lywsd02_clock/strings.json`
- Modify: `custom_components/lywsd02_clock/translations/en.json`
- Modify: `README.md` (entities list, if it enumerates sensors)
- Test: `tests/test_coordinator.py` (new)

**Interfaces:**
- Consumes: `set_time(...) -> int | None` from Task 1.
- Produces: `coordinator.battery_level: int | None`; `sensor.<name>_battery` diagnostic entity.

- [ ] **Step 1: Write the failing tests**

`tests/test_coordinator.py`:
```python
"""Coordinator battery-state tests."""
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.lywsd02_clock.coordinator import LYWSD02Coordinator

MAC = "e7:2e:01:42:60:ff"
COORD_NS = "custom_components.lywsd02_clock.coordinator"


def _make_entry():
    entry = MagicMock()
    entry.options = {}
    entry.data = {}
    return entry


async def test_battery_level_stored_on_successful_sync(hass):
    coord = LYWSD02Coordinator(hass, _make_entry(), MAC)
    with patch(f"{COORD_NS}.set_time", new=AsyncMock(return_value=88)):
        assert await coord.async_sync() is True
    assert coord.battery_level == 88


async def test_battery_level_kept_when_read_returns_none(hass):
    coord = LYWSD02Coordinator(hass, _make_entry(), MAC)
    coord.battery_level = 77
    with patch(f"{COORD_NS}.set_time", new=AsyncMock(return_value=None)):
        assert await coord.async_sync() is True
    assert coord.battery_level == 77


async def test_battery_level_untouched_on_failed_sync(hass):
    from custom_components.lywsd02_clock.device import DeviceCommunicationError

    coord = LYWSD02Coordinator(hass, _make_entry(), MAC)
    coord.battery_level = 55
    with patch(
        f"{COORD_NS}.set_time",
        new=AsyncMock(side_effect=DeviceCommunicationError("boom")),
    ):
        assert await coord.async_sync() is False
    assert coord.battery_level == 55
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_coordinator.py -v`
Expected: FAIL — `LYWSD02Coordinator` has no attribute `battery_level`.

- [ ] **Step 3: Implement**

`coordinator.py`:
1. In `__init__`, after `self.last_utcoffset: Any = None`:
```python
        self.battery_level: int | None = None
```
2. In `async_sync`, capture the return and store it — change:
```python
                await set_time(
```
to:
```python
                battery = await set_time(
```
and, in the success tail (right before `self.async_update_listeners()`):
```python
            if battery is not None:
                self.battery_level = battery
```

`__init__.py` — in `_handle_set_time`, change `await set_time(` to `battery = await set_time(`, and in the `if coordinator is not None:` block add (before `coordinator.async_update_listeners()`):
```python
            if battery is not None:
                coordinator.battery_level = battery
```

`sensor.py`:
1. Extend imports:
```python
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory
```
2. Register the new entity in `async_setup_entry`'s list: `BatterySensor(coordinator),`
3. Add the class:
```python
class BatterySensor(LYWSD02Entity, SensorEntity):
    _attr_translation_key = "battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: LYWSD02Coordinator) -> None:
        super().__init__(coordinator, "battery")

    @property
    def native_value(self) -> int | None:
        return self.coordinator.battery_level
```

`strings.json` and `translations/en.json` — inside `entity.sensor`, add (keeping key order alphabetical-insertion consistent with the existing style):
```json
"battery": {"name": "Battery"}
```

`README.md` — if it lists the integration's entities, add a line for the Battery diagnostic sensor (updated at each successful sync; requires a connection, which is why `xiaomi_ble` cannot provide it passively).

- [ ] **Step 4: Full suite + JSON validity**

Run: `.venv/bin/pytest -q` — expected: 32 passed.
Run: `.venv/bin/python -c "import json; [json.load(open(p)) for p in ('custom_components/lywsd02_clock/strings.json','custom_components/lywsd02_clock/translations/en.json')]; print('JSON OK')"`

- [ ] **Step 5: Commit**

```bash
git pull --ff-only
git add custom_components/lywsd02_clock tests/test_coordinator.py README.md
git commit -m "feat: battery diagnostic sensor fed by the sync connection"
```

---

### Task 3: Live verification on the maintainer's HAOS instance

**Files:** none (deployment; coordinate restarts with the user — durable restart authorization was granted for the previous session's verification, ask again if in doubt).

- [ ] **Step 1: Deploy** — `scp` the changed component files (including `translations/en.json`) to `ha:/config/custom_components/lywsd02_clock/`, verify md5sums match.
- [ ] **Step 2: Restart core**, wait for the API, re-enable debug logging for `custom_components.lywsd02_clock`.
- [ ] **Step 3: Trigger the service** `lywsd02_clock.set_time` for `e7:2e:01:42:60:ff` via the supervisor API; confirm HTTP 200.
- [ ] **Step 4: Check the sensor** — `sensor.<name>_battery` (find the exact entity_id via the states API) must show an integer 0–100; the log must show no battery-related errors. A `None`/unknown value with a successful sync is a soft failure: read the debug log for "Battery read failed" and investigate before proceeding.

---

### Task 4: Release v0.16.0

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `custom_components/lywsd02_clock/manifest.json`

- [ ] **Step 1: Changelog entry** — insert after the header block, before `## [0.15.0]`:
```markdown
## [0.16.0] - 2026-08-03

### Added
- **Battery diagnostic sensor** (`sensor.<name>_battery`). The battery
  percentage is read from the clock (GATT characteristic `EBE0CCC4`) on the
  same connection each sync already opens — no extra BLE traffic. It
  refreshes at the sync cadence (and on *Sync now*); a failed battery read
  never fails the sync. This is the value `xiaomi_ble` cannot provide
  passively, since the classic LYWSD02 does not broadcast battery in its
  advertisements.
```
- [ ] **Step 2: Manifest** — `"version": "0.15.0"` → `"version": "0.16.0"`.
- [ ] **Step 3: Full suite** — `.venv/bin/pytest -q` green (32).
- [ ] **Step 4: Dedicated commit**
```bash
git pull --ff-only
git add CHANGELOG.md custom_components/lywsd02_clock/manifest.json
git commit -m "release: v0.16.0"
```
Never push or tag without an explicit user instruction.
