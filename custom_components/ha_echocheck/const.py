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
BATTERY_CHAR_UUID = "00002a19-0000-1000-8000-00805f9b34fb"

# Telink firmware version characteristic (not present on current hardware)
VERSION_SERVICE_UUID = "0000d0ff-3c17-d293-8e48-14fe2e4da212"
VERSION_CHAR_UUID = "0000ffd4-0000-1000-8000-00805f9b34fb"

# ── Device identification ────────────────────────────────────────────────────
ECHOCHECK_NAME_PREFIX = "@TNK"
ECHOCHECK_MANUFACTURER_ID = 0x4E54

# ── Manufacturer-data layout (26-byte payload after company ID) ─────────────
#   [0:2]   advertisement counter (increments each packet)
#   [2:4]   0x4E54 company-ID echo
#   [4:6]   tank level = liquid height in MILLIMETRES, 16-bit BIG-ENDIAN.
#           This is the settled ultrasonic echo; it is authenticated by being
#           echoed inside the AES identity block (decrypted bytes [2:4]).
#           percent = level_mm / tank_height_mm * 100.
#   [6]     battery percent (cleartext, 0-100)
#   [7]     reserved
#   [8]     constant
#   [9:25]  16-byte AES-128-ECB identity block.  Decrypted layout:
#           [0:2]  company-ID echo (0x4E54)
#           [2:4]  level-mm echo (== manuf[4:6])
#           [4]    battery (== manuf[6])
#           [5:7]  reserved
#           [7]    firmware type code (04 = "21-4")
#           [8]    0x21 protocol constant
#           [9:15] real MAC address
#           [15]   XOR checksum of bytes [0:15]
#   [25]    varies with battery/status changes; NOT the level.
MANUF_LENGTH = 26
MANUF_BATTERY_OFFSET = 6
MANUF_LEVEL_OFFSET = 4
MANUF_LEVEL_LEN = 2
MANUF_IDENTITY_OFFSET = 9
MANUF_IDENTITY_LEN = 16

# ── Firmware version (via OTA characteristic) ───────────────────────────────
#   write OTA_FW_VERSION_REQ → notify 0xFF05 → bytes [2:5] = version
#   little-endian: bytes[4].bytes[3].bytes[2] = major.minor.patch
#   Confirmed: response 05 ff 00 00 01 → "1.0.0"
OTA_FW_VERSION_REQ = b'\x04\xff\x00\x00\x00'
OTA_FW_VERSION_RSP_OPCODE = 0xFF05

# ── Config entry keys ────────────────────────────────────────────────────────
CONF_TANK_TYPE = "tank_type"
CONF_TANK_HEIGHT_MM = "tank_height_mm"
# AES-128-ECB key for identity verification (optional, user-provided via
# Options). Not required for battery/level (both are cleartext); it only
# enables MAC/battery/checksum verification of the identity block.
CONF_ENCRYPTION_KEY = "encryption_key"

CUSTOM_TANK_KEY = "custom"

# Calibrated fill-height range per standard tank (mm).
# key → (display_name, calibrated_height_mm)
TANK_SPECS: dict[str, tuple[str, float]] = {
    "20gal_v": ("20 gal Vertical", 765.0),
    "20lb_v":  ("20 lb Vertical",  378.0),
    "30lb_v":  ("30 lb Vertical",  610.0),
    "40lb_v":  ("40 lb Vertical",  737.0),
    "100lb_v": ("100 lb Vertical", 1220.0),
    CUSTOM_TANK_KEY: ("Custom",    765.0),
}

# ── Timing ───────────────────────────────────────────────────────────────────
DATA_HEALTH_TIMEOUT_SECONDS = 120
OFFLINE_TIMEOUT_SECONDS = 10 * 60

# ── Notification format (legacy firmware; retained for future-proofing) ──────
NOTIF_PREFIX = "M:"
NOTIF_LEN = 20
