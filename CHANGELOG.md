# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.10.1] - 2026-04-21

### Fixed
- `bleak connect after bluetoothctl: Device with address ... was not
  found`. The bluez D-Bus ObjectManager stores addresses in upper case,
  and `BleakClientBlueZDBus`'s internal lookup is case-sensitive. We
  were passing the lowercase MAC straight through, so the lookup
  always missed. Now we upper-case before constructing the client in
  both the `bluetoothctl+dbus` and the bluezdbus-direct paths.

## [0.10.0] - 2026-04-21

### Added
- **bluetoothctl + D-Bus combined path** as the primary non-proxy sync
  route. `bluetoothctl connect <mac>` via subprocess reliably establishes
  an ACL link (cooperates with HA's managed discovery, does not need
  `sudo`). While that ACL is open, `BleakClientBlueZDBus` — imported
  directly so HA's wrapper can't interfere — does the three GATT writes
  over D-Bus. Then `bluetoothctl disconnect` cleans up.

### Fixed
- `pygatt GATTToolBackend.start failed: No such file or directory: 'sudo'`
  on HAOS. v0.9.3's `reset_on_start=True` relied on `sudo hciconfig
  hci0 reset`, and HAOS has no `sudo`. The pygatt path now lives as
  path 3 (fallback) and the new bluetoothctl+D-Bus path (2) is the one
  that actually works on HAOS.

### Changed
- Sync fallback order:
  1. HA Bluetooth stack (cached connectable `BLEDevice`).
  2. **`bluetoothctl connect` + `BleakClientBlueZDBus` writes + `bluetoothctl disconnect`**.
  3. `pygatt` / `gatttool` (still useful on non-HAOS hosts that have `sudo`).
  4. `BleakClient(mac)` via HA wrapper.
  5. `BleakClientBlueZDBus(mac)` standalone.

## [0.9.3] - 2026-04-21

### Fixed
- pygatt (`gatttool`) now uses `reset_on_start=True`, matching
  `h4/lywsd02` (and therefore `ashald/home-assistant-lywsd02`). This
  briefly resets `hci0`, kicking Home Assistant's bluetooth scanner off
  for a fraction of a second so that `gatttool` has exclusive access to
  do its own scan and connect. HA's scanner auto-reconnects right after.
  The previous `reset_on_start=False` was trying to be too polite with
  HA's stack and was the root cause of all the connect timeouts on
  setups where `hci0` is the reachable adapter.

### Removed
- `_write_via_bluetoothctl` full-write path (v0.9.1). The scripted
  interactive session through stdin kept dumping help text instead of
  executing the gatt submenu commands — the actual connect attempt
  never ran. Not worth debugging further when the pygatt fix above
  solves the real problem.

## [0.9.2] - 2026-04-21

### Fixed
- `bluetoothctl: did not report connection success` on hosts that had
  just restarted (e.g. right after a Home Assistant restart). The non-
  interactive `bluetoothctl connect` subprocess does not trigger its own
  scan — if bluez's D-Bus tree does not already know the device, it fails
  instantly with "Device XX:XX:XX:XX:XX:XX not available". Manual
  interactive sessions had been working because interactive mode auto-
  scans on `connect`.

### Changed
- `_write_via_bluetoothctl` now runs a short (~8 s) `bluetoothctl
  --timeout 8 scan on` window before the connect+write script so bluez
  has the device in its ObjectManager.

## [0.9.1] - 2026-04-21

### Added
- Full write path via `bluetoothctl` subprocess (connect → `menu gatt` →
  select-attribute → write → disconnect, piped through stdin). We had
  proven that `bluetoothctl` reliably reaches the device over D-Bus when
  HA holds `hci0`, but priming alone did not help `gatttool` which uses
  legacy raw HCI sockets (different transport). Running the full write
  through the same `bluetoothctl` session finally lets the integration
  succeed on hosts where `hci0` is busy with HA's managed discovery.

### Changed
- Connection fallback order is now:
  1. HA Bluetooth stack (when a connectable `BLEDevice` is already cached).
  2. **`bluetoothctl` subprocess (full write).**
  3. `pygatt` / `gatttool` (with the bluez-prime from v0.9.0).
  4. `BleakClient(mac)` via HA wrapper.
  5. `BleakClientBlueZDBus(mac)` via direct import.

## [0.9.0] - 2026-04-21

### Added
- Automatic bluez D-Bus priming via `bluetoothctl connect`/`disconnect`
  subprocess before the pygatt path. When Home Assistant's Bluetooth
  integration holds `hci0` in managed-discovery mode, `gatttool` cannot
  discover a device on its own and times out; `bluetoothctl` however
  cooperates with HA's scan and consistently registers the device in
  `/org/bluez/hciX/dev_XX_...`. Once registered, `gatttool` connects
  instantly, and the subsequent `char_write` (now without response)
  succeeds. Removes the previous requirement for a one-off manual
  `bluetoothctl connect` from the HA host terminal.

## [0.8.1] - 2026-04-21

### Fixed
- `pygatt: No response received` after a successful GATT connection. The
  LYWSD02 accepts time writes as "write without response" — requesting
  a response was causing the write to time out at `char_write_handle`.
  Setting `wait_for_response=False` matches what `h4/lywsd02` does and
  lets the write succeed once pygatt has a live connection to the device.

### Note
- Before Home Assistant's Bluetooth stack can reach the device reliably,
  `bluez` needs the device registered in its D-Bus tree. One-time manual
  registration: run `bluetoothctl connect <mac>` from the HA host
  terminal (the connection only needs to succeed once, then you can
  disconnect). After that, all sync attempts via the local adapter
  should succeed without further intervention.

## [0.8.0] - 2026-04-21

### Fixed
- `pygatt`/`gatttool` path timing out because of interference from Home
  Assistant's active BLE scanning. Our previous advertisement-wait phase
  registered a callback in `ACTIVE` scanning mode, which asked HA to
  keep `hci0` in active-scan mode. When `gatttool` then tried to
  acquire the adapter for a connection it could not do its own active
  scan and timed out. This matched the failure mode the user was seeing
  while the very similar `ashald/home-assistant-lywsd02` plugin kept
  working in the same setup (because that plugin does not register any
  HA scanning callbacks).

### Changed
- Sync flow reworked:
  1. HA Bluetooth stack — only used when a connectable `BLEDevice` is
     already cached. No waits, no active-scan activation. This lets
     proxy-connectable setups short-circuit, while other setups skip it.
  2. `pygatt` / `gatttool` on the local adapter (was path 4, now runs
     second so it gets `hci0` unmolested).
  3. `BleakClient(mac)` via HA wrapper.
  4. `BleakClientBlueZDBus(mac)` via direct import.
- The 30-second advertisement-wait and associated error messaging are
  gone.
- `BleakScannerBlueZDBus` construction now also tries the newer
  `bluez={}` keyword-only signature as a first attempt.

### Kept
- Auto-discovery via `manifest.json` Bluetooth matcher is unchanged.

## [0.7.0] - 2026-04-21

### Added
- **`pygatt` fallback path** (path 4). Spawns `gatttool` out-of-process
  and writes the payloads there, matching exactly how
  `ashald/home-assistant-lywsd02` (via `h4/lywsd02`) reaches the device
  on Linux hosts. This bypasses bleak, `habluetooth`, and bluez's
  managed-discovery layer entirely. New requirement: `pygatt>=4.0.5`.
  Requires `gatttool` on PATH — ships with most bluez distributions.
- Debug logs now say which scanner signature was used (or why each one
  failed), to make future bleak-signature changes easier to diagnose.

### Changed
- Connection fallback order is now:
  1. HA Bluetooth stack (supports BLE proxies).
  2. `BleakClient(mac)` through HA's wrapper.
  3. `BleakClientBlueZDBus(mac)` + raw bluez scan — bypasses wrapper.
  4. `pygatt` / `gatttool` subprocess — bypasses bleak entirely.
- Error message now lists all four paths.

## [0.6.1] - 2026-04-21

### Fixed
- `BleakScannerBlueZDBus.__init__() missing 2 required positional arguments`.
  Newer bleak versions require `detection_callback`, `service_uuids`, and
  `scanning_mode` explicitly. Constructor is now tried with multiple
  known signatures as fallbacks.

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
