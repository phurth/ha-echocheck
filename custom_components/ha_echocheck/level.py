"""Tank level calculation for EchoCheck sensors.

The sensor reports the round-trip flight time of an ultrasonic pulse between
the tank floor and the liquid surface, in microseconds, with no temperature
compensation of its own.  Turning that into a level therefore takes two steps:

    depth_mm = raw_us * c(T) / 2000
    level_%  = depth_mm / fill_height_mm * 100

where c(T) is the speed of sound in liquid propane at the tank's temperature
and fill_height_mm is the depth of liquid a full tank of that size holds.

Both matter.  Without the temperature term the same undisturbed tank appears to
gain or lose roughly half a percent of level per degree, which is the drift
seen in the field; and the fill height is not the cylinder's overall height —
a 30 lb bottle stands about 610 mm tall but holds ~381 mm of liquid when full.
"""

from __future__ import annotations

from .const import (
    DEFAULT_ASSUMED_TEMP_C,
    PROPANE_SOUND_SPEED_0C,
    PROPANE_SOUND_SPEED_SLOPE,
)


def speed_of_sound_mps(temp_c: float | None) -> float:
    """Speed of sound in saturated liquid propane at *temp_c*, in m/s."""
    if temp_c is None:
        temp_c = DEFAULT_ASSUMED_TEMP_C
    return PROPANE_SOUND_SPEED_0C + PROPANE_SOUND_SPEED_SLOPE * temp_c


def depth_mm_from_raw(raw_us: int | float, temp_c: float | None) -> float:
    """Convert a round-trip flight time in microseconds to a liquid depth."""
    if raw_us <= 0:
        return 0.0
    return raw_us * speed_of_sound_mps(temp_c) / 2000.0


def tank_level_from_raw(
    raw_us: int | float,
    fill_height_mm: float | None,
    temp_c: float | None = None,
) -> float | None:
    """Return tank level as a percentage, or None if it cannot be computed.

    A reading of zero is a genuine empty tank rather than a missing value: the
    sensor reports 0 when there is no liquid echo above it, confirmed against
    an empty cylinder.
    """
    if fill_height_mm is None or fill_height_mm <= 0:
        return None
    if raw_us < 0:
        return None
    depth = depth_mm_from_raw(raw_us, temp_c)
    return round(min(100.0, max(0.0, depth / fill_height_mm * 100.0)), 1)
