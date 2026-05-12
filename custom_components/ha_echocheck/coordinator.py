"""Active GATT coordinator for EchoCheck tank sensors."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import time

from bleak import BleakClient, BleakError
from bleak_retry_connector import establish_connection

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_TANK_HEIGHT_MM,
    CONF_TANK_TYPE,
    CUSTOM_TANK_KEY,
    DATA_HEALTH_TIMEOUT_SECONDS,
    DOMAIN,
    ECHOCHECK_MANUFACTURER_ID,
    MANUF_BATTERY_OFFSET,
    NOTIFY_CHAR_UUID,
    OFFLINE_TIMEOUT_SECONDS,
    OTA_CHAR_UUID,
    OTA_FW_VERSION_REQ,
    OTA_FW_VERSION_RSP_OPCODE,
    TANK_SPECS,
)
from .model import EchoCheckSensorData
from .parser import parse_echocheck_notification

_LOGGER = logging.getLogger(__name__)

# How long to wait after a disconnection before attempting to reconnect.
_RECONNECT_DELAY_S = 10
# Reconnect polling interval (used by DataUpdateCoordinator as the heartbeat).
_POLL_INTERVAL = timedelta(seconds=30)


class EchoCheckCoordinator(DataUpdateCoordinator[EchoCheckSensorData | None]):
    """Coordinator that maintains an active GATT connection to an EchoCheck sensor.

    The EchoCheck sensor begins sending FFF1 notifications immediately after
    connection — no CCCD write is required (observed in HCI capture).  The
    coordinator subscribes to notifications and pushes updates to HA entities.

    The DataUpdateCoordinator update_interval acts as a reconnect heartbeat:
    if the connection is lost, _async_update_data() re-establishes it.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"EchoCheck {entry.data[CONF_ADDRESS]}",
            update_interval=_POLL_INTERVAL,
        )
        self.entry = entry
        self.address: str = entry.data[CONF_ADDRESS]
        # Resolve tank height: from TANK_SPECS for standard types, or stored mm for custom.
        # Falls back to reading CONF_TANK_HEIGHT_MM directly for old entries that pre-date
        # the tank-type dropdown (migration path).
        tank_type = entry.options.get(CONF_TANK_TYPE, entry.data.get(CONF_TANK_TYPE))
        if tank_type is not None and tank_type != CUSTOM_TANK_KEY:
            self.tank_height_mm: float | None = TANK_SPECS[tank_type][1]
        else:
            raw_height = entry.options.get(CONF_TANK_HEIGHT_MM, entry.data.get(CONF_TANK_HEIGHT_MM))
            self.tank_height_mm = float(raw_height) if raw_height is not None else None
        self._client: BleakClient | None = None
        self._last_seen_monotonic: float | None = None
        self._battery_percent: int | None = None
        self._firmware_version: str | None = None
        self._fw_event: asyncio.Event = asyncio.Event()
        _LOGGER.info(
            "EchoCheck coordinator init: address=%s tank_height_mm=%s",
            self.address,
            self.tank_height_mm,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    async def async_start(self) -> None:
        """Attempt initial connection and start the heartbeat poll."""
        await self._async_connect()

    async def async_stop(self) -> None:
        """Disconnect and clean up."""
        await self._async_disconnect()

    @property
    def data_healthy(self) -> bool:
        """True when a notification was received recently."""
        if self._last_seen_monotonic is None:
            return False
        return (time.monotonic() - self._last_seen_monotonic) < DATA_HEALTH_TIMEOUT_SECONDS

    @property
    def available(self) -> bool:
        """True while the sensor is reachable (not stale/offline)."""
        if self._last_seen_monotonic is None:
            return False
        return (time.monotonic() - self._last_seen_monotonic) < OFFLINE_TIMEOUT_SECONDS

    @property
    def last_seen_age(self) -> float | None:
        """Seconds since last notification, or None if never received."""
        if self._last_seen_monotonic is None:
            return None
        return time.monotonic() - self._last_seen_monotonic

    # ── DataUpdateCoordinator heartbeat ──────────────────────────────────────

    async def _async_update_data(self) -> EchoCheckSensorData | None:
        """Called on poll_interval.  Reconnects if the client is gone."""
        if self._client is None or not self._client.is_connected:
            _LOGGER.debug("EchoCheck %s: not connected, attempting reconnect", self.address)
            await self._async_connect()
        return self.data  # data is updated via notification callback

    # ── Connection management ─────────────────────────────────────────────────

    async def _async_connect(self) -> None:
        """Resolve the BLE device and open a GATT connection."""
        ble_device = async_ble_device_from_address(self.hass, self.address, connectable=True)
        if ble_device is None:
            _LOGGER.debug("EchoCheck %s: device not in BLE cache, waiting for advertisement", self.address)
            return

        try:
            client = await establish_connection(
                BleakClient,
                ble_device,
                self.address,
                disconnected_callback=self._on_disconnected,
            )
        except (BleakError, TimeoutError, OSError) as err:
            _LOGGER.warning("EchoCheck %s: connection failed: %s", self.address, err)
            return

        _LOGGER.info("EchoCheck %s: connected, subscribing to FFF1 notifications", self.address)
        self._client = client

        try:
            await client.start_notify(NOTIFY_CHAR_UUID, self._on_notification)
        except BleakError as err:
            _LOGGER.warning("EchoCheck %s: start_notify failed: %s", self.address, err)
            await self._async_disconnect()
            return

        # Firmware version: subscribe to OTA char, send version request (0xFF04),
        # wait for 0xFF05 notification.  Confirmed from HCI capture.
        try:
            self._fw_event.clear()
            await client.start_notify(OTA_CHAR_UUID, self._on_ota_notification)
            await client.write_gatt_char(OTA_CHAR_UUID, OTA_FW_VERSION_REQ, response=False)
            await asyncio.wait_for(self._fw_event.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            _LOGGER.warning("EchoCheck %s: firmware version request timed out", self.address)
        except (BleakError, OSError) as err:
            _LOGGER.warning("EchoCheck %s: firmware version exchange failed: %s", self.address, err)

    async def _async_disconnect(self) -> None:
        """Cleanly disconnect from the sensor."""
        client = self._client
        self._client = None
        if client is not None and client.is_connected:
            try:
                await client.disconnect()
            except BleakError:
                pass
        _LOGGER.debug("EchoCheck %s: disconnected", self.address)

    @callback
    def _on_disconnected(self, client: BleakClient) -> None:
        """BleakClient disconnected callback (called from Bleak's event loop)."""
        _LOGGER.info("EchoCheck %s: unexpectedly disconnected", self.address)
        self._client = None
        # The next heartbeat poll will trigger reconnect.

    # ── OTA notification handler (firmware version) ───────────────────────────

    @callback
    def _on_ota_notification(self, _handle: int, data: bytearray) -> None:
        """Handle OTA characteristic notifications (firmware version response)."""
        if len(data) >= 5 and data[0] == (OTA_FW_VERSION_RSP_OPCODE & 0xFF) and data[1] == (OTA_FW_VERSION_RSP_OPCODE >> 8):
            # Version bytes [2:5] are little-endian: [patch, minor, major]
            major, minor, patch = data[4], data[3], data[2]
            self._firmware_version = f"{major}.{minor}.{patch}"
            _LOGGER.info("EchoCheck %s: firmware=%s", self.address, self._firmware_version)
            self._fw_event.set()

    # ── Notification handler ──────────────────────────────────────────────────

    @callback
    def _on_notification(self, _handle: int, data: bytearray) -> None:
        """Handle an incoming FFF1 notification."""
        rssi: int | None = None
        # Retrieve RSSI and battery level from the BLE advertisement cache.
        # Battery is broadcast in every advertisement at manufacturer data byte[6].
        cached: BluetoothServiceInfoBleak | None = bluetooth.async_last_service_info(
            self.hass, self.address, connectable=True
        )
        if cached is not None:
            rssi = cached.rssi
            manuf = cached.advertisement.manufacturer_data.get(ECHOCHECK_MANUFACTURER_ID)
            if manuf and len(manuf) > MANUF_BATTERY_OFFSET:
                self._battery_percent = int(manuf[MANUF_BATTERY_OFFSET])

        parsed = parse_echocheck_notification(
            mac_address=self.address,
            payload=data,
            rssi=rssi,
            tank_height_mm=self.tank_height_mm,
            battery_percent=self._battery_percent,
            firmware_version=self._firmware_version,
        )
        if parsed is None:
            return

        self._last_seen_monotonic = time.monotonic()
        _LOGGER.info(
            "EchoCheck %s: raw=%r a=%04X b=%04X c=%04X(%.1fmm) quality=%d tank=%.1f%% bat=%s%% rssi=%s",
            self.address,
            data.decode("ascii", errors="replace"),
            parsed.field_a,
            parsed.field_b,
            parsed.field_c,
            parsed.field_c / 10.0,
            parsed.ddd_raw,
            parsed.tank_level_percent if parsed.tank_level_percent is not None else -1.0,
            parsed.battery_percent if parsed.battery_percent is not None else "?",
            rssi,
        )
        self.async_set_updated_data(parsed)
