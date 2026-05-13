"""Config flow for Simulated Energy Meter."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_INITIAL_KWH,
    CONF_POWER_SENSORS,
    CONF_PROFILE_MORNING,
    CONF_PROFILE_DAY,
    CONF_PROFILE_EVENING,
    CONF_PROFILE_NIGHT,
    CONF_PRESENCE_PERSONS,
    CONF_PRESENCE_EXTRA_WATTS,
    CONF_PRESENCE_AWAY_FACTOR,
    DEFAULT_PROFILE_MORNING,
    DEFAULT_PROFILE_DAY,
    DEFAULT_PROFILE_EVENING,
    DEFAULT_PROFILE_NIGHT,
    DEFAULT_PRESENCE_EXTRA_WATTS,
    DEFAULT_PRESENCE_AWAY_FACTOR,
)

_LOGGER = logging.getLogger(__name__)


def _watts_selector(default: float, max_w: int = 2000) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0, max=max_w, step=1,
            unit_of_measurement="W",
            mode=selector.NumberSelectorMode.BOX,
        )
    )


class SimulatedEnergyMeterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Three-step setup: basics → time profiles → presence."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    # ── Step 1: Initial kWh + smart plugs ─────────────────────────────────────
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_INITIAL_KWH] < 0:
                errors[CONF_INITIAL_KWH] = "invalid_kwh"
            else:
                self._data.update(user_input)
                return await self.async_step_profiles()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_INITIAL_KWH, default=0.0): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=999999, step=0.001,
                        unit_of_measurement="kWh",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(CONF_POWER_SENSORS, default=[]): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        device_class="power",
                        multiple=True,
                    )
                ),
            }),
            errors=errors,
        )

    # ── Step 2: Time-of-day profiles ──────────────────────────────────────────
    async def async_step_profiles(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_presence()

        return self.async_show_form(
            step_id="profiles",
            data_schema=vol.Schema({
                vol.Required(CONF_PROFILE_MORNING, default=DEFAULT_PROFILE_MORNING): _watts_selector(DEFAULT_PROFILE_MORNING),
                vol.Required(CONF_PROFILE_DAY,     default=DEFAULT_PROFILE_DAY):     _watts_selector(DEFAULT_PROFILE_DAY),
                vol.Required(CONF_PROFILE_EVENING, default=DEFAULT_PROFILE_EVENING): _watts_selector(DEFAULT_PROFILE_EVENING),
                vol.Required(CONF_PROFILE_NIGHT,   default=DEFAULT_PROFILE_NIGHT):   _watts_selector(DEFAULT_PROFILE_NIGHT),
            }),
        )

    # ── Step 3: Presence ──────────────────────────────────────────────────────
    async def async_step_presence(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title="Simulated Energy Meter", data=self._data)

        return self.async_show_form(
            step_id="presence",
            data_schema=vol.Schema({
                vol.Optional(CONF_PRESENCE_PERSONS, default=[]): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="person", multiple=True)
                ),
                vol.Required(CONF_PRESENCE_EXTRA_WATTS, default=DEFAULT_PRESENCE_EXTRA_WATTS): _watts_selector(DEFAULT_PRESENCE_EXTRA_WATTS),
                vol.Required(CONF_PRESENCE_AWAY_FACTOR, default=DEFAULT_PRESENCE_AWAY_FACTOR): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.0, max=1.0, step=0.05,
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                ),
            }),
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: config_entries.ConfigEntry) -> SimulatedEnergyMeterOptionsFlow:
        return SimulatedEnergyMeterOptionsFlow(entry)


# ── Options flow (same 3 steps, pre-filled) ───────────────────────────────────

class SimulatedEnergyMeterOptionsFlow(config_entries.OptionsFlow):
    """Edit all settings after initial setup."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry
        self._data: dict[str, Any] = {}

    def _get(self, key: str, default):
        return self.entry.options.get(key, self.entry.data.get(key, default))

    async def async_step_init(self, user_input=None) -> config_entries.FlowResult:
        return await self.async_step_profiles()

    async def async_step_profiles(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_presence()

        return self.async_show_form(
            step_id="profiles",
            data_schema=vol.Schema({
                vol.Required(CONF_PROFILE_MORNING, default=self._get(CONF_PROFILE_MORNING, DEFAULT_PROFILE_MORNING)): _watts_selector(DEFAULT_PROFILE_MORNING),
                vol.Required(CONF_PROFILE_DAY,     default=self._get(CONF_PROFILE_DAY,     DEFAULT_PROFILE_DAY)):     _watts_selector(DEFAULT_PROFILE_DAY),
                vol.Required(CONF_PROFILE_EVENING, default=self._get(CONF_PROFILE_EVENING, DEFAULT_PROFILE_EVENING)): _watts_selector(DEFAULT_PROFILE_EVENING),
                vol.Required(CONF_PROFILE_NIGHT,   default=self._get(CONF_PROFILE_NIGHT,   DEFAULT_PROFILE_NIGHT)):   _watts_selector(DEFAULT_PROFILE_NIGHT),
            }),
        )

    async def async_step_presence(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_plugs()

        return self.async_show_form(
            step_id="presence",
            data_schema=vol.Schema({
                vol.Optional(CONF_PRESENCE_PERSONS, default=self._get(CONF_PRESENCE_PERSONS, [])): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="person", multiple=True)
                ),
                vol.Required(CONF_PRESENCE_EXTRA_WATTS, default=self._get(CONF_PRESENCE_EXTRA_WATTS, DEFAULT_PRESENCE_EXTRA_WATTS)): _watts_selector(DEFAULT_PRESENCE_EXTRA_WATTS),
                vol.Required(CONF_PRESENCE_AWAY_FACTOR, default=self._get(CONF_PRESENCE_AWAY_FACTOR, DEFAULT_PRESENCE_AWAY_FACTOR)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.0, max=1.0, step=0.05, mode=selector.NumberSelectorMode.SLIDER)
                ),
            }),
        )

    async def async_step_plugs(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            self._data.update(user_input)
            # Push changes into live coordinator immediately
            coordinator = self.hass.data[DOMAIN][self.entry.entry_id].get("coordinator")
            if coordinator:
                from .coordinator import _current_slot  # noqa: F401
                coordinator.update_config(
                    profiles={
                        CONF_PROFILE_MORNING: self._data.get(CONF_PROFILE_MORNING, DEFAULT_PROFILE_MORNING),
                        CONF_PROFILE_DAY:     self._data.get(CONF_PROFILE_DAY,     DEFAULT_PROFILE_DAY),
                        CONF_PROFILE_EVENING: self._data.get(CONF_PROFILE_EVENING, DEFAULT_PROFILE_EVENING),
                        CONF_PROFILE_NIGHT:   self._data.get(CONF_PROFILE_NIGHT,   DEFAULT_PROFILE_NIGHT),
                    },
                    power_sensors=self._data.get(CONF_POWER_SENSORS, []),
                    presence_persons=self._data.get(CONF_PRESENCE_PERSONS, []),
                    presence_extra_watts=self._data.get(CONF_PRESENCE_EXTRA_WATTS, DEFAULT_PRESENCE_EXTRA_WATTS),
                    presence_away_factor=self._data.get(CONF_PRESENCE_AWAY_FACTOR, DEFAULT_PRESENCE_AWAY_FACTOR),
                )
            return self.async_create_entry(title="", data=self._data)

        return self.async_show_form(
            step_id="plugs",
            data_schema=vol.Schema({
                vol.Optional(CONF_POWER_SENSORS, default=self._get(CONF_POWER_SENSORS, [])): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="power", multiple=True)
                ),
            }),
        )
