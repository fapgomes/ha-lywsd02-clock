# BLE stack rewrite — Home Assistant Bluetooth API only

**Date:** 2026-08-03
**Status:** Approved
**Driver:** Home Assistant core review of the integration submission (@frenck,
requested changes): the integration must stop resetting the shared adapter,
monkeypatching pygatt, and shelling out to `bluetoothctl`/`hciconfig`, and must
use Home Assistant's Bluetooth APIs instead. The undeclared `lywsd02`/`bluepy`
path must be dropped, and the service's `mac` parameter must be validated.

## Background: why the fallback ladder exists, and why it can go

`device.py` currently tries up to five write paths in order: the `lywsd02`
library (never installed — not in the manifest), the HA Bluetooth stack,
pygatt/gatttool (with an adapter reset), `bluetoothctl` subprocesses + D-Bus,
and a raw bluezdbus backend client. Only the pygatt path has ever delivered
writes in practice.

Live debugging on the maintainer's HAOS instance (core 2026.7.4, bleak 3.0.2)
proved that the HA path — the only one the core review allows — has never
worked in any installation, for three independent reasons:

1. **MAC case mismatch.** `_normalize_mac()` lowercases the address, but
   `habluetooth`'s `async_ble_device_from_address` is a plain `dict.get()`
   against uppercase keys (`habluetooth/manager.py:1405`). The lookup always
   returned `None`, so the HA path was always skipped.
2. **The advertisement wait is dead code.** `_resolve_ble_device_via_ha` and
   `_wait_for_ha_advertisement` exist but are never called; `set_time` gives
   up immediately when no advertisement is cached.
3. **Double connect.** `_write_via_retry_connector` wraps the
   already-connected client returned by `establish_connection` in
   `async with client:`, which calls `connect()` a second time. Inside HA this
   surfaced as `GATT Protocol Error: Unlikely Error`; with raw bleak outside
   the habluetooth wrapper the same defect raises
   `BleakError: Client is already connected`. One defect, two manifestations.

With all three fixed, the corrected pattern was validated against the real
device from inside the HA container: `establish_connection` →
`write_gatt_char(..., response=True)` on both characteristics → `disconnect()`
— both writes acknowledged. GATT enumeration confirmed the time and unit
characteristics advertise `['read', 'write']` only (Write-Request), so
`response=True` is explicit and correct.

Measured device behaviour (used to size timeouts): the LYWSD02 advertises
roughly every 9.6 s and was seen by both the local `hci0` adapter and an
ESPHome proxy.

## Goals

- Single write path through Home Assistant's Bluetooth stack
  (`homeassistant.components.bluetooth` + `bleak-retry-connector`). Works with
  local adapters and ESPHome BLE proxies alike.
- No adapter resets, no subprocesses, no monkeypatching, no direct backend
  imports.
- Validate the `mac` service parameter.
- Focused test suite covering the defects this rewrite fixes.

## Non-goals

- No changes to entities, coordinator scheduling, config flow UX, or the
  service's public schema (beyond MAC validation).
- No new fallback paths (`BleakClient(mac)` as a secondary route was
  considered and rejected: same stack, same slots, no demonstrated gain).

## Design

### 1. `device.py` — public API unchanged, interior reduced

Keep the signature
`set_time(hass, mac, *, temp_unit, clock_mode, timestamp_utc, tz_offset_hours, timeout, write_clock_mode)`
and the exceptions `DeviceNotFoundError` / `DeviceCommunicationError`, so
`coordinator.py` and `button.py` need no changes (`__init__.py` changes only
for the service-schema MAC validation in §4).

Keep unchanged (pure, already correct): `_build_time_payload`,
`_build_unit_payload`, `_build_mode_payload`, `_current_time_and_offset`.

Delete: the `pygatt` and `lywsd02` imports and availability flags,
`_patch_pygatt_no_sudo` and its module-level invocation, the pygatt logging
filter, `_pygatt_sync_write`, `_write_via_pygatt`, `_lywsd02_lib_sync_write`,
`_write_via_lywsd02_lib`, `_bluetoothctl_scan`, `_write_via_bluetoothctl`,
`_write_via_bluetoothctl_then_dbus`, `_prime_bluez_via_bluetoothctl`,
`_discover_via_raw_bluez`, `_write_via_bluezdbus_direct`,
`_write_via_direct_client`, `_pick_response_mode`, `_resolve_characteristics`,
the bluezdbus backend imports (`_BluezBackendClient`, `_BluezBackendScanner`),
and the now-unused constants `ADVERTISEMENT_WAIT_SECONDS` and
`DIRECT_CLIENT_TIMEOUT_SECONDS`. Net effect: ~1040 lines → ~230.

### 2. Device resolution

```python
async def _resolve_ble_device(
    hass: HomeAssistant, mac: str, timeout: float
) -> BLEDevice | None:
    address = mac.upper()  # fixes defect 1
    ble_device = bluetooth.async_ble_device_from_address(
        hass, address, connectable=True
    )
    if ble_device is not None:
        return ble_device
    # Wait for an advertisement (fixes defect 2), re-querying from the
    # callback (see trap below).
    ...
```

The wait registers a callback via `bluetooth.async_register_callback` with
`BluetoothCallbackMatcher(address=address, connectable=True)` and waits up to
`timeout` seconds (the caller's `timeout`, default `DEFAULT_TIMEOUT` = 60 s —
no new constant).

**Trap, learned by measurement:** `async_register_callback` fires immediately
for devices HA already knows, so a one-shot `asyncio.Event` can resolve
instantly while `async_ble_device_from_address` still returns `None`. The
callback must therefore **re-query** `async_ble_device_from_address` and only
complete the wait when it actually returns a device, staying subscribed until
then or until timeout.

