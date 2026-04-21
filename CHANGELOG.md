# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
