"""EchoCheck data model."""

from __future__ import annotations

from dataclasses import dataclass
import time


@dataclass(slots=True)
class EchoCheckSensorData:
    """Parsed data from an EchoCheck FFF1 notification.

    Field meanings for field_a / field_b / field_c are preliminary — a live
    on-tank capture is required to confirm which field maps to echo distance,
    which to battery, and which (if any) carries a secondary measurement.
    """

    mac_address: str
    # Raw hex fields from the notification "M:AAAA_BBBB@CCCC_DDD"
    field_a: int       # most-recent raw echo measurement (0.1 mm units, noisy)
    field_b: int       # previous raw echo measurement (0.1 mm units, noisy)
    field_c: int       # filtered/settled echo measurement (0.1 mm units, stable)
    # DDD suffix — 3-char hex integer; semantics unconfirmed.
    # Observed 16-20 on-tank (oscillates with ~9s measurement cycle), 16 off-tank.
    # Not exposed by official app. Likely internal signal quality or SNR metric.
    ddd_raw: int
    # Derived / computed values
    tank_level_percent: float | None = None   # field_c / 10mm / tank_height * 100
    battery_percent: int | None = None        # from BLE Battery Service char 0x2A19 (0-100)
    rssi: int | None = None
    timestamp: float = 0.0
    firmware_version: str | None = None       # from Telink version char 0x0000ffd4

    def __post_init__(self) -> None:
        if self.timestamp == 0.0:
            self.timestamp = time.time()
