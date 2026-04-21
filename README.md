# LYWSD02 Clock — Home Assistant integration

Keep one or more Xiaomi **LYWSD02** e-Ink clocks in sync with Home Assistant's local time over Bluetooth — directly or through an [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html).

Unlike service-only plugins, this is a full integration with UI setup, per-device entities, automatic scheduled sync, and automatic daylight-saving-time handling.

## Features

- **Automatic discovery** — LYWSD02 devices seen via your Bluetooth adapter or a BLE proxy appear as a discovery card in *Settings → Devices & Services*.
- **UI-driven setup** — no YAML. One config entry per clock.
- **Configurable cadence** — `daily`, `weekly` (Sundays), `monthly` (day 1) or `DST-only`. Scheduled syncs always fire at 03:30 local time.
- **Automatic DST** — a daily check at 03:35 forces a sync whenever the local UTC offset changes, independently of the chosen frequency. In `DST-only` mode this is the *only* automatic trigger.
- **Initial sync on setup** — the first successful sync runs automatically when the device is first added, so the clock is correct right away even in `DST-only` mode.
- **Per-device entities**:
  - `button.<name>_sync_now` — run a manual sync now.
  - `switch.<name>_auto_sync` — enable/disable the schedule for this device.
  - `sensor.<name>_last_sync` — timestamp of the last successful sync.
  - `sensor.<name>_next_sync` — when the next scheduled sync will fire.
  - `sensor.<name>_last_sync_status` — `success`, `failed` or `never`, with the error message as an attribute.
- **Backwards-compat service** — `lywsd02_clock.set_time` for advanced / scripted flows.

## Requirements

- Home Assistant **2024.1** or newer.
- A working Bluetooth stack in Home Assistant: either a local adapter supported by the [Bluetooth integration](https://www.home-assistant.io/integrations/bluetooth/) or an [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html) within range of the clock.

## Installation

### HACS (recommended)

1. In HACS, open *Integrations → ⋮ → Custom repositories*.
2. Add `https://github.com/fapgomes/ha-lywsd02-clock` with category **Integration**.
3. Install **LYWSD02 Clock** and restart Home Assistant.

### Manual

1. Copy `custom_components/lywsd02_clock/` into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.

## Setup

### Bluetooth discovery (automatic)

When Home Assistant sees an advertisement from an LYWSD02 — directly or via a BLE proxy — a **Discovered** card appears in *Settings → Devices & Services*. Click **Configure**, pick a friendly name, frequency, temperature unit and clock mode, and save. Done.

### Manual add

If the device doesn't show up automatically:

1. *Settings → Devices & Services → + Add Integration → LYWSD02 Clock*.
2. Select the device from the list of recently-seen unconfigured LYWSD02 clocks, or enter a raw MAC address.
3. Fill in the same configuration form.

### Reconfiguring

*Devices & Services → LYWSD02 Clock → Configure* reopens the form. Saving applies changes on the next sync.

## Entities

| Entity | Description |
|---|---|
| `button.<name>_sync_now` | Press to sync immediately, regardless of schedule or auto-sync state. |
| `switch.<name>_auto_sync` | On = the schedule runs. Off = no automatic sync, no DST sync. Manual button / service still work. |
| `sensor.<name>_last_sync` | Timestamp (`device_class: timestamp`) of the last successful sync. `unknown` until the first success. |
| `sensor.<name>_next_sync` | When the next scheduled sync will fire. `unknown` when auto-sync is off. |
| `sensor.<name>_last_sync_status` | `success` / `failed` / `never`. Attributes: `error_message`, `attempted_at`. |

All entities are grouped under a single HA device (manufacturer Xiaomi, model LYWSD02, identifier = MAC).

## Advanced: custom schedules

Default sync fires at **03:30 local time**. Configurable hour / minute / weekday is *not* exposed in the UI — build your own automation instead.

### Disable auto-sync and use the button

Turn off `switch.<name>_auto_sync`, then build an automation that calls the button on your own schedule:

```yaml
automation:
  - alias: LYWSD02 - sync twice a day
    triggers:
      - trigger: time
        at: ["03:30:00", "15:30:00"]
    actions:
      - action: button.press
        target:
          entity_id: button.kitchen_clock_sync_now
```

### Use the service directly (no config entry required)

```yaml
action: lywsd02_clock.set_time
data:
  mac: E7:2E:01:42:60:FF
  clock_mode: 24
  temp_mode: C
```

All service fields:

| Field | Default | Description |
|---|---|---|
| `mac` | *required* | Bluetooth MAC. |
| `timestamp` | current UTC | Override the time written (epoch seconds). |
| `tz_offset` | HA offset | Override the timezone offset in hours. |
| `temp_mode` | entry's setting, else `C` | `C` or `F`. |
| `clock_mode` | entry's setting, else `24` | `12` or `24`. |
| `timeout` | 60 | BLE connection timeout in seconds. |

When the MAC matches a configured entry and no optional fields are provided, the call goes through the coordinator and updates `last_sync` / `last_sync_status` just like a scheduled sync.

## Troubleshooting

Enable debug logs to see every BLE write:

```yaml
logger:
  default: info
  logs:
    custom_components.lywsd02_clock: debug
```

### "No BLE device with MAC … known to the Bluetooth stack"

The Bluetooth integration hasn't seen an advertisement from the device recently.

- Move closer, or add a BLE proxy within range.
- Wake the clock (press its button, change the battery).
- The next scheduled tick will retry automatically; you don't need to do anything.

### "GATT write failed"

Usually transient. `bleak-retry-connector` already retries up to 3 times per sync attempt. If it keeps failing:

- Check battery level — near-empty batteries produce unstable BLE connections.
- Try another BLE proxy if you have one.

### Time / DST looks wrong

- Home Assistant's local timezone must be correct (*Settings → System → General*).
- The DST check runs at 03:35 local time; outside-the-window transitions will catch up at the next tick.

## Battery impact

The LYWSD02 runs on a single CR2032 cell. Every sync wakes the BLE stack and writes three GATT characteristics, which costs real energy. Rough guidance:

| Frequency | Expected battery life | Notes |
|---|---|---|
| DST-only | ~2+ years | Only the twice-a-year DST transitions plus the initial sync. Relies on the clock's native accuracy between transitions. |
| Monthly | ~1.5–2 years | DST transitions still trigger a sync when they happen. |
| Weekly | ~12–18 months | Reasonable middle ground. |
| Daily | ~8–12 months | Default. Good enough for almost everyone. |
| Sub-daily (custom automation) | <6 months | Not recommended. |

Actual battery life varies with temperature and firmware revision.

## Credits

- [`ashald/home-assistant-lywsd02`](https://github.com/ashald/home-assistant-lywsd02) — the original HA plugin this integration replaces.
- [`h4/lywsd02`](https://github.com/h4/lywsd02) — Python library whose reverse-engineered protocol informed the BLE payloads.

## License

[MIT](LICENSE)
