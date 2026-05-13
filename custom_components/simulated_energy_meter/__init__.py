"""Simulated Energy Meter Integration."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    SERVICE_SET_METER,
    SERVICE_CALIBRATE,
    ATTR_KWH_VALUE,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.NUMBER]

_KWH_SCHEMA = vol.Schema({vol.Required(ATTR_KWH_VALUE): vol.Coerce(float)})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {"entry": entry, "coordinator": None}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _set_meter(call: ServiceCall) -> None:
        coord = hass.data[DOMAIN][entry.entry_id].get("coordinator")
        if coord:
            await coord.async_set_meter(call.data[ATTR_KWH_VALUE])

    async def _calibrate(call: ServiceCall) -> None:
        coord = hass.data[DOMAIN][entry.entry_id].get("coordinator")
        if coord:
            await coord.async_calibrate(call.data[ATTR_KWH_VALUE])

    hass.services.async_register(DOMAIN, SERVICE_SET_METER, _set_meter, schema=_KWH_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_CALIBRATE, _calibrate, schema=_KWH_SCHEMA)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
