"""Data coordinator for Simulated Energy Meter.

Power model
-----------
Every DEFAULT_SCAN_INTERVAL seconds:

  base_watts      = time-of-day profile value (Morgen/Tag/Abend/Nacht)
  presence_watts  = persons_home × presence_extra_watts_per_person
                    (if nobody home: base_watts × away_factor instead)
  plug_watts      = Σ live readings from smart-plug power sensors

  total_watts     = base_watts  (or base×away_factor)
                  + presence_watts
                  + plug_watts

  kWh_delta       = total_watts / 1000 × elapsed_hours
  total_kwh      += kWh_delta
"""
from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
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

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_{{entry_id}}"

# Time-slot boundaries (hour, inclusive start)
_SLOTS = [
    ("Morgen",  6,  9,  CONF_PROFILE_MORNING),
    ("Tag",    10, 17,  CONF_PROFILE_DAY),
    ("Abend",  18, 22,  CONF_PROFILE_EVENING),
    ("Nacht",  23, 29,  CONF_PROFILE_NIGHT),   # 29 wraps: 23–05
]


def _current_slot(profiles: dict[str, float], local_hour: int) -> tuple[str, float]:
    """Return (slot_name, watts) for the given local hour."""
    h = local_hour
    if 6 <= h <= 9:
        return "Morgen", profiles[CONF_PROFILE_MORNING]
    if 10 <= h <= 17:
        return "Tag", profiles[CONF_PROFILE_DAY]
    if 18 <= h <= 22:
        return "Abend", profiles[CONF_PROFILE_EVENING]
    return "Nacht", profiles[CONF_PROFILE_NIGHT]


