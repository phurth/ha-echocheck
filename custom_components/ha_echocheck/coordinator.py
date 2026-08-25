"""Passive BLE coordinator for EchoCheck tank sensors.

These sensors broadcast everything they have — liquid measurement, battery —
in their manufacturer advertisement, so the integration never connects.  That
is not just a simplification:

* Holding a GATT connection makes the sensor **stop advertising entirely**,
  so connecting trades one data source for another rather than adding one, and
  hides the sensor from every other consumer including the vendor app.
* A connection occupies one of an adapter's handful of slots, permanently, per
  sensor.
* Current firmware never emits the FFF1 ``M:`` notification that a connection
  would be for, so on those devices a connection yields nothing at all.

Updates are push-driven: Home Assistant delivers each advertisement as it
arrives, which also makes availability meaningful — the coordinator only marks
data fresh when a real advertisement was seen, never on a cached one.
"""

from __future__ import annotations

from collections import deque
import logging
import time

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothChange,
    BluetoothServiceInfoBleak,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_TANK_HEIGHT_MM,
    CONF_TANK_TYPE,
    CONF_TEMP_ENTITY,
    CUSTOM_TANK_KEY,
    DATA_HEALTH_TIMEOUT_SECONDS,
    ECHOCHECK_MANUFACTURER_ID,
    MANUF_BATTERY_OFFSET,
    MANUF_COUNTER_LEN,
    MANUF_COUNTER_OFFSET,
    MANUF_LENGTH,
    MANUF_LEVEL_LEN,
    MANUF_LEVEL_OFFSET,
    OFFLINE_TIMEOUT_SECONDS,
    TANK_SPECS,
)
from .level import depth_mm_from_raw, speed_of_sound_mps, tank_level_from_raw
from .model import EchoCheckSensorData

_LOGGER = logging.getLogger(__name__)

# Median window for the raw measurement.  The ultrasonic reading intermittently
# returns a false echo — a full 30 lb cylinder reading ~745 will occasionally
# report ~192 — so a single sample cannot be trusted.  A median rejects those
# spikes outright while still tracking a genuine fill within a couple of
# minutes, which is far faster than a propane tank actually changes.
_LEVEL_SMOOTH_WINDOW = 5


