# ha-lywsd02-clock — Design

**Date:** 2026-04-19
**Status:** Approved (ready for implementation planning)

## Overview

Home Assistant custom integration that keeps one or more Xiaomi LYWSD02 e-Ink clocks in sync with Home Assistant's local time via Bluetooth (directly or through ESPHome BLE proxies). Replaces the service-only `home-assistant-lywsd02` plugin with a full integration that provides config-flow setup, per-device entities, automatic scheduled sync, and automatic DST handling.

## Goals

- Zero-config sync: user adds the device and the clock stays correct without writing any automation.
- Multi-device: each LYWSD02 is a separate config entry with independent settings.
- UI-driven: discovery + setup + reconfiguration via Home Assistant UI. No YAML required.
- Battery-aware: default sync cadence is low-frequency; UI and docs steer the user away from sub-daily sync.
- Backwards compatible with the old plugin's service (`lywsd02_clock.set_time`) for advanced / scripted use.

## Non-goals

- Reading temperature / humidity from the LYWSD02. That is handled by separate, well-established integrations (e.g., `xiaomi_ble`). This integration is about writing time/unit/clock-mode, not reading sensor values.
- Sub-daily automatic sync. Users who need it can disable `auto_sync` and create their own automation.
- Sync-time customization (hour, weekday, day-of-month). Fixed defaults only; customization happens via the service.

## Repository layout

```
ha-lywsd02-clock/
├── custom_components/
│   └── lywsd02_clock/
│       ├── __init__.py          # setup, entry (un)load, shared registry
│       ├── manifest.json        # deps: bleak-retry-connector, bluetooth
│       ├── config_flow.py       # user / bluetooth / reconfigure flow
│       ├── const.py             # DOMAIN, keys, defaults
│       ├── coordinator.py       # LYWSD02Coordinator: schedule + sync driver
│       ├── device.py            # protocol layer: connect + GATT writes
│       ├── button.py            # button.sync_now
│       ├── switch.py            # switch.auto_sync
│       ├── sensor.py            # last_sync, next_sync, last_sync_status
│       ├── services.yaml        # lywsd02_clock.set_time (backwards compat)
│       └── strings.json         # i18n strings
├── tests/
│   ├── conftest.py              # HA test fixtures
│   ├── test_config_flow.py
│   ├── test_coordinator.py      # scheduler logic with freeze_time
│   ├── test_device.py           # BLE protocol with mocked Bleak
│   └── test_entities.py
├── hacs.json
├── info.md
├── README.md
└── LICENSE
```

**Domain:** `lywsd02_clock` (avoids collision with the existing `lywsd02` plugin if both are installed side by side).

**External dependencies** (in `manifest.json:requirements`):
- `bleak-retry-connector>=3.0` — reliable BLE connection establishment and retries.

## Architecture

One `LYWSD02Coordinator` instance per config entry. The coordinator owns:
- The schedule (two `async_track_time_change` callbacks),
- Runtime state (`last_sync`, `last_attempt`, `last_status`, `last_error`, `last_utcoffset`),
- The `async_sync` entry point shared by all triggers.

BLE protocol is isolated in `device.py` as a pure async function `set_time(...)` that encapsulates connection, payload encoding, and GATT writes.

Entities (`button`, `switch`, three `sensor`) are thin `CoordinatorEntity` subclasses that read from the coordinator's state.

## Config flow

Three entry points:

### 1. Bluetooth discovery (automatic)

`manifest.json` declares a matcher:

```json
"bluetooth": [
  {"local_name": "LYWSD02"}
]
```

When Home Assistant (or an ESPHome BLE proxy) sees an advertisement from an LYWSD02, it invokes `config_flow.async_step_bluetooth(BluetoothServiceInfoBleak)`. The flow shows a "Discovered" card and asks for:

- **Friendly name** — default `LYWSD02 <last 4 hex of MAC>` (e.g., `LYWSD02 60FF`).
- **Frequency** — select `{daily, weekly, monthly}`, default `daily`.
- **Temperature unit** — select `{C, F}`, default `C`.
- **Clock mode** — select `{12h, 24h}`, default `24h`.

### 2. Manual add (`async_step_user`)

Under "+ Add Integration" → "LYWSD02 Clock". The flow shows a dropdown populated with all recently-seen unconfigured BLE devices matching the LYWSD02 matcher; if the user's clock isn't in the list, a free-text field accepts a raw MAC. Then proceeds to the same configuration form above.

### 3. Options flow (reconfiguration)

*Devices & Services → LYWSD02 Clock → Configure* reopens the same form. Saving updates `config_entry.options` and the coordinator re-schedules/applies changes on the next sync.

**`unique_id`** for the config entry: MAC normalized to lowercase with colons. Home Assistant rejects duplicate entries automatically.

**No connection test at submit time.** If the device is temporarily unreachable, the user shouldn't be blocked from adding it; the `last_sync_status` sensor surfaces any real issues.

## Entities

Five entities per config entry, grouped under a single HA device (identifiers = MAC, manufacturer = "Xiaomi", model = "LYWSD02").

