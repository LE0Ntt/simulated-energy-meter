"""Simulated Energy Meter Integration."""
from __future__ import annotations

import logging
from datetime import datetime

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

SET_METER_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_KWH_VALUE): vol.Coerce(float),
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Simulated Energy Meter from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "entry": entry,
        "coordinator": None,  # will be set by sensor platform
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    async def handle_set_meter(call: ServiceCall) -> None:
        """Handle set_meter_value service."""
        kwh = call.data[ATTR_KWH_VALUE]
        coordinator = hass.data[DOMAIN][entry.entry_id].get("coordinator")
        if coordinator:
            await coordinator.async_set_meter(kwh)
            _LOGGER.info("Meter set to %.3f kWh", kwh)

    async def handle_calibrate(call: ServiceCall) -> None:
        """Handle calibrate service: set meter to real reading."""
        kwh = call.data[ATTR_KWH_VALUE]
        coordinator = hass.data[DOMAIN][entry.entry_id].get("coordinator")
        if coordinator:
            await coordinator.async_calibrate(kwh)
            _LOGGER.info("Meter calibrated to %.3f kWh at %s", kwh, datetime.now())

    hass.services.async_register(
        DOMAIN, SERVICE_SET_METER, handle_set_meter, schema=SET_METER_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CALIBRATE, handle_calibrate, schema=SET_METER_SCHEMA
    )

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