class EchoCheckCoordinator(DataUpdateCoordinator[EchoCheckSensorData | None]):
    """Builds sensor state from EchoCheck advertisements."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"EchoCheck {entry.data[CONF_ADDRESS]}",
            update_interval=None,  # push-driven; advertisements arrive on their own
        )
        self.entry = entry
        self.address: str = entry.data[CONF_ADDRESS]
        self._last_seen_monotonic: float | None = None
        self._battery_percent: int | None = None
        self._level_samples: deque[int] = deque(maxlen=_LEVEL_SMOOTH_WINDOW)
        self._last_counter: bytes | None = None
        self._unregister: callable | None = None
        self.reload_from_entry(entry)

    def reload_from_entry(self, entry: ConfigEntry) -> None:
        """Apply tank size and temperature-source options."""
        self.entry = entry
        self._temp_entity_id: str | None = entry.options.get(
            CONF_TEMP_ENTITY, entry.data.get(CONF_TEMP_ENTITY)
        ) or None
        self._level_samples.clear()
        tank_type = entry.options.get(CONF_TANK_TYPE, entry.data.get(CONF_TANK_TYPE))
        if tank_type is not None and tank_type != CUSTOM_TANK_KEY:
            self.tank_height_mm: float | None = TANK_SPECS[tank_type][1]
        else:
            raw_height = entry.options.get(
                CONF_TANK_HEIGHT_MM, entry.data.get(CONF_TANK_HEIGHT_MM)
            )
            self.tank_height_mm = float(raw_height) if raw_height is not None else None
        _LOGGER.info(
            "EchoCheck %s: fill_height=%smm temp_entity=%s",
            self.address,
            self.tank_height_mm,
            self._temp_entity_id or "(assumed default)",
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_start(self) -> None:
        """Subscribe to this sensor's advertisements."""
        self._unregister = bluetooth.async_register_callback(
            self.hass,
            self._async_on_advertisement,
            {"address": self.address, "connectable": False},
            bluetooth.BluetoothScanningMode.PASSIVE,
        )
        # Seed from whatever the stack already holds so entities populate
        # immediately rather than waiting for the next advertisement.
        cached = bluetooth.async_last_service_info(
            self.hass, self.address, connectable=False
        )
        if cached is not None:
            self._process(cached, seeded=True)

    async def async_stop(self) -> None:
        """Unsubscribe."""
        if self._unregister is not None:
            self._unregister()
            self._unregister = None

    # ── Advertisement handling ────────────────────────────────────────────────

    @callback
    def _async_on_advertisement(
        self, service_info: BluetoothServiceInfoBleak, change: BluetoothChange
    ) -> None:
        self._process(service_info)

    def _process(self, info: BluetoothServiceInfoBleak, seeded: bool = False) -> None:
        payload = info.manufacturer_data.get(ECHOCHECK_MANUFACTURER_ID)
        if not payload or len(payload) < MANUF_LENGTH:
            return
        payload = bytes(payload)

        # Each advertisement carries an incrementing counter.  A repeat means
        # the stack handed back a packet we have already accounted for, which
        # must not count as the sensor still being alive.
        counter = payload[
            MANUF_COUNTER_OFFSET:MANUF_COUNTER_OFFSET + MANUF_COUNTER_LEN
        ]
        is_fresh = counter != self._last_counter
        self._last_counter = counter

        battery = int(payload[MANUF_BATTERY_OFFSET])
        raw_us = int.from_bytes(
            payload[MANUF_LEVEL_OFFSET:MANUF_LEVEL_OFFSET + MANUF_LEVEL_LEN], "big"
        )
        if is_fresh:
            self._level_samples.append(raw_us)
        smoothed = self._median_level()
        temp_c = self.current_temp_c()
        level_percent = tank_level_from_raw(smoothed, self.tank_height_mm, temp_c)

        if is_fresh or seeded:
            self._battery_percent = battery
            if not seeded:
                self._last_seen_monotonic = time.monotonic()
            _LOGGER.debug(
                "EchoCheck %s: raw=%dus median=%.0fus window=%s temp=%s c=%.0fm/s "
                "depth=%.0fmm of %smm -> %s%% batt=%d%% rssi=%s",
                self.address, raw_us, smoothed, list(self._level_samples),
                f"{temp_c:.1f}C" if temp_c is not None else "assumed",
                speed_of_sound_mps(temp_c),
                depth_mm_from_raw(smoothed, temp_c),
                self.tank_height_mm, level_percent, battery, info.rssi,
            )

        self.async_set_updated_data(
            EchoCheckSensorData(
                mac_address=self.address,
                raw_us=raw_us,
                median_us=smoothed,
                tank_level_percent=level_percent,
                battery_percent=self._battery_percent,
                rssi=info.rssi,
            )
        )

    def _median_level(self) -> float:
        """Median of the recent window, or the latest sample while warming up."""
        samples = sorted(self._level_samples)
        if not samples:
            return 0.0
        mid = len(samples) // 2
        if len(samples) % 2:
            return float(samples[mid])
        return (samples[mid - 1] + samples[mid]) / 2.0

    # ── Temperature source ────────────────────────────────────────────────────

    def current_temp_c(self) -> float | None:
        """Temperature at the tank in °C from the configured entity, or None.

        The sensor reports flight time and compensates for nothing, so this is
        what keeps a level steady as the tank warms through the day.  Returns
        None when unset or unavailable, and the level model then assumes a
        default rather than failing.
        """
        if not self._temp_entity_id:
            return None
        state = self.hass.states.get(self._temp_entity_id)
        if state is None or state.state in ("unknown", "unavailable", ""):
            return None
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return None
        unit = state.attributes.get("unit_of_measurement")
        if unit == "°F":
            return (value - 32.0) * 5.0 / 9.0
        if unit == "K":
            return value - 273.15
        return value

    # ── Health ────────────────────────────────────────────────────────────────

    @property
    def data_healthy(self) -> bool:
        """True when a fresh advertisement arrived recently."""
        if self._last_seen_monotonic is None:
            return False
        return (time.monotonic() - self._last_seen_monotonic) < DATA_HEALTH_TIMEOUT_SECONDS

    @property
    def available(self) -> bool:
        if self._last_seen_monotonic is None:
            return False
        return (time.monotonic() - self._last_seen_monotonic) < OFFLINE_TIMEOUT_SECONDS

    @property
    def last_seen_age(self) -> float | None:
        if self._last_seen_monotonic is None:
            return None
        return time.monotonic() - self._last_seen_monotonic

    async def _async_update_data(self) -> EchoCheckSensorData | None:
        """Unused: updates are pushed from advertisements."""
        return self.data
