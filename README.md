# Home Assistant EchoCheck Tank Sensor (HACS)

[EchoCheck BLE](https://ghpgroupinc.com/pages/echocheck) propane tank sensor integration for Home Assistant.

This integration reads EchoCheck tank sensors (BLE name `@TNK*`, manufacturer ID `0x4E54`) **passively**, from their BLE advertisements. It never connects to the sensor, which matters for three reasons: a connection makes the sensor stop advertising altogether, it permanently occupies one of your adapter's connection slots, and current sensor firmware sends nothing over a connection anyway.

> **Disclaimer:** This is an independent community integration and is not affiliated with, endorsed by, or supported by Thincke or EchoCheck. Use it at your own risk.

## Features

- **Passive** — no connection, no connection slot, works with any Bluetooth proxy
- **Temperature compensated** tank level (see below)
- Works with both older and current sensor firmware
- Battery level and signal strength from the same advertisement
- Tank size dropdown for standard propane cylinders, plus custom
- Multi-sensor support (one config entry per sensor MAC)
- Sensors:
  - Tank Level (%)
  - Battery (%)
- Diagnostic entities:
  - Signal Strength (dBm)
  - Data Healthy (binary sensor)

## Configuration

1. Add integration: **EchoCheck Tank Sensor**
2. Select a discovered BLE device from the dropdown, or enter the MAC address manually
3. Select your tank size
4. If **Custom** is selected, enter the depth of liquid your tank holds when full
5. Optionally select a **temperature sensor** located near your tanks — strongly recommended, see below

## Tank Sizes

| Key | Name | Fill height |
|-----|------|-------------|
| `20lb_v` | 20 lb Vertical | 254 mm |
| `30lb_v` | 30 lb Vertical | 381 mm |
| `40lb_v` | 40 lb Vertical | 508 mm |
| `100lb_v` | 100 lb Vertical | 812.8 mm |
| `120gal_v` | 120 gal Vertical | 974 mm |
| `europe_6kg` / `europe_11kg` / `europe_14kg` | EU cylinders | 340 / 390 / 430 mm |
| `custom` | Custom | User-specified |

These are **fill heights** — the depth of liquid a full tank holds — not the cylinder's
overall height. A 30 lb bottle stands about 610 mm tall but holds roughly 381 mm of
propane when full, because propane is filled to 80% of volume.

## Why temperature matters

The sensor reports the round-trip flight time of an ultrasonic pulse from the tank
floor to the liquid surface. Converting that to a depth requires the speed of sound in
liquid propane, which changes with temperature — roughly 960 m/s at 0 °C, falling about
4.4 m/s per °C.

The sensor does not measure or compensate for temperature itself. Left uncompensated,
an untouched tank appears to lose about half a percent of level per degree of warming:
around **16 percentage points across a 0–40 °C range**. If you have seen a tank slowly
drift without using any gas, this is why.

Selecting a temperature sensor near your tanks corrects for it. Any temperature entity
works; one physically close to the tanks is best, since the propane's temperature is
what matters. Without one, the integration assumes 15 °C.

## Requirements

- Home Assistant 2024.1.0 or newer
- A Bluetooth adapter or [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy) within range of your sensor

## Installation via HACS

1. Open HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/phurth/ha-echocheck` as an **Integration**
3. Install **EchoCheck Tank Sensor**
4. Restart Home Assistant
5. Go to Settings → Devices & Services → Add Integration → **EchoCheck Tank Sensor**
