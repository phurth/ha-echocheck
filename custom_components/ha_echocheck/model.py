"""EchoCheck data model."""

from __future__ import annotations

from dataclasses import dataclass
import time


@dataclass
class EchoCheckSensorData:
    """One sensor reading, built from a single BLE advertisement.

    raw_us is the round-trip ultrasonic flight time the sensor broadcasts;
    median_us is that value after the false-echo filter, and is what the level
    percentage is derived from.
    """

    mac_address: str
    raw_us: int = 0
    median_us: float = 0.0
    tank_level_percent: float | None = None
    battery_percent: int | None = None
    rssi: int | None = None