class EnergyMeterCoordinator:
    """Central state machine for the simulated energy meter."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        initial_kwh: float,
        profiles: dict[str, float],
        power_sensors: list[str],
        presence_persons: list[str],
        presence_extra_watts: float,
        presence_away_factor: float,
    ) -> None:
        self.hass = hass
        self.entry_id = entry_id

        # Config (can be hot-updated via update_config)
        self._profiles = profiles
        self._power_sensors = power_sensors
        self._presence_persons = presence_persons
        self._presence_extra_watts = presence_extra_watts
        self._presence_away_factor = presence_away_factor

        # Persistent state
        self._total_kwh: float = initial_kwh
        self._last_update: datetime = dt_util.utcnow()
        self._last_calibration: datetime | None = None

        # Live state (updated each cycle)
        self._current_power_w: float = 0.0
        self._profile_power_w: float = 0.0
        self._presence_power_w: float = 0.0
        self._smart_plug_power_w: float = 0.0
        self._sensor_breakdown: dict[str, float] = {}
        self._active_persons: list[str] = []
        self._persons_home: int = 0
        self._current_slot: str = "Nacht"
        self._unavailable_sensors: list[str] = []

        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY.format(entry_id=entry_id))
        self._listeners: list = []

    # ──────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        """Load persisted state; add background energy for offline period."""
        stored = await self._store.async_load()
        if stored:
            self._total_kwh = stored.get("total_kwh", self._total_kwh)
            last_str = stored.get("last_update")
            if last_str:
                try:
                    last = datetime.fromisoformat(last_str)
                    now = dt_util.utcnow()
                    offline_h = (now - last).total_seconds() / 3600
                    if 0 < offline_h < 168:
                        # Use night profile × away_factor as conservative offline estimate
                        offline_w = self._profiles[CONF_PROFILE_NIGHT] * self._presence_away_factor
                        offline_kwh = (offline_w / 1000) * offline_h
                        self._total_kwh += offline_kwh
                        _LOGGER.info(
                            "Offline %.2fh → added %.4f kWh (standby estimate)",
                            offline_h, offline_kwh,
                        )
                except ValueError:
                    pass
            cal_str = stored.get("last_calibration")
            if cal_str:
                try:
                    self._last_calibration = datetime.fromisoformat(cal_str)
                except ValueError:
                    pass

        self._last_update = dt_util.utcnow()
        await self._async_save()

    def update_config(
        self,
        profiles: dict[str, float],
        power_sensors: list[str],
        presence_persons: list[str],
        presence_extra_watts: float,
        presence_away_factor: float,
    ) -> None:
        """Hot-update config without restarting HA."""
        self._profiles = profiles
        self._power_sensors = power_sensors
        self._presence_persons = presence_persons
        self._presence_extra_watts = presence_extra_watts
        self._presence_away_factor = presence_away_factor

    # ──────────────────────────────────────────────────────────────────────────
    # Listeners
    # ──────────────────────────────────────────────────────────────────────────

    def register_listener(self, cb) -> None:
        self._listeners.append(cb)

    def _notify(self) -> None:
        for cb in self._listeners:
            try:
                cb()
            except Exception:  # noqa: BLE001
                pass

    # ──────────────────────────────────────────────────────────────────────────
    # Core update loop
    # ──────────────────────────────────────────────────────────────────────────

    async def async_update(self) -> None:
        now = dt_util.utcnow()
        elapsed_h = (now - self._last_update).total_seconds() / 3600
        if elapsed_h <= 0:
            return

        local_now = dt_util.as_local(now)
        local_hour = local_now.hour

        # 1) Time-of-day profile
        slot_name, profile_w = _current_slot(self._profiles, local_hour)

        # 2) Presence
        persons_home: list[str] = []
        for entity_id in self._presence_persons:
            state = self.hass.states.get(entity_id)
            if state and state.state == "home":
                friendly = state.attributes.get("friendly_name", entity_id)
                persons_home.append(friendly)

        anyone_home = len(persons_home) > 0

        if anyone_home:
            effective_profile_w = profile_w
            presence_w = len(persons_home) * self._presence_extra_watts
        else:
            # Nobody home — scale profile down, no presence bonus
            effective_profile_w = profile_w * self._presence_away_factor
            presence_w = 0.0

        # 3) Smart plugs (live watts)
        breakdown: dict[str, float] = {}
        unavailable: list[str] = []
        plug_w = 0.0

        for entity_id in self._power_sensors:
            state = self.hass.states.get(entity_id)
            if state is None or state.state in ("unavailable", "unknown", "none", ""):
                unavailable.append(entity_id)
                continue
            try:
                w = float(state.state)
                breakdown[entity_id] = round(w, 1)
                plug_w += w
            except (ValueError, TypeError):
                unavailable.append(entity_id)

        # 4) Integrate
        total_w = effective_profile_w + presence_w + plug_w
        kwh_delta = (total_w / 1000) * elapsed_h
        self._total_kwh += kwh_delta

        # 5) Store live state
        self._current_slot = slot_name
        self._profile_power_w = round(effective_profile_w, 1)
        self._presence_power_w = round(presence_w, 1)
        self._smart_plug_power_w = round(plug_w, 1)
        self._current_power_w = round(total_w, 1)
        self._sensor_breakdown = breakdown
        self._active_persons = persons_home
        self._persons_home = len(persons_home)
        self._unavailable_sensors = unavailable
        self._last_update = now

        await self._async_save()
        self._notify()

        _LOGGER.debug(
            "[%s] slot=%s profile=%.0fW presence=%.0fW plugs=%.0fW "
            "total=%.0fW +%.5fkWh → %.3fkWh | home=%s",
            local_now.strftime("%H:%M"),
            slot_name,
            effective_profile_w,
            presence_w,
            plug_w,
            total_w,
            kwh_delta,
            self._total_kwh,
            persons_home,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Services
    # ──────────────────────────────────────────────────────────────────────────

    async def async_set_meter(self, kwh: float) -> None:
        self._total_kwh = kwh
        self._last_update = dt_util.utcnow()
        await self._async_save()
        self._notify()

    async def async_calibrate(self, real_kwh: float) -> None:
        _LOGGER.info(
            "Calibrate %.3f → %.3f kWh (drift %.3f)",
            self._total_kwh, real_kwh, real_kwh - self._total_kwh,
        )
        self._total_kwh = real_kwh
        self._last_calibration = dt_util.utcnow()
        self._last_update = dt_util.utcnow()
        await self._async_save()
        self._notify()

    async def _async_save(self) -> None:
        await self._store.async_save({
            "total_kwh": self._total_kwh,
            "last_update": self._last_update.isoformat(),
            "last_calibration": (
                self._last_calibration.isoformat() if self._last_calibration else None
            ),
        })

    # ──────────────────────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────────────────────

    @property
    def total_kwh(self) -> float:
        return round(self._total_kwh, 3)

    @property
    def current_power_w(self) -> float:
        return self._current_power_w

    @property
    def profile_power_w(self) -> float:
        return self._profile_power_w

    @property
    def presence_power_w(self) -> float:
        return self._presence_power_w

    @property
    def smart_plug_power_w(self) -> float:
        return self._smart_plug_power_w

    @property
    def sensor_breakdown(self) -> dict[str, float]:
        return self._sensor_breakdown

    @property
    def active_persons(self) -> list[str]:
        return self._active_persons

    @property
    def persons_home(self) -> int:
        return self._persons_home

    @property
    def current_time_slot(self) -> str:
        return self._current_slot

    @property
    def unavailable_sensors(self) -> list[str]:
        return self._unavailable_sensors

    @property
    def last_calibration(self) -> str | None:
        return self._last_calibration.isoformat() if self._last_calibration else None
