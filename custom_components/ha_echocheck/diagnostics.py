"""Diagnostics for EchoCheck integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import EchoCheckCoordinator

TO_REDACT = {CONF_ADDRESS}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics data for EchoCheck config entry."""
    coordinator: EchoCheckCoordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data
    return {
        "config_entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "runtime_config": {
            "address": async_redact_data({"address": coordinator.address}, TO_REDACT),
            "tank_height_mm": coordinator.tank_height_mm,
            "connected": coordinator._client is not None and coordinator._client.is_connected,
        },
        "availability": {
            "available": coordinator.available,
            "data_healthy": coordinator.data_healthy,
            "last_seen_age_seconds": coordinator.last_seen_age,
        },
        "last_data": {
            "raw_us": data.raw_us if data else None,
            "median_us": data.median_us if data else None,
            "tank_level_percent": data.tank_level_percent if data else None,
            "battery_percent": data.battery_percent if data else None,
            "rssi": data.rssi if data else None,
            "timestamp": data.timestamp if data else None,
        },
    }
