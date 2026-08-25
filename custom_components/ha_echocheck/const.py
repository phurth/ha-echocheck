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
# Increments on every advertisement; a repeat means the Bluetooth stack replayed
# a packet we have already seen, which must not be mistaken for a live sensor.
MANUF_COUNTER_OFFSET = 0
MANUF_COUNTER_LEN = 2
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

CUSTOM_TANK_KEY = "custom"

# Entity supplying the tank's ambient temperature.  Optional: without it the
# integration falls back to DEFAULT_ASSUMED_TEMP_C.
CONF_TEMP_ENTITY = "temperature_entity"

# ── Acoustic model ───────────────────────────────────────────────────────────
# The sensor reports the ROUND-TRIP flight time of an ultrasonic pulse from the
# tank floor to the liquid surface and back, in microseconds.  It applies no
# temperature compensation of its own — there is no temperature field anywhere
# in its advertisement, and its raw value tracks the speed of sound rather than
# the liquid depth.
#
#   depth_mm = raw_us * c(T) / 2000        (c in m/s, hence the 2000)
#
# Confirmed on a 30 lb cylinder: full reads ~715, empty reads 0, and the
# implied speed of sound at 15.6 °C is ~890 m/s — which is liquid propane.
# Reading the value as millimetres instead would put 715 mm of liquid inside a
# bottle whose interior column is ~410 mm.
#
# Speed of sound in saturated liquid propane falls roughly linearly with
# temperature across the range these tanks live in (about 960 m/s at 0 °C,
# dropping ~4.4 m/s per °C).  Uncompensated, a full tank appears to gain or
# lose ~0.5 % of level per °C.
PROPANE_SOUND_SPEED_0C = 960.0      # m/s
PROPANE_SOUND_SPEED_SLOPE = -4.4    # m/s per °C
DEFAULT_ASSUMED_TEMP_C = 15.0       # used when no temperature entity is set

# ── Tank fill heights (mm) ───────────────────────────────────────────────────
# Depth of liquid at which a tank reads 100 %.  These are the empirically
# calibrated ranges Mopeka uses for the same cylinders (10 / 15 / 20 / 32 inch
# fill depths), which is the same quantity we need here.  They are NOT the
# cylinder's overall height: a 30 lb bottle stands ~610 mm tall but holds
# ~381 mm of liquid when full.
# key → (display_name, fill_height_mm)
TANK_SPECS: dict[str, tuple[str, float]] = {
    "20lb_v":     ("20 lb Vertical",     254.0),
    "30lb_v":     ("30 lb Vertical",     381.0),
    "40lb_v":     ("40 lb Vertical",     508.0),
    "100lb_v":    ("100 lb Vertical",    812.8),
    "120gal_v":   ("120 gal Vertical",   974.0),
    "europe_6kg":  ("6 kg Vertical (EU)",  340.0),
    "europe_11kg": ("11 kg Vertical (EU)", 390.0),
    "europe_14kg": ("14 kg Vertical (EU)", 430.0),
    CUSTOM_TANK_KEY: ("Custom", 381.0),
}

# ── Timing ───────────────────────────────────────────────────────────────────
DATA_HEALTH_TIMEOUT_SECONDS = 120
OFFLINE_TIMEOUT_SECONDS = 10 * 60

# ── Notification format (legacy firmware; retained for future-proofing) ──────
NOTIF_PREFIX = "M:"
NOTIF_LEN = 20
