"""Parser for EchoCheck FFF1 GATT notifications."""

from __future__ import annotations

import logging

from .const import NOTIF_LEN, NOTIF_PREFIX
from .model import EchoCheckSensorData

_LOGGER = logging.getLogger(__name__)


def parse_echocheck_notification(
    mac_address: str,
    payload: bytes | bytearray,
    rssi: int | None = None,
    tank_height_mm: float | None = None,
    battery_percent: int | None = None,
    firmware_version: str | None = None,
) -> EchoCheckSensorData | None:
    """Parse a raw FFF1 GATT notification into an EchoCheckSensorData.

    Notification format (20 bytes, ASCII):
        M:AAAA_BBBB@CCCC_DDD
          ────────────────────
          field_a (4 hex): most-recent raw echo measurement, in 0.1 mm units.
                           Two consecutive raw samples alternate between field_a
                           and field_b each notification.
          field_b (4 hex): previous raw echo measurement, same units as field_a.
          field_c (4 hex): filtered/settled echo measurement (lowest variance).
                           This is the value used to compute tank level.
                           Units: 0.1 mm  →  field_c / 10 = distance in mm.
          DDD (3 chars):   3-character hex value whose exact semantics are not
                           yet confirmed.  Observed to be independent of on/off-
                           tank state.  Likely temperature (°C) or signal quality.
                           NOT firmware version (changes every ~9 s on-tank).

    All fields are 0x0000 / "000" when the sensor has no valid echo (off-tank).

    Battery level is NOT encoded in this notification; it is returned via
    handle 0x000B on a separate command/response exchange initiated by the app.
    Our coordinator does not yet issue that query, so battery_percent is None.

    Returns None if the payload does not match the expected format.
    """
    try:
        text = payload.decode("ascii")
    except (UnicodeDecodeError, AttributeError):
        _LOGGER.debug("EchoCheck: non-ASCII notification payload from %s: %s", mac_address, payload.hex())
        return None

    if len(text) != NOTIF_LEN or not text.startswith(NOTIF_PREFIX):
        _LOGGER.debug("EchoCheck: unexpected notification format from %s: %r", mac_address, text)
        return None

    # Format: "M:AAAA_BBBB@CCCC_DDD"
    #          01234567890123456789
    try:
        field_a = int(text[2:6], 16)
        # text[6] == '_'
        field_b = int(text[7:11], 16)
        # text[11] == '@'
        field_c = int(text[12:16], 16)
        # text[16] == '_'
        ddd_raw = int(text[17:20], 16)   # internal quality/SNR metric; semantics unconfirmed
    except (ValueError, IndexError):
        _LOGGER.debug("EchoCheck: failed to parse notification from %s: %r", mac_address, text)
        return None

    # ── Tank level ─────────────────────────────────────────────────────────────
    # field_c is in units of 0.1 mm.  The sensor mounts on the bottom of the
    # tank and measures the liquid fill height upward from its mounting point.
    # Divide by 10 to get mm, then express as a percentage of the configured
    # tank height.
    tank_level_percent: float | None = None
    if field_c > 0 and tank_height_mm is not None and tank_height_mm > 0:
        distance_mm = field_c / 10.0
        tank_level_percent = min(100.0, max(0.0, (distance_mm / tank_height_mm) * 100.0))

    return EchoCheckSensorData(
        mac_address=mac_address,
        field_a=field_a,
        field_b=field_b,
        field_c=field_c,
        ddd_raw=ddd_raw,
        tank_level_percent=tank_level_percent,
        battery_percent=battery_percent,
        firmware_version=firmware_version,
        rssi=rssi,
    )