| Platform | `unique_id` suffix | Name | Behavior |
|---|---|---|---|
| `button` | `sync_now` | "Sync Now" | Triggers an immediate sync, ignoring both the schedule and `auto_sync`. Goes through the coordinator's `async_sync`. |
| `switch` | `auto_sync` | "Auto Sync" | Enables/disables the automatic schedule. Persisted in `config_entry.options`. Default: `on`. Does not affect manual sync or the service. |
| `sensor` | `last_sync` | "Last Sync" | `device_class: timestamp`. Datetime of the last successful sync (manual or auto). `None` until the first success. |
| `sensor` | `next_sync` | "Next Sync" | `device_class: timestamp`. Datetime of the next scheduled sync, computed on-demand. `None` when `auto_sync=off`. |
| `sensor` | `last_sync_status` | "Last Sync Status" | `device_class: enum`, states `{success, failed, never}`. Attributes: `error_message` (string), `attempted_at` (datetime). `attempted_at` is updated for both success and failure. |

Entity `unique_id` format: `{mac_lowercase}_{suffix}` (e.g., `aa:bb:cc:dd:ee:ff_sync_now`).

State is not persisted explicitly; `RestoreEntity` handles state restoration across HA restarts.

## Scheduler

Registered in `async_setup_entry`:

```python
async_track_time_change(hass, _on_schedule_tick, hour=3, minute=30, second=0)
async_track_time_change(hass, _on_dst_check,     hour=3, minute=35, second=0)
```

### Tick logic

```python
async def _on_schedule_tick(now: datetime) -> None:
    if not self.auto_sync_enabled:
        return
    if not _is_sync_day(now, self.frequency):
        return
    await self.async_sync()
```

`_is_sync_day` (pure, testable):
- `daily` → `True`
- `weekly` → `now.weekday() == 6` (Sunday)
- `monthly` → `now.day == 1`

### DST check

```python
async def _on_dst_check(now: datetime) -> None:
    current_offset = dt_util.now().utcoffset()
    if (
        self.auto_sync_enabled
        and self.last_utcoffset is not None
        and current_offset != self.last_utcoffset
    ):
        _LOGGER.info("DST transition detected — forcing sync")
        await self.async_sync()
    self.last_utcoffset = current_offset
```

This covers DST transitions regardless of the chosen frequency. `last_utcoffset` is refreshed on every check (and on every successful sync) so it tracks the true current offset even while `auto_sync` is off — no spurious catch-up sync when the user re-enables `auto_sync` later.

The DST check respects `auto_sync_enabled`: turning off auto sync disables *all* automatic triggers, including DST. A user who disables auto sync and builds a custom automation is responsible for whatever DST handling their automation needs.

### `next_sync` computation

Pure function, called when the sensor is read:

```python
def _compute_next_sync(now: datetime, frequency: str) -> datetime:
    candidate = now.replace(hour=3, minute=30, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    while not _is_sync_day(candidate, frequency):
        candidate += timedelta(days=1)
    return candidate
```

Returns `None` when `auto_sync` is off.

### `async_sync` (single code path)

Invoked from: schedule tick, DST check, `button.sync_now`, service.

1. `last_attempt = dt_util.utcnow()`
2. Call `device.set_time(...)` with per-entry `temp_unit` and `clock_mode`.
3. On success: `last_sync = utcnow`, `last_status = "success"`, `last_error = None`, `last_utcoffset = dt_util.now().utcoffset()`.
4. On failure: `last_status = "failed"`, `last_error = str(exc)`. No additional retries — `bleak_retry_connector` already retries internally.
5. `coordinator.async_update_listeners()` to push new state to entities.

## BLE protocol layer (`device.py`)

### Public contract

```python
async def set_time(
    hass: HomeAssistant,
    mac: str,
    *,
    temp_unit: Literal["C", "F"],
    clock_mode: Literal[12, 24],
    timestamp_utc: int | None = None,    # default: dt_util.utcnow().timestamp()
    tz_offset_hours: int | None = None,  # default: dt_util.now().utcoffset() hours
    timeout: float = 60.0,
) -> None:
    """Writes time, temperature unit, and clock mode to the device.

    When `timestamp_utc` / `tz_offset_hours` are None (normal case), they are
    derived from the current Home Assistant time. Explicit values are an escape
    hatch for the backwards-compat service.

    Raises:
        DeviceNotFoundError: if the BLE stack doesn't know the MAC.
        DeviceCommunicationError: on any connect or GATT write failure.
    """
```

### Protocol constants

```python
UUID_TIME = "EBE0CCB7-7A0A-4B0C-8A1A-6FF2997DA3A6"
UUID_UNIT = "EBE0CCBE-7A0A-4B0C-8A1A-6FF2997DA3A6"
```

### Payloads

- **Time:** `struct.pack("<Ib", timestamp_utc, tz_offset_hours)` → `UUID_TIME`
- **Temperature unit:** `struct.pack("B", 0x01 if F else 0xFF)` → `UUID_UNIT`
- **Clock mode:** `struct.pack("<IHB", 0, 0, 0xAA if 12 else 0x00)` → `UUID_TIME`

### Correct time / tz_offset calculation

