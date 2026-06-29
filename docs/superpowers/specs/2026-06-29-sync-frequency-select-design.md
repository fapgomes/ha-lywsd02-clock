# Design: "Sync frequency" Select entity

**Date:** 2026-06-29
**Status:** Approved

## Problem

The sync frequency (`CONF_FREQUENCY`) can only be changed through the
integration's config/options flow. The user wants to pick it directly from the
device page, next to the existing "Auto sync" switch and "Sync now" button.

## Goal

Expose the existing sync frequency as a **Select entity** in the device's
*Controls* section. No new frequency values are added — the dropdown surfaces
the four choices that already exist:

- `daily` — Daily
- `weekly` — Weekly (Sundays)
- `monthly` — Monthly (1st)
- `dst_only` — DST transitions only (no scheduled sync)

## Approach

Mirror the established pattern of the `AutoSyncSwitch` (`switch.py`): an entity
that writes the chosen value into `entry.options` and lets the existing update
listener reload the entry. The scheduler then reads the new frequency on its
next tick. **No Bluetooth write is involved** — frequency is purely a
scheduling concern. (The previously removed `ClockModeSelect`, v0.13.1, did
write over BLE; this one does not, so it carries none of that risk.)

The `select.py` file already exists but is dead code: `Platform.SELECT` is not
in `PLATFORMS`, so `ClockModeSelect` is never loaded. It is repurposed.

## Changes

1. **`select.py`** — replace `ClockModeSelect` with `FrequencySelect`:
   - `_attr_translation_key = "frequency"`
   - unique_id suffix `"frequency"`
   - `_attr_options = FREQUENCIES` (from `const.py`)
   - `current_option` returns `self.coordinator.frequency`
   - `async_select_option(option)` writes
     `entry.options[CONF_FREQUENCY] = option` via
     `hass.config_entries.async_update_entry(entry, options=...)`, exactly like
     `AutoSyncSwitch._set_option`. The `_async_update_listener` in
     `__init__.py` reloads the entry.

2. **`__init__.py`** — add `Platform.SELECT` back to `PLATFORMS`.

3. **`strings.json` + `translations/en.json`** — under `entity.select`, replace
   the obsolete `clock_mode` block with a `frequency` block:
   - `name`: "Sync frequency"
   - `state`: the four labels, reusing the text already present under
     `selector.frequency` (Daily / Weekly (Sundays) / Monthly (1st) /
     DST transitions only (no scheduled sync)).

## Data flow

User picks an option in the dropdown → `async_select_option` → `entry.options`
updated → entry reload → coordinator reads the new `frequency` on its next
03:30 tick. The "Next sync" sensor reflects the change after reload.

## Out of scope (unchanged)

- Scheduling logic in `coordinator.py` (`is_sync_day`, `compute_next_sync`).
- The config/options flow — frequency stays configurable there too, the same
  way `auto_sync` lives in both places.
- `sensor.py`, `button.py`, `switch.py`, `device.py`.
- No new frequency values (no "yearly").

## Verification

The repo has no test suite. Verify that:

- The integration loads without errors after the change.
- The "Sync frequency" select appears in the device's Controls.
- Selecting a value persists across a reload and the "Next sync" sensor updates
  accordingly.

## Release

Bump to v0.14.0 in a dedicated commit with a `CHANGELOG.md` entry.
