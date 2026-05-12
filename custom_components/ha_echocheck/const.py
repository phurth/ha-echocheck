"""Constants for the EchoCheck BLE tank sensor integration."""

from __future__ import annotations

DOMAIN = "ha_echocheck"

# ── GATT UUIDs (confirmed from HCI capture) ─────────────────────────────────
DATA_SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
NOTIFY_CHAR_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"  # READ | NOTIFY
WRITE_CHAR_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"   # READ | WRITE_NO_RESP

OTA_SERVICE_UUID = "00010203-0405-0607-0809-0a0b0c0d1912"
OTA_CHAR_UUID = "00010203-0405-0607-0809-0a0b0c0d2b12"

# Standard BLE Battery Service (confirmed from UuidInfo.java in app binary)
BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
BATTERY_CHAR_UUID = "00002a19-0000-1000-8000-00805f9b34fb"  # READ; returns 0-100 as single byte

# Telink firmware version characteristic (confirmed from UuidInfo.java in app binary)
VERSION_SERVICE_UUID = "0000d0ff-3c17-d293-8e48-14fe2e4da212"
VERSION_CHAR_UUID = "0000ffd4-0000-1000-8000-00805f9b34fb"  # READ; UTF-8 version string

# ── Device identification ────────────────────────────────────────────────────
# Confirmed from HCI capture: sensor advertises as "@TNK<suffix>" (e.g. "@TNK2140F3").
# Manufacturer ID 0x4E54 (20052) is present in all advertisements.
ECHOCHECK_NAME_PREFIX = "@TNK"
ECHOCHECK_MANUFACTURER_ID = 0x4E54

# Battery level is broadcast in every advertisement, in the manufacturer data
# (company ID 0x4E54).  The 26-byte payload (after company ID) has battery at
# byte index 6, as a plain integer 0-100.
MANUF_BATTERY_OFFSET = 6

# Firmware version is obtained via the OTA characteristic:
#   write OTA_FW_VERSION_REQ → receive 0xFF05 notification → bytes [2:5] = version
# Version encoding: little-endian → bytes[4].bytes[3].bytes[2] = major.minor.patch
# Confirmed from HCI capture: response 05 ff 00 00 01 → version "1.0.0"
OTA_FW_VERSION_REQ = b'\x04\xff\x00\x00\x00'  # opcode 0xFF04 LE + 3 padding bytes
OTA_FW_VERSION_RSP_OPCODE = 0xFF05

# ── Config entry keys ────────────────────────────────────────────────────────
CONF_TANK_TYPE = "tank_type"
CONF_TANK_HEIGHT_MM = "tank_height_mm"   # only used when CONF_TANK_TYPE == CUSTOM_TANK_KEY

CUSTOM_TANK_KEY = "custom"

# Calibrated fill-height range per standard tank (mm).
# EchoCheck firmware reports field_c in 0.1 mm units; dividing by 10 gives
# fill depth in mm.  30 lb is confirmed via Mopeka cross-validation
# (field_c=0x0841→211.3 mm at ~83% fill → calibrated max ≈ 254 mm).
# Other sizes are approximate, derived from the same ~0.667 ratio to Mopeka.
# key → (display_name, calibrated_height_mm)
TANK_SPECS: dict[str, tuple[str, float]] = {
    "20lb_v":  ("20 lb Vertical (approx)",  169.0),
    "30lb_v":  ("30 lb Vertical",           254.0),   # confirmed
    "40lb_v":  ("40 lb Vertical (approx)",  338.0),
    "100lb_v": ("100 lb Vertical (approx)", 542.0),
    CUSTOM_TANK_KEY: ("Custom",             254.0),   # user-specified via custom_height step
}

# ── Timing ───────────────────────────────────────────────────────────────────
# Sensor auto-notifies every ~1 s once connected.
DATA_HEALTH_TIMEOUT_SECONDS = 120
OFFLINE_TIMEOUT_SECONDS = 10 * 60  # attempt reconnect after 10 min silence

# ── Notification format ──────────────────────────────────────────────────────
# FFF1 notification: 20-byte ASCII  "M:AAAA_BBBB@CCCC_DDD"
#   AAAA = most-recent raw echo (0.1 mm units, noisy)
#   BBBB = previous raw echo (0.1 mm units, noisy)
#   CCCC = filtered/settled echo (0.1 mm units, stable) — used for tank level
    #   DDD  = internal quality/SNR metric (observed 16-20; correlates with measurement cycle,
    #          not ambient temperature; not exposed by official app)
NOTIF_PREFIX = "M:"
NOTIF_LEN = 20
