# Battery sensor — read during sync connection

**Date:** 2026-08-03
**Status:** Approved

## Background

The classic LYWSD02 does not broadcast battery level in its MiBeacon
advertisements, so the core `xiaomi_ble` integration (which covers
temperature/humidity passively) cannot provide it. The battery IS exposed as
a readable GATT characteristic: `EBE0CCC4-7A0A-4B0C-8A1A-6FF2997DA3A6`
(1 byte, percent) — confirmed by live GATT enumeration of the maintainer's
device (handle 66, props `['read']`) and matching the `h4/lywsd02` library.

The integration already opens a connection on every sync; the read
piggybacks on it. No extra connections, no extra drain on the clock's
battery. Refresh cadence = sync frequency (plus the *Sync now* button) —
adequate for a battery that lasts ~a year.

## Design

1. **`const.py`** — add
   `UUID_BATTERY: Final = "EBE0CCC4-7A0A-4B0C-8A1A-6FF2997DA3A6"`.
2. **`device.py`** —
   - `_write_payloads` returns `int | None`: after the payload writes
     succeed, `read_gatt_char(UUID_BATTERY)` on the same connection,
     best-effort: any exception or empty/out-of-range value (valid range
     0–100) → debug log, return `None`. A battery-read failure must NEVER
     fail the sync.
   - `_read_back_matches` gains the same best-effort battery read on its
     verification connection and returns `tuple[bool, int | None]`.
   - `set_time` returns `int | None` (the battery level, `None` when
     unavailable). Additive change: existing callers ignore the return.
3. **`coordinator.py`** — new attribute `battery_level: int | None = None`;
   `async_sync` stores the value returned by `set_time` on success (a `None`
   return leaves the previous value in place, so a single failed read does
   not blank the sensor).
4. **`__init__.py`** — the service handler also feeds the returned level to
   the matching coordinator when one exists (same place it already updates
   `last_sync`).
5. **`sensor.py`** — `BatterySensor(LYWSD02Entity, SensorEntity)`:
   `device_class=SensorDeviceClass.BATTERY`,
   `native_unit_of_measurement=PERCENTAGE`,
   `state_class=SensorStateClass.MEASUREMENT`,
   `entity_category=EntityCategory.DIAGNOSTIC`,
   `native_value` = `coordinator.battery_level`. Translation key `battery`
   added to `strings.json`/`translations/en.json`. Unknown until the first
   successful sync after a restart — consistent with *Last sync*.

## Tests

- Battery read succeeds → `set_time` returns the level; payload writes
  unchanged.
- Battery read raises / returns empty / out-of-range → sync still succeeds,
  returns `None`.
- Read-back verification path also returns a battery level when available.
- Coordinator keeps the previous level when a sync returns `None`.

## Non-goals

- No dedicated battery polling schedule (rejected: extra BLE connections
  and clock-battery drain for no practical gain).
- No temperature/humidity sensors (covered passively by core `xiaomi_ble`).
- No state restore across restarts (consistent with the existing entities).

## Release

`v0.16.0` — dedicated version-bump commit with CHANGELOG entry.
