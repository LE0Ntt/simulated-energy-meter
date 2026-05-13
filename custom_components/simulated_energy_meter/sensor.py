"""Sensor platform for Simulated Energy Meter."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

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
    DEFAULT_SCAN_INTERVAL,
    ATTR_CURRENT_POWER_W,
    ATTR_PROFILE_POWER_W,
    ATTR_PRESENCE_POWER_W,
    ATTR_SMART_PLUG_POWER_W,
    ATTR_SENSOR_BREAKDOWN,
    ATTR_ACTIVE_PERSONS,
    ATTR_PERSONS_HOME,
    ATTR_CURRENT_TIME_SLOT,
    ATTR_LAST_CALIBRATION,
    ATTR_UNAVAILABLE_SENSORS,
    ATTR_CALIBRATION_COUNT,
    ATTR_LEARNING_MODE,
    ATTR_LAST_DRIFT_KWH,
)
from .coordinator import EnergyMeterCoordinator

_LOGGER = logging.getLogger(__name__)


def _get(entry: ConfigEntry, key, default):
    return entry.options.get(key, entry.data.get(key, default))


def _device_info(entry: ConfigEntry) -> dict:
    return {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": "Simulated Energy Meter",
        "manufacturer": "Custom Integration",
        "model": "Adaptive Learning",
    }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    profiles = {
        CONF_PROFILE_MORNING: _get(
            entry, CONF_PROFILE_MORNING, DEFAULT_PROFILE_MORNING
        ),
        CONF_PROFILE_DAY: _get(entry, CONF_PROFILE_DAY, DEFAULT_PROFILE_DAY),
        CONF_PROFILE_EVENING: _get(
            entry, CONF_PROFILE_EVENING, DEFAULT_PROFILE_EVENING
        ),
        CONF_PROFILE_NIGHT: _get(entry, CONF_PROFILE_NIGHT, DEFAULT_PROFILE_NIGHT),
    }

    coordinator = EnergyMeterCoordinator(
        hass=hass,
        entry_id=entry.entry_id,
        initial_kwh=entry.data.get(CONF_INITIAL_KWH, 0.0),
        profiles=profiles,
        power_sensors=_get(entry, CONF_POWER_SENSORS, []),
        presence_persons=_get(entry, CONF_PRESENCE_PERSONS, []),
        presence_extra_watts=_get(
            entry, CONF_PRESENCE_EXTRA_WATTS, DEFAULT_PRESENCE_EXTRA_WATTS
        ),
        presence_away_factor=_get(
            entry, CONF_PRESENCE_AWAY_FACTOR, DEFAULT_PRESENCE_AWAY_FACTOR
        ),
    )
    await coordinator.async_setup()
    hass.data[DOMAIN][entry.entry_id]["coordinator"] = coordinator

    async_add_entities(
        [
            SimulatedEnergyMeterSensor(coordinator, entry),
            SimulatedPowerSensor(coordinator, entry),
        ],
        update_before_add=True,
    )

    entry.async_on_unload(
        async_track_time_interval(
            hass,
            lambda _now: hass.async_create_task(coordinator.async_update()),
            timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
    )


class SimulatedEnergyMeterSensor(SensorEntity):
    """Simulated cumulative kWh meter with learning attributes."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:counter"
    _attr_has_entity_name = True
    _attr_suggested_display_precision = 3

    def __init__(self, coordinator: EnergyMeterCoordinator, entry: ConfigEntry) -> None:
        self._c = coordinator
        self._attr_unique_id = f"{entry.entry_id}_meter"
        self._attr_name = "Stromzähler"
        self._attr_device_info = _device_info(entry)
        coordinator.register_listener(self._push)

    @callback
    def _push(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> float:
        return self._c.total_kwh

    @property
    def extra_state_attributes(self) -> dict:
        return {
            ATTR_CURRENT_POWER_W: self._c.current_power_w,
            ATTR_PROFILE_POWER_W: self._c.profile_power_w,
            ATTR_PRESENCE_POWER_W: self._c.presence_power_w,
            ATTR_SMART_PLUG_POWER_W: self._c.smart_plug_power_w,
            ATTR_SENSOR_BREAKDOWN: self._c.sensor_breakdown,
            ATTR_ACTIVE_PERSONS: self._c.active_persons,
            ATTR_PERSONS_HOME: self._c.persons_home,
            ATTR_CURRENT_TIME_SLOT: self._c.current_time_slot,
            ATTR_LAST_CALIBRATION: self._c.last_calibration,
            ATTR_UNAVAILABLE_SENSORS: self._c.unavailable_sensors,
            # Learning
            ATTR_CALIBRATION_COUNT: self._c.calibration_count,
            ATTR_LEARNING_MODE: self._c.learning_mode,
            ATTR_LAST_DRIFT_KWH: self._c.last_drift_kwh,
            "learned_profiles_w": self._c.learned_profiles,
        }

    async def async_update(self) -> None:
        await self._c.async_update()


class SimulatedPowerSensor(SensorEntity):
    """Current estimated power in Watts."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:lightning-bolt"
    _attr_has_entity_name = True
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: EnergyMeterCoordinator, entry: ConfigEntry) -> None:
        self._c = coordinator
        self._attr_unique_id = f"{entry.entry_id}_power"
        self._attr_name = "Aktuelle Leistung"
        self._attr_device_info = _device_info(entry)
        coordinator.register_listener(self._push)

    @callback
    def _push(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> float:
        return self._c.current_power_w

    @property
    def extra_state_attributes(self) -> dict:
        return {
            ATTR_PROFILE_POWER_W: self._c.profile_power_w,
            ATTR_PRESENCE_POWER_W: self._c.presence_power_w,
            ATTR_SMART_PLUG_POWER_W: self._c.smart_plug_power_w,
            ATTR_SENSOR_BREAKDOWN: self._c.sensor_breakdown,
            ATTR_ACTIVE_PERSONS: self._c.active_persons,
            ATTR_CURRENT_TIME_SLOT: self._c.current_time_slot,
            ATTR_LEARNING_MODE: self._c.learning_mode,
        }

    async def async_update(self) -> None:
        pass
