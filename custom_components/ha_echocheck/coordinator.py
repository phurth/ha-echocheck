"""EchoCheck coordinator: active GATT (legacy) or passive advertisement.

The coordinator runs in one of two modes, selected by whether the user has
supplied an AES-128-ECB key via Options:

* **No key** (default) — legacy active-GATT mode.  The sensor is expected to
  emit ASCII ``M:AAAA_BBBB@CCCC_DDD`` FFF1 notifications once connected; the
  coordinator subscribes and parses ``field_c`` (settled echo, 0.1 mm) to
  compute the level.  This preserves the original integration behaviour for
  firmware variants that do emit those notifications.

* **With key** — passive advertisement mode.  Current GCI03 firmware never
  emits the ``M:`` notification, so instead each poll reads the cached BLE
  advertisement and recovers battery (manuf[6]) and tank level (manuf[4:6],
  16-bit big-endian millimetres).  The key decrypts the identity block
  (manuf[9:25]) to verify the device and derive the firmware version
  (``21-{type}``, matching the official app).

The key is user-provided and never shipped in source.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import timedelta
import logging
import re
import time

from bleak import BleakClient, BleakError
from bleak_retry_connector import establish_connection
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_ENCRYPTION_KEY,
    CONF_TANK_HEIGHT_MM,
    CONF_TANK_TYPE,
    CUSTOM_TANK_KEY,
    DATA_HEALTH_TIMEOUT_SECONDS,
    ECHOCHECK_MANUFACTURER_ID,
    MANUF_BATTERY_OFFSET,
    MANUF_IDENTITY_LEN,
    MANUF_IDENTITY_OFFSET,
    MANUF_LEVEL_LEN,
    MANUF_LEVEL_OFFSET,
    MANUF_LENGTH,
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

# DataUpdateCoordinator poll interval doubles as the reconnect heartbeat for
# active mode and the advertisement poll for passive mode.
_POLL_INTERVAL = timedelta(seconds=15)

# Passive mode median-filter window for the raw level.  At a 15s poll this is
# ~75s of history, which rejects single false-echo spikes (they jump to 100%)
# while still tracking real fills within the official app's ~30s-2min settle.
_LEVEL_SMOOTH_WINDOW = 5

# GCI03 tank-firmware major version (the "21" in "21-4").  The minor version is
# carried in the decrypted identity block byte [7] (04 = V21_04).
_FW_MAJOR = 21

_HEX_KEY_RE = re.compile(r"[0-9a-fA-F]{32}")


def _parse_hex_key(raw: str | None) -> bytes | None:
    """Normalize a user-supplied key to 16 bytes, or None if absent/invalid."""
    if not raw:
        return None
    cleaned = raw.strip().replace(":", "").replace(" ", "")
    if _HEX_KEY_RE.fullmatch(cleaned):
        return bytes.fromhex(cleaned)
    return None


def _aes_ecb_decrypt_block(key: bytes, block: bytes) -> bytes:
    decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    return decryptor.update(block) + decryptor.finalize()


class EchoCheckCoordinator(DataUpdateCoordinator[EchoCheckSensorData | None]):
    """Coordinator that supports both legacy GATT and passive adv operation.

    Without an encryption key the coordinator behaves exactly like the
    original: it keeps an active GATT connection and parses FFF1 "M:"
    notifications.  With a key it switches to passive advertisement reads
    (required for current GCI03 firmware, which never emits "M:").
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
        self._client: BleakClient | None = None
        self._last_seen_monotonic: float | None = None
        self._battery_percent: int | None = None
        self._firmware_version: str | None = None
        self._adv_key: bytes | None = None
        self._level_samples: deque[int] = deque(maxlen=_LEVEL_SMOOTH_WINDOW)
        self._fw_event: asyncio.Event = asyncio.Event()
        try:
            self._mac_bytes = bytes.fromhex(self.address.replace(":", ""))
        except Exception:
            self._mac_bytes = None
        self.reload_from_entry(entry)

    def reload_from_entry(self, entry: ConfigEntry) -> None:
        """Refresh coordinator state after an options update.

        The encryption key determines the operating mode: absent -> legacy
        active-GATT; present -> passive advertisement.
        """
        self.entry = entry
        raw_key = entry.options.get(CONF_ENCRYPTION_KEY, entry.data.get(CONF_ENCRYPTION_KEY))
        self._adv_key = _parse_hex_key(raw_key)
        self._level_samples.clear()
        tank_type = entry.options.get(CONF_TANK_TYPE, entry.data.get(CONF_TANK_TYPE))
        if tank_type is not None and tank_type != CUSTOM_TANK_KEY:
            self.tank_height_mm: float | None = TANK_SPECS[tank_type][1]
        else:
            raw_height = entry.options.get(CONF_TANK_HEIGHT_MM, entry.data.get(CONF_TANK_HEIGHT_MM))
            self.tank_height_mm = float(raw_height) if raw_height is not None else None
        mode = "passive-adv" if self._adv_key is not None else "active-gatt"
        _LOGGER.info(
            "EchoCheck init: address=%s mode=%s height=%s",
            self.address,
            mode,
            self.tank_height_mm,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    async def async_start(self) -> None:
        """Attempt initial connection (active mode) or do nothing (passive)."""
        if self._adv_key is not None:
            return
        await self._async_connect()

    async def async_stop(self) -> None:
        """Disconnect and clean up (active mode only)."""
        if self._client is not None:
            await self._async_disconnect()

    @property
    def data_healthy(self) -> bool:
        """True when a notification/advertisement was received recently."""
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
        """Seconds since last data, or None if never received."""
        if self._last_seen_monotonic is None:
            return None
        return time.monotonic() - self._last_seen_monotonic

    # ── DataUpdateCoordinator heartbeat ──────────────────────────────────────

    async def _async_update_data(self) -> EchoCheckSensorData | None:
        """Poll.  Passive mode reads the adv cache; active mode reconnects."""
        if self._adv_key is not None:
            return self._update_passive()
        if self._client is None or not self._client.is_connected:
            _LOGGER.debug("EchoCheck %s: not connected, attempting reconnect", self.address)
            await self._async_connect()
        return self.data  # data is updated via notification callback

    # ── Passive advertisement path (key required) ────────────────────────────

    def _update_passive(self) -> EchoCheckSensorData | None:
        """Read the cached advertisement and build a sensor snapshot."""
        cached: BluetoothServiceInfoBleak | None = bluetooth.async_last_service_info(
            self.hass, self.address, connectable=True
        )
        if cached is None:
            _LOGGER.debug("EchoCheck %s: no adv in cache", self.address)
            return self.data

        rssi = cached.rssi
        manuf = cached.advertisement.manufacturer_data.get(ECHOCHECK_MANUFACTURER_ID)

        battery = self._battery_percent
        if manuf and len(manuf) > MANUF_BATTERY_OFFSET:
            battery = int(manuf[MANUF_BATTERY_OFFSET])
        if battery is not None:
            self._battery_percent = battery

        # Tank level: manuf[4:6] = 16-bit big-endian liquid height in mm.
        # The raw echo is noisy (ultrasonic), so we median-filter the last few
        # samples to reject false-echo spikes and track the settled level.
        level_percent: float | None = None
        if manuf and len(manuf) >= MANUF_LENGTH and self.tank_height_mm:
            raw_mm = int.from_bytes(
                manuf[MANUF_LEVEL_OFFSET:MANUF_LEVEL_OFFSET + MANUF_LEVEL_LEN], "big"
            )
            level_mm = self._smooth_level(raw_mm)
            level_percent = round(
                min(max(level_mm / self.tank_height_mm * 100.0, 0.0), 100.0), 1
            )
            self._verify_identity(manuf)

        data = EchoCheckSensorData(
            mac_address=self.address,
            field_a=0,
            field_b=0,
            field_c=0,
            ddd_raw=0,
            tank_level_percent=level_percent,
            battery_percent=self._battery_percent,
            firmware_version=self._firmware_version,
            rssi=rssi,
        )
        self._last_seen_monotonic = time.monotonic()
        self.async_set_updated_data(data)
        return data

    def _smooth_level(self, raw_mm: int) -> float:
        """Median-filter the raw level reading over the recent window."""
        self._level_samples.append(raw_mm)
        samples = sorted(self._level_samples)
        n = len(samples)
        if n < 3:
            # Warm-up: not enough history yet, return the raw value so the
            # entity reports immediately instead of waiting for a full window.
            return float(raw_mm)
        mid = n // 2
        if n % 2:
            return float(samples[mid])
        return (samples[mid - 1] + samples[mid]) / 2.0

    def _verify_identity(self, manuf: bytes | bytearray) -> bool:
        """Decrypt manuf[9:25], verify device, and read the firmware type byte."""
        block = bytes(manuf[MANUF_IDENTITY_OFFSET:MANUF_IDENTITY_OFFSET + MANUF_IDENTITY_LEN])
        try:
            plain = _aes_ecb_decrypt_block(self._adv_key, block)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("EchoCheck %s: adv decrypt failed: %s", self.address, exc)
            return False

        xor_check = 0
        for b in plain[:15]:
            xor_check ^= b
        mac_ok = self._mac_bytes is not None and plain[9:15] == self._mac_bytes
        batt_ok = plain[4] == manuf[MANUF_BATTERY_OFFSET]
        xor_ok = xor_check == plain[15]
        ok = bool(mac_ok and batt_ok and xor_ok)
        if not ok:
            _LOGGER.warning(
                "EchoCheck %s: adv identity check failed (mac_ok=%s batt_ok=%s xor_ok=%s) plain=%s",
                self.address, mac_ok, batt_ok, xor_ok, plain.hex(),
            )
            return False

        # Firmware version from the identity block: minor version at byte [7],
        # major is the GCI03 tank-firmware line (21).  04 -> "21-4".
        type_byte = plain[7]
        self._firmware_version = f"{_FW_MAJOR}-{type_byte}"
        return True

    # ── Active GATT connection management ────────────────────────────────────

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
        except (BleakError, TimeoutError, OSError) as err:
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

    # ── OTA notification handler (firmware version, active mode) ─────────────

    @callback
    def _on_ota_notification(self, _handle: int, data: bytearray) -> None:
        """Handle OTA characteristic notifications (firmware version response)."""
        if len(data) >= 5 and data[0] == (OTA_FW_VERSION_RSP_OPCODE & 0xFF) and data[1] == (OTA_FW_VERSION_RSP_OPCODE >> 8):
            # Version bytes [2:5] are little-endian: [patch, minor, major]
            major, minor, patch = data[4], data[3], data[2]
            self._firmware_version = f"{major}.{minor}.{patch}"
            _LOGGER.info("EchoCheck %s: firmware=%s", self.address, self._firmware_version)
            self._fw_event.set()

    # ── Notification handler (active mode) ───────────────────────────────────

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
