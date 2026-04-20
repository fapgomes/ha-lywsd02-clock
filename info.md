# LYWSD02 Clock

Home Assistant custom integration that keeps one or more Xiaomi LYWSD02 e-Ink clocks in sync with Home Assistant's local time over Bluetooth (directly or through an ESPHome BLE proxy).

- Automatic discovery via Bluetooth.
- UI-driven setup, one config entry per device.
- Low-frequency sync (daily / weekly / monthly) with automatic DST handling.
- Service `lywsd02_clock.set_time` for advanced / scripted flows.

See the README for full documentation.
