"""Number platform — live-editable time-profile watts and meter calibration."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    CONF_INITIAL_KWH,
    CONF_PROFILE_MORNING,
    CONF_PROFILE_DAY,
    CONF_PROFILE_EVENING,
    CONF_PROFILE_NIGHT,
    CONF_POWER_SENSORS,
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

_PROFILE_ENTITIES = [
    (
        CONF_PROFILE_MORNING,
        "Profil: Morgen (06–10 Uhr)",
        "mdi:weather-sunset-up",
        DEFAULT_PROFILE_MORNING,
    ),
    (
        CONF_PROFILE_DAY,
        "Profil: Tag (10–18 Uhr)",
        "mdi:weather-sunny",
        DEFAULT_PROFILE_DAY,
    ),
    (
        CONF_PROFILE_EVENING,
        "Profil: Abend (18–23 Uhr)",
        "mdi:weather-night",
        DEFAULT_PROFILE_EVENING,
    ),
    (
        CONF_PROFILE_NIGHT,
        "Profil: Nacht (23–06 Uhr)",
        "mdi:moon-waning-crescent",
        DEFAULT_PROFILE_NIGHT,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    def _get(key, default):
        return entry.options.get(key, entry.data.get(key, default))

    entities = [
        ProfileWattsNumber(hass, entry, conf_key, name, icon, _get(conf_key, default))
        for conf_key, name, icon, default in _PROFILE_ENTITIES
    ]
    entities.append(MeterReadingNumber(hass, entry))
    async_add_entities(entities)


class ProfileWattsNumber(NumberEntity):
    """A number entity to live-adjust one time-profile slot's wattage."""

    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 5000
    _attr_native_step = 5
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        conf_key: str,
        name: str,
        icon: str,
        value: float,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._conf_key = conf_key
        self._attr_unique_id = f"{entry.entry_id}_{conf_key}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_native_value = value
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Simulated Energy Meter",
            "manufacturer": "Custom Integration",
            "model": "Time-Profile + Presence",
        }

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()
        self._push_to_coordinator()

    def _push_to_coordinator(self) -> None:
        coordinator = self.hass.data[DOMAIN][self._entry.entry_id].get("coordinator")
        if not coordinator:
            return

        def _get(key, default):
            return self._entry.options.get(key, self._entry.data.get(key, default))

        # Build updated profiles dict — use this entity's new value for its own key
        profiles = {
            CONF_PROFILE_MORNING: (
                self._attr_native_value
                if self._conf_key == CONF_PROFILE_MORNING
                else _get(CONF_PROFILE_MORNING, DEFAULT_PROFILE_MORNING)
            ),
            CONF_PROFILE_DAY: (
                self._attr_native_value
                if self._conf_key == CONF_PROFILE_DAY
                else _get(CONF_PROFILE_DAY, DEFAULT_PROFILE_DAY)
            ),
            CONF_PROFILE_EVENING: (
                self._attr_native_value
                if self._conf_key == CONF_PROFILE_EVENING
                else _get(CONF_PROFILE_EVENING, DEFAULT_PROFILE_EVENING)
            ),
            CONF_PROFILE_NIGHT: (
                self._attr_native_value
                if self._conf_key == CONF_PROFILE_NIGHT
                else _get(CONF_PROFILE_NIGHT, DEFAULT_PROFILE_NIGHT)
            ),
        }
        coordinator.update_config(
            profiles=profiles,
            power_sensors=_get(CONF_POWER_SENSORS, []),
            presence_persons=_get(CONF_PRESENCE_PERSONS, []),
            presence_extra_watts=_get(
                CONF_PRESENCE_EXTRA_WATTS, DEFAULT_PRESENCE_EXTRA_WATTS
            ),
            presence_away_factor=_get(
                CONF_PRESENCE_AWAY_FACTOR, DEFAULT_PRESENCE_AWAY_FACTOR
            ),
        )


class MeterReadingNumber(NumberEntity):
    """Number entity to calibrate the meter to the real reading.

    Displays the current simulated total and, when a new value is set,
    calls async_calibrate so the adaptive learning system adjusts profiles.
    """

    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 999999
    _attr_native_step = 0.001
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_has_entity_name = True
    _attr_icon = "mdi:counter"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_meter_input"
        self._attr_name = "Zählerstand (Kalibrierung)"
        self._attr_native_value = entry.data.get(CONF_INITIAL_KWH, 0.0)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Simulated Energy Meter",
            "manufacturer": "Custom Integration",
            "model": "Time-Profile + Presence",
        }

    async def async_added_to_hass(self) -> None:
        coordinator = self.hass.data[DOMAIN][self._entry.entry_id].get("coordinator")
        if coordinator:
            self._attr_native_value = coordinator.total_kwh
            coordinator.register_listener(self._on_coordinator_update)
            self.async_write_ha_state()

    @callback
    def _on_coordinator_update(self) -> None:
        coordinator = self.hass.data[DOMAIN][self._entry.entry_id].get("coordinator")
        if coordinator:
            self._attr_native_value = coordinator.total_kwh
            self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        coordinator = self.hass.data[DOMAIN][self._entry.entry_id].get("coordinator")
        if coordinator:
            await coordinator.async_calibrate(value)
