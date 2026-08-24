"""Config flow for EchoCheck BLE integration."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_ADDRESS

from .const import (
    CONF_ENCRYPTION_KEY,
    CONF_TANK_HEIGHT_MM,
    CONF_TANK_TYPE,
    CUSTOM_TANK_KEY,
    DOMAIN,
    ECHOCHECK_MANUFACTURER_ID,
    ECHOCHECK_NAME_PREFIX,
    TANK_SPECS,
)

_MM_PER_INCH = 25.4
_DEFAULT_CUSTOM_HEIGHT_MM = 254

_TANK_TYPE_LABELS: dict[str, str] = {k: v[0] for k, v in TANK_SPECS.items()}


def _display_in_inches(hass) -> bool:
    return not hass.config.units.is_metric


def _tank_type_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_TANK_TYPE, default=defaults.get(CONF_TANK_TYPE, "30lb_v")): vol.In(_TANK_TYPE_LABELS),
    })


def _custom_height_schema(defaults: dict[str, Any], use_inches: bool) -> vol.Schema:
    stored_mm = float(defaults.get(CONF_TANK_HEIGHT_MM, _DEFAULT_CUSTOM_HEIGHT_MM))
    if use_inches:
        display_default = round(stored_mm / _MM_PER_INCH)
        validator = vol.All(vol.Coerce(int), vol.Range(min=1, max=394))
    else:
        display_default = round(stored_mm)
        validator = vol.All(vol.Coerce(int), vol.Range(min=10, max=10000))
    return vol.Schema({
        vol.Required(CONF_TANK_HEIGHT_MM, default=display_default): validator,
    })


def _validate_encryption_key(value: str) -> str:
    """Validate/normalize the optional AES-128 key (empty or 16 bytes hex).

    Accepts 32 hex chars, optionally colon/space separated. Returns normalized
    lowercase hex (no separators), or "" to disable verification.
    """
    if not isinstance(value, str):
        raise vol.Invalid("Encryption key must be a string")
    cleaned = value.strip().replace(":", "").replace(" ", "").lower()
    if cleaned == "":
        return ""
    if re.fullmatch(r"[0-9a-f]{32}", cleaned):
        return cleaned
    raise vol.Invalid("Encryption key must be empty or 32 hex characters (16 bytes)")


def _is_echocheck_device(info: BluetoothServiceInfoBleak) -> bool:
    return (info.name or "").startswith(ECHOCHECK_NAME_PREFIX) or \
        ECHOCHECK_MANUFACTURER_ID in info.manufacturer_data


class EchoCheckConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle config flow for EchoCheck."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._pending_data: dict[str, Any] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle BLE auto-discovery."""
        if not _is_echocheck_device(discovery_info):
            return self.async_abort(reason="not_supported")

        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {
            "name": discovery_info.name or discovery_info.address
        }
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm auto-discovered device and select tank type."""
        if self._discovery_info is None:
            return self.async_abort(reason="no_device")

        if user_input is not None:
            self._pending_data = {
                CONF_ADDRESS: self._discovery_info.address,
                **user_input,
            }
            if user_input[CONF_TANK_TYPE] == CUSTOM_TANK_KEY:
                return await self.async_step_custom_height()
            return self.async_create_entry(
                title=self._discovery_info.name or self._discovery_info.address,
                data=self._pending_data,
            )

        return self.async_show_form(
            step_id="confirm",
            data_schema=_tank_type_schema({}),
            description_placeholders={
                "name": self._discovery_info.name or self._discovery_info.address,
            },
        )

    async def async_step_custom_height(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect custom tank height (only when 'Custom' is selected)."""
        use_inches = _display_in_inches(self.hass)
        if user_input is not None:
            raw = user_input[CONF_TANK_HEIGHT_MM]
            self._pending_data[CONF_TANK_HEIGHT_MM] = round(raw * _MM_PER_INCH) if use_inches else raw
            title = self._pending_data.get(CONF_ADDRESS, "EchoCheck")
            return self.async_create_entry(title=title, data=self._pending_data)

        return self.async_show_form(
            step_id="custom_height",
            data_schema=_custom_height_schema(self._pending_data, use_inches),
            description_placeholders={"unit": "inches" if use_inches else "mm"},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual setup flow."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()
            self._pending_data = dict(user_input)
            if user_input[CONF_TANK_TYPE] == CUSTOM_TANK_KEY:
                return await self.async_step_custom_height()
            return self.async_create_entry(
                title=f"EchoCheck {address}",
                data=self._pending_data,
            )

        discovered: dict[str, str] = {}
        for info in async_discovered_service_info(self.hass, connectable=True):
            if _is_echocheck_device(info):
                discovered[info.address] = f"{info.name} ({info.address})"

        address_field: vol.Marker = (
            vol.Required(CONF_ADDRESS, default=next(iter(discovered)))
            if discovered
            else vol.Required(CONF_ADDRESS)
        )
        address_validator = vol.In(discovered) if discovered else str

        schema = vol.Schema({
            address_field: address_validator,
            **_tank_type_schema({}).schema,
        })

        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    def async_get_options_flow(config_entry):
        return EchoCheckOptionsFlow(config_entry)


class EchoCheckOptionsFlow(OptionsFlow):
    """Options flow for EchoCheck (tank type/height + optional encryption key)."""

    def __init__(self, config_entry) -> None:
        self.config_entry = config_entry
        self._pending_options: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._pending_options = dict(user_input)
            if user_input[CONF_TANK_TYPE] == CUSTOM_TANK_KEY:
                return await self.async_step_custom_height()
            return self.async_create_entry(title="", data=self._pending_options)

        defaults = {
            CONF_TANK_TYPE: self.config_entry.options.get(
                CONF_TANK_TYPE, self.config_entry.data.get(CONF_TANK_TYPE, "30lb_v")
            ),
            CONF_ENCRYPTION_KEY: self.config_entry.options.get(
                CONF_ENCRYPTION_KEY, self.config_entry.data.get(CONF_ENCRYPTION_KEY, "")
            ),
        }
        schema = vol.Schema({
            **_tank_type_schema(defaults).schema,
            vol.Optional(
                CONF_ENCRYPTION_KEY, default=defaults[CONF_ENCRYPTION_KEY]
            ): _validate_encryption_key,
        })
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_custom_height(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        use_inches = _display_in_inches(self.hass)
        if user_input is not None:
            raw = user_input[CONF_TANK_HEIGHT_MM]
            self._pending_options[CONF_TANK_HEIGHT_MM] = round(raw * _MM_PER_INCH) if use_inches else raw
            return self.async_create_entry(title="", data=self._pending_options)

        existing_mm = self.config_entry.options.get(
            CONF_TANK_HEIGHT_MM,
            self.config_entry.data.get(CONF_TANK_HEIGHT_MM, _DEFAULT_CUSTOM_HEIGHT_MM),
        )
        return self.async_show_form(
            step_id="custom_height",
            data_schema=_custom_height_schema({CONF_TANK_HEIGHT_MM: existing_mm}, use_inches),
            description_placeholders={"unit": "inches" if use_inches else "mm"},
        )