Uppercase conversion happens only at this boundary. The config entry and
`unique_id` keep the lowercase convention (existing entries keep working).

### 3. Write sequence

Exactly the pattern validated against the real device:

```python
client = await establish_connection(
    BleakClientWithServiceCache, ble_device, name=mac, max_attempts=3
)
try:
    await client.write_gatt_char(UUID_TIME, time_payload, response=True)
    await client.write_gatt_char(UUID_UNIT, unit_payload, response=True)
    if mode_payload is not None:
        await client.write_gatt_char(UUID_TIME, mode_payload, response=True)
finally:
    await client.disconnect()
```

No `async with` on the already-connected client (fixes defect 3).
`response=True` is explicit: both characteristics support Write-Request only.
The uppercase UUIDs in `const.py` are fine — bleak normalizes characteristic
specifiers internally (verified live).

**Error mapping:** no device after the wait → `DeviceNotFoundError` with
guidance (press a button on the clock to wake it / ensure a proxy or adapter
is in range). Connection or write failure → `DeviceCommunicationError`
wrapping the underlying error.

**Time budget:** worst case ≈ `timeout` (60 s wait) + 3 connect attempts —
roughly 70–90 s before failure. Acceptable for a service call and for the
scheduled sync; in practice the device advertises every ~10 s, so the wait
resolves in seconds. (Superseded by the post-verification retry loop below:
the worst case extends well beyond the advertisement timeout, bounded by 3
write attempts plus their read-back verifications — see "Post-verification
amendment" below.)

### 4. MAC validation and manifest cleanup

New module `mac.py` with `normalize_mac()` and `is_valid_mac()`, moved out of
`config_flow.py`; `config_flow.py` then imports them from `mac.py`. Used in
three places:

- `config_flow.py` (as today, now imported),
- `__init__.py` `async_setup_entry` (normalization, as today),
- the `set_time` service schema (**new** — this closes the review point):

```python
vol.Required("mac"): vol.All(cv.string, _validate_mac)
```

where `_validate_mac` raises `vol.Invalid` on anything that is not a
`xx:xx:xx:xx:xx:xx` MAC (case-insensitive input, normalized to lowercase).

`manifest.json`: `requirements` becomes `["bleak-retry-connector>=3.0"]`
(pygatt dropped; lywsd02/bluepy were never declared). Everything else in the
manifest stays.

### 5. Tests and CI

New `tests/` using `pytest-homeassistant-custom-component`.

**Regression tests (fail on the current code — they prove the defects):**

- `test_device.py`:
  - `async_ble_device_from_address` is called with the **uppercase** MAC
    (defect 1);
  - when no device is cached, the code registers a callback and waits, and
    the callback **re-queries** rather than trusting the first fire
    (defect 2, including the immediate-fire trap);
  - the write sequence performs exactly one connect (no context-manager
    re-entry), writes with `response=True`, and disconnects in `finally`
    (defect 3);
  - no device within the timeout → `DeviceNotFoundError`; write failure →
    `DeviceCommunicationError`.
- `test_services.py`: service call with an invalid `mac` is rejected by the
  schema; valid MAC in any case reaches `set_time` normalized.

**Characterization tests (pass today — they protect the rewrite):**

- `test_payloads.py`: byte-exact expectations for the three payload builders
  (time+tz, unit C/F, 12/24 h mode).
- `test_mac.py`: `normalize_mac` / `is_valid_mac` accept and reject the right
  shapes.

CI: add a `tests` job to `.github/workflows/validate.yml` alongside
`hassfest` and `hacs`.

### 6. Release

All work commits first; then a dedicated version-bump commit: `v0.15.0`,
`CHANGELOG.md` entry grouping the rewrite, `manifest.json` version. After
release, re-request the core review.

## Verification plan

1. Test suite green locally and in CI.
2. Install on the maintainer's HAOS instance, restart core, press *Sync now*,
   and confirm the debug log shows the HA-stack write succeeding
   (`Wrote time/unit/mode to … via HA Bluetooth`) with no pygatt/bluetoothctl
   lines (they no longer exist).
3. Optional: confirm a sync that goes through an ESPHome proxy (e.g. with
   the local adapter disabled or the clock only in range of a proxy). This
   validates the main functional gain of the rewrite, but is not a release
   blocker if impractical to stage.

## Post-verification amendment (2026-08-03)

Live verification on the maintainer's device revealed a firmware quirk the
single-shot write design missed: the LYWSD02 intermittently drops the BLE
link immediately after connect. A write in flight then fails (BlueZ surfaces
ATT `UNLIKELY_ERROR 0x0E`) — but the device APPLIES the write anyway; only
the acknowledgement is lost (visually confirmed: a sync that reported
"failed after 3 attempts" had set the clock correctly). The legacy pygatt
path was reliable only because it retried 3 times and treated a missing ACK
as delivered.

Amendments to §3:
- `set_time` retries the write phase up to `WRITE_ATTEMPTS = 3` times, each
  attempt on a fresh `establish_connection`, recomputing defaulted
  timestamps per attempt (`WRITE_RETRY_DELAY_SECONDS = 2.0` between
  attempts).
- On a failed write, `_read_back_matches` opens a fresh connection and reads
  the time (and unit) back; a match within `VERIFY_TOLERANCE_SECONDS = 30`
  confirms delivery and the sync reports success. The optional clock-mode
  payload cannot be read back and is assumed delivered alongside.
