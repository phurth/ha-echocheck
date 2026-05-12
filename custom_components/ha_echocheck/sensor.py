"""Sensor entities for EchoCheck BLE tank sensor."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_ADDRESS,
    EntityCategory,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EchoCheckCoordinator
from .model import EchoCheckSensorData


@dataclass(frozen=True, kw_only=True)
class EchoCheckSensorDescription(SensorEntityDescription):
    value_fn: Callable[[EchoCheckSensorData], float | int | str | None]


SENSOR_DESCRIPTIONS: tuple[EchoCheckSensorDescription, ...] = (
    EchoCheckSensorDescription(
        key="tank_level",
        name="Tank Level",
        native_unit_of_measurement="%",
        icon="mdi:gauge",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.tank_level_percent,
    ),
    EchoCheckSensorDescription(
        key="battery",
        name="Battery",
        native_unit_of_measurement="%",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.battery_percent,
    ),
    EchoCheckSensorDescription(
        key="firmware_version",
        name="Firmware Version",
        icon="mdi:tag",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.firmware_version,
    ),
    EchoCheckSensorDescription(
        key="rssi",
        name="Signal Strength",
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.rssi,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EchoCheckCoordinator = hass.data[DOMAIN][entry.entry_id]
    address = entry.data[CONF_ADDRESS]
    async_add_entities(
        EchoCheckSensor(coordinator, address, entry.title, desc)
        for desc in SENSOR_DESCRIPTIONS
    )


class EchoCheckSensor(CoordinatorEntity[EchoCheckCoordinator], SensorEntity):
    """EchoCheck sensor entity."""

    entity_description: EchoCheckSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EchoCheckCoordinator,
        address: str,
        device_name: str,
        description: EchoCheckSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        mac = address.replace(":", "").lower()
        self._attr_unique_id = f"{mac}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=device_name,
            manufacturer="EchoCheck / Thincke",
            model="EchoCheck Tank Sensor",
            connections={("bluetooth", address)},
        )

    @property
    def available(self) -> bool:
        return self.coordinator.available and self.coordinator.data is not None

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
