"""Config + options flow for the LYWSD02 Clock integration."""
from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CLOCK_MODE_12,
    CLOCK_MODE_24,
    CONF_CLOCK_MODE,
    CONF_FREQUENCY,
    CONF_MAC,
    CONF_NAME,
    CONF_TEMP_UNIT,
    DEFAULT_CLOCK_MODE,
    DEFAULT_FREQUENCY,
    DEFAULT_TEMP_UNIT,
    DOMAIN,
    FREQUENCY_DAILY,
    FREQUENCY_MONTHLY,
    FREQUENCY_WEEKLY,
    TEMP_UNIT_C,
    TEMP_UNIT_F,
)

MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


def _normalize_mac(mac: str) -> str:
    return mac.strip().lower()


def _is_valid_mac(mac: str) -> bool:
    return bool(MAC_RE.match(_normalize_mac(mac)))


def _friendly_default(mac: str) -> str:
    compact = _normalize_mac(mac).replace(":", "")
    return f"LYWSD02 {compact[-4:].upper()}"


def _frequency_selector() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=FREQUENCY_DAILY, label="Daily"),
                SelectOptionDict(value=FREQUENCY_WEEKLY, label="Weekly (Sundays)"),
                SelectOptionDict(value=FREQUENCY_MONTHLY, label="Monthly (1st)"),
            ],
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


def _temp_unit_selector() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=TEMP_UNIT_C, label="Celsius"),
                SelectOptionDict(value=TEMP_UNIT_F, label="Fahrenheit"),
            ],
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


def _clock_mode_selector() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=str(CLOCK_MODE_24), label="24-hour"),
                SelectOptionDict(value=str(CLOCK_MODE_12), label="12-hour"),
            ],
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


class LYWSD02ConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovered_mac: str | None = None
        self._discovered_name: str | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        mac = _normalize_mac(discovery_info.address)
        await self.async_set_unique_id(mac)
        self._abort_if_unique_id_configured()
        self._discovered_mac = mac
        self._discovered_name = discovery_info.name or _friendly_default(mac)
        self.context["title_placeholders"] = {"name": self._discovered_name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._discovered_mac is not None
        if user_input is not None:
            return self._create_entry(
                mac=self._discovered_mac,
                name=user_input[CONF_NAME],
                frequency=user_input[CONF_FREQUENCY],
                temp_unit=user_input[CONF_TEMP_UNIT],
                clock_mode=int(user_input[CONF_CLOCK_MODE]),
            )

        default_name = self._discovered_name or _friendly_default(self._discovered_mac)
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=default_name): str,
                vol.Required(CONF_FREQUENCY, default=DEFAULT_FREQUENCY): _frequency_selector(),
                vol.Required(CONF_TEMP_UNIT, default=DEFAULT_TEMP_UNIT): _temp_unit_selector(),
                vol.Required(
                    CONF_CLOCK_MODE, default=str(DEFAULT_CLOCK_MODE)
                ): _clock_mode_selector(),
            }
        )
        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=schema,
            description_placeholders={
                "name": default_name,
                "mac": self._discovered_mac,
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        configured_macs = {
            entry.unique_id
            for entry in self._async_current_entries(include_ignore=False)
            if entry.unique_id
        }

        discovered_macs: list[str] = []
        for info in async_discovered_service_info(self.hass, connectable=True):
            name = (info.name or "").upper()
            if "LYWSD02" not in name:
                continue
            mac = _normalize_mac(info.address)
            if mac in configured_macs:
                continue
            if mac not in discovered_macs:
                discovered_macs.append(mac)

        if user_input is not None:
            raw_mac = user_input.get(CONF_MAC, "").strip()
            if not _is_valid_mac(raw_mac):
                errors[CONF_MAC] = "invalid_mac"
            else:
                mac = _normalize_mac(raw_mac)
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured()
                return self._create_entry(
                    mac=mac,
                    name=user_input[CONF_NAME] or _friendly_default(mac),
                    frequency=user_input[CONF_FREQUENCY],
                    temp_unit=user_input[CONF_TEMP_UNIT],
                    clock_mode=int(user_input[CONF_CLOCK_MODE]),
                )

        mac_options = [
            SelectOptionDict(value=m, label=m.upper()) for m in discovered_macs
        ]
        schema_dict: dict[Any, Any]
        if mac_options:
            schema_dict = {
                vol.Required(CONF_MAC): SelectSelector(
                    SelectSelectorConfig(
                        options=mac_options,
                        mode=SelectSelectorMode.DROPDOWN,
                        custom_value=True,
                    )
                ),
            }
        else:
            schema_dict = {vol.Required(CONF_MAC): str}

        schema_dict.update(
            {
                vol.Optional(CONF_NAME, default=""): str,
                vol.Required(CONF_FREQUENCY, default=DEFAULT_FREQUENCY): _frequency_selector(),
                vol.Required(CONF_TEMP_UNIT, default=DEFAULT_TEMP_UNIT): _temp_unit_selector(),
                vol.Required(
                    CONF_CLOCK_MODE, default=str(DEFAULT_CLOCK_MODE)
                ): _clock_mode_selector(),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )

    @callback
    def _create_entry(
        self,
        *,
        mac: str,
        name: str,
        frequency: str,
        temp_unit: str,
        clock_mode: int,
    ) -> ConfigFlowResult:
        return self.async_create_entry(
            title=name,
            data={
                CONF_MAC: mac,
                CONF_NAME: name,
                CONF_FREQUENCY: frequency,
                CONF_TEMP_UNIT: temp_unit,
                CONF_CLOCK_MODE: clock_mode,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return LYWSD02OptionsFlow(entry)


class LYWSD02OptionsFlow(OptionsFlow):
    def __init__(self, entry: ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    CONF_FREQUENCY: user_input[CONF_FREQUENCY],
                    CONF_TEMP_UNIT: user_input[CONF_TEMP_UNIT],
                    CONF_CLOCK_MODE: int(user_input[CONF_CLOCK_MODE]),
                },
            )

        current_frequency = self.entry.options.get(
            CONF_FREQUENCY, self.entry.data.get(CONF_FREQUENCY, DEFAULT_FREQUENCY)
        )
        current_unit = self.entry.options.get(
            CONF_TEMP_UNIT, self.entry.data.get(CONF_TEMP_UNIT, DEFAULT_TEMP_UNIT)
        )
        current_mode = str(
            self.entry.options.get(
                CONF_CLOCK_MODE, self.entry.data.get(CONF_CLOCK_MODE, DEFAULT_CLOCK_MODE)
            )
        )

        schema = vol.Schema(
            {
                vol.Required(CONF_FREQUENCY, default=current_frequency): _frequency_selector(),
                vol.Required(CONF_TEMP_UNIT, default=current_unit): _temp_unit_selector(),
                vol.Required(CONF_CLOCK_MODE, default=current_mode): _clock_mode_selector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
