# Home Assistant EchoCheck Tank Sensor (HACS)

EchoCheck BLE propane tank sensor integration for Home Assistant.

This integration connects to EchoCheck tank sensors (BLE name `@TNK*`, manufacturer ID `0x4E54`) via active GATT connection and parses ultrasonic echo measurements to calculate tank level.

> **Disclaimer:** This is an independent community integration and is not affiliated with, endorsed by, or supported by Thincke or EchoCheck. Use it at your own risk.

## Features

- Active GATT BLE connection (works with HA Bluetooth proxies)
- Tank level percentage from calibrated ultrasonic echo measurement
- Battery level from BLE advertisement data (no extra GATT read)
- Firmware version via OTA characteristic exchange
- Tank type dropdown matching standard propane cylinder sizes
- Multi-sensor support (one config entry per sensor MAC)
- Sensors:
  - Tank Level (%)
  - Battery (%)
- Diagnostic entities:
  - Firmware Version
  - Signal Strength (dBm)
  - Data Healthy (binary sensor)

## Configuration

1. Add integration: **EchoCheck Tank Sensor**
2. Select a discovered BLE device from the dropdown, or enter the MAC address manually
3. Select tank type from the dropdown
4. If **Custom** is selected, enter the calibrated fill height in mm

## Tank Types

| Key | Name | Calibrated Height |
|-----|------|-------------------|
| `20lb_v` | 20 lb Vertical (approx) | 169 mm |
| `30lb_v` | 30 lb Vertical | 254 mm |
| `40lb_v` | 40 lb Vertical (approx) | 338 mm |
| `100lb_v` | 100 lb Vertical (approx) | 542 mm |
| `custom` | Custom | User-specified |

The 30 lb calibrated height (254 mm) is confirmed via cross-validation with a Mopeka sensor on the same tank.

## Requirements

- Home Assistant 2024.1.0 or newer
- A Bluetooth adapter or [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy) within range of your sensor

## Installation via HACS

1. Open HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/phurth/ha-echocheck` as an **Integration**
3. Install **EchoCheck Tank Sensor**
4. Restart Home Assistant
5. Go to Settings → Devices & Services → Add Integration → **EchoCheck Tank Sensor**
