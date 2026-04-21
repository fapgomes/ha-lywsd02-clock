# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.0] - 2026-04-21

### Added
- Active bluez scan step before the bluezdbus-direct connect. Uses
  `BleakScannerBlueZDBus` imported directly (also not patched by HA) to
  populate bluez's internal device cache, then passes the freshly
  discovered `BLEDevice` to `BleakClientBlueZDBus`. This avoids the
  `BleakDeviceNotFoundError: Device with address ... was not found`
  error seen when HA's scanner is idle and bluez has no D-Bus entry for
  the device.

## [0.5.2] - 2026-04-21

### Fixed
- `BleakClientBlueZDBus.connect() missing 1 required positional argument:
  'pair'`. Newer bleak / habluetooth versions changed the backend signature.
  Connect call is now introspected at runtime with fallbacks, so it works
  across bleak 0.22, 0.23+, and whatever HA ships in future versions.

## [0.5.1] - 2026-04-21

### Fixed
- `bluezdbus direct error: ... does not support the asynchronous context
  manager protocol`. The backend class `BleakClientBlueZDBus` is low-level
  and doesn't implement `__aenter__`/`__aexit__` — the high-level
  `BleakClient` facade does. Switched to explicit
  `connect()` / `disconnect()` calls and explicit `response=True` on the
  GATT writes.

## [0.5.0] - 2026-04-21

### Fixed
- v0.4.0 "direct BleakClient" was still being intercepted by Home Assistant's
  `habluetooth` wrapper (HA patches `BleakClient` too, not just `BleakScanner`),
  so the wrapper refused to connect with _"No backend with an available
  connection slot that can reach address"_ whenever no HA scanner had a recent
  advertisement for the device.

### Added
- Third connection path that imports `BleakClientBlueZDBus` from
  `bleak.backends.bluezdbus.client` directly. That class reference is not
  patched by `habluetooth`, so the connection goes straight to `bluez` over
  D-Bus — the same route that `pygatt`/`bluepy`-based plugins
  (`ashald/home-assistant-lywsd02`, `h4/lywsd02`) use. Linux only.

### Changed
- Connection fallback order is now:
  1. HA Bluetooth stack (supports BLE proxies).
  2. `BleakClient(mac)` (goes through HA's wrapper — still useful when it
     succeeds for other reasons).
  3. `BleakClientBlueZDBus(mac)` via direct import (bypasses HA wrapper).
- Error message now lists which of the three paths failed and with what error.

## [0.4.0] - 2026-04-21

### Fixed
- The v0.3.0 "direct bleak scan" fallback was not actually direct —
  Home Assistant monkey-patches `bleak.BleakScanner` globally, so every
  scanner instance inside the HA process reads from the same (empty) HA
  cache that path 1 already failed on. The real "direct" path is via
  `BleakClient(mac)`, which HA does *not* patch and which goes straight
  to bluez on Linux. This matches how service-only plugins such as
  `ashald/home-assistant-lywsd02` succeed even when HA's cache is empty.

### Changed
- Connection fallback rewritten. Order of attempts:
  1. HA Bluetooth stack (supports BLE proxies).
  2. Direct `BleakClient(mac)` via OS bluez — only works with a local
     Bluetooth adapter on the Home Assistant host.
- Error message now says which specific path failed and how, instead of
  a generic "not found".

## [0.3.0] - 2026-04-21

### Fixed
- Sync failing with "No advertisement received" even when the device is
  actually reachable from the host OS (the same scenario where
  `ashald/home-assistant-lywsd02` succeeds).

### Changed
- `device.set_time` now falls back to a direct `BleakScanner.find_device_by_address`
  scan on the local OS Bluetooth adapter when Home Assistant's Bluetooth cache
  has no recent advertisement for the device. Order of attempts:
  1. HA's cached advertisement (instant).
  2. HA active-scan callback wait (up to ~30 s).
  3. Direct bleak scan on the local adapter (up to 15 s).
- Coordinator now logs the full traceback at `debug` when a sync fails.

### Notes
- The direct-bleak fallback only works with a local OS Bluetooth adapter.
  Setups that rely exclusively on ESPHome BLE proxies will still need HA's
  Bluetooth stack to see the advertisement (paths 1 or 2).

## [0.2.0] - 2026-04-21

### Added
- `dst_only` frequency option: no scheduled periodic sync — the device is only
  re-synced when the local UTC offset changes (twice a year in most of Europe).
  Great for users who trust the clock's native accuracy between DST transitions.
- Automatic initial sync when a config entry is set up, so the clock is correct
  immediately even in `dst_only` mode.
- English translations file (`translations/en.json`) so entity names render
  properly instead of falling back to generic labels like "Timestamp".
- `CHANGELOG.md` (this file).

### Changed
- Clearer entity names: `Last sync`, `Next sync`, `Sync status`, `Auto sync`,
  `Sync now` (previously the two timestamp sensors both showed up as
  "Timestamp" in the UI).
- `device.set_time` now waits up to 30 seconds for a fresh BLE advertisement
  before giving up when the Bluetooth stack has no cached advertisement for
  the device.
- "Device not found" error message now tells the user to press a button on the
  clock to wake it, and to check the MAC and BLE proxy range.

## [0.1.0] - 2026-04-20

Initial release.

- Config flow with Bluetooth discovery, manual add, and options reconfiguration.
- Per-device entities: `button.sync_now`, `switch.auto_sync`,
  `sensor.last_sync`, `sensor.next_sync`, `sensor.last_sync_status`.
- Daily / weekly / monthly scheduled sync at 03:30 local time with an
  independent DST check at 03:35.
- `lywsd02_clock.set_time` service for advanced / scripted flows.
- HACS-ready repository layout.