**Fixes the `get_localized_timestamp` bug from the old plugin** (the one that uses `(utc-local).seconds` and breaks for positive UTC offsets):

```python
local_now = dt_util.now()  # timezone-aware
timestamp_utc = int(local_now.timestamp())
tz_offset_hours = int(local_now.utcoffset().total_seconds() / 3600)
```

Works correctly in any timezone and across DST transitions.

### Connection

```python
from bleak_retry_connector import establish_connection, BleakClientWithServiceCache

ble_device = bluetooth.async_ble_device_from_address(hass, mac, connectable=True)
if ble_device is None:
    raise DeviceNotFoundError(mac)

async with await establish_connection(
    BleakClientWithServiceCache,
    ble_device,
    name=mac,
    max_attempts=3,
) as client:
    await client.write_gatt_char(UUID_TIME, time_payload)
    await client.write_gatt_char(UUID_UNIT, unit_payload)
    await client.write_gatt_char(UUID_TIME, mode_payload)
```

`establish_connection` handles backoff, client lifetime, and eliminates the `habluetooth` warning about raw `BleakClient`.

### Error handling

A single `DeviceCommunicationError` wraps any BLE-layer failure. The coordinator catches it and records the message in `last_error`. No per-call retry beyond what `establish_connection` already does.

Default timeout: 60 seconds. Not exposed via UI; advanced users override via the service.

## Service `lywsd02_clock.set_time` (advanced / backwards compat)

```yaml
service: lywsd02_clock.set_time
data:
  mac: E7:2E:01:42:60:FF
  timestamp: 1745078400    # optional — default: HA's current UTC time
  tz_offset: 1             # optional — default: HA's utcoffset
  temp_mode: C             # optional
  clock_mode: 24           # optional
  timeout: 60              # optional
```

The service is independent of any config entry — accepts any MAC. Used for scripted/automation flows when the user wants a custom schedule or wants to sync a device that isn't configured as an integration entry.

Parameter resolution:
- `mac` — required.
- `timestamp` / `tz_offset` — if provided, passed verbatim to `device.set_time(...)`; otherwise HA's current time is used.
- `temp_mode` / `clock_mode` — if provided, used for this call only. If omitted and the MAC matches a configured entry, fall back to that entry's saved values. If omitted and the MAC is unknown, use the defaults (`C`, `24`).
- `timeout` — if provided, overrides the 60 s default.

When the service is called against a MAC that matches a configured entry, the coordinator's `last_attempt` / `last_sync` / `last_status` state is updated in the same way as the other triggers. When called against an unknown MAC, the service just performs the BLE write and returns.

## README outline

1. **Overview** — what the integration does, assumptions (BLE proxy or local adapter).
2. **Installation** — HACS custom repo + manual install.
3. **Setup** — walkthrough of Bluetooth discovery and manual add.
4. **Entities** — reference table of the 5 entities.
5. **Advanced: custom schedules** — how to disable `auto_sync` and build custom automations with `button.press` or the service. Example YAML snippets for: custom hour, multiple times per day, weekday-specific sync.
6. **Troubleshooting** — expected log messages, known warnings, how to enable debug logging.
7. **Battery impact** — table comparing daily/weekly/monthly cadence vs. expected battery drain. Warning against sub-daily sync.
8. **Credits** — link to `ashald/home-assistant-lywsd02` and `h4/lywsd02`.

## Testing strategy

| Layer | Framework | Scope |
|---|---|---|
| Pure-logic unit | `pytest` + `freezegun` | `_is_sync_day`, `_compute_next_sync`, timestamp / tz_offset math, BLE payload encoding |
| BLE unit | `pytest` + `unittest.mock` | `device.set_time` with `establish_connection` patched; validates GATT calls and payloads |
| HA integration | `pytest-homeassistant-custom-component` | Config flow (bluetooth + user paths), `async_setup_entry`, entity state reflects coordinator, service registration |

**Critical test cases:**

- DST transition detection: use `freezegun` to simulate Portugal spring-forward (2026-03-29 around 01:30 → 03:30) and autumn-fallback, verifying `_on_dst_check` triggers an immediate sync.
- `_compute_next_sync` edge cases: monthly in a month with DST transition; weekly where today is Sunday but past 03:30.
- Timestamp/tz_offset correctness for WEST (+1), WET (+0), and a negative-offset timezone.
- Config flow rejects duplicate MAC.

**CI:** GitHub Actions, single workflow running `pytest` on Python 3.12 (matches current HA core).

## Risks and open questions

- **LYWSD02 firmware variants.** The original `h4/lywsd02` project is several years old; if Xiaomi has shipped a firmware variant that changes the GATT contract, the protocol layer may need adjustments. Mitigation: test against the user's actual device early; fail loudly with a clear error if GATT writes fail.
- **BLE proxy reachability on HA startup.** If the HA Bluetooth stack isn't ready when the coordinator schedules its first tick, the first sync may log a "device not found" error. Acceptable — the next tick will succeed.
- **Daylight Saving rules outside Europe.** The DST check relies purely on `utcoffset()` delta, so it works regardless of which rules apply locally. No timezone-specific code paths.
