"""Data coordinator for Simulated Energy Meter.

Power model (every DEFAULT_SCAN_INTERVAL seconds)
──────────────────────────────────────────────────
  profile_w  = current time-slot base value  (Morgen/Tag/Abend/Nacht)
  presence_w = persons_home × extra_watts    (0 if nobody home → profile × away_factor)
  plug_w     = Σ live smart-plug sensor readings

  total_w    = profile_w + presence_w + plug_w
  kWh_delta  = total_w / 1000 × elapsed_hours
  total_kwh += kWh_delta

Learning system
───────────────
Between every two calibrations the coordinator tracks per-slot accumulators:
  slot_profile_kwh[slot]  — how much energy the *profile part* contributed
  slot_hours[slot]        — how many hours were spent in this slot

On calibration the "profile drift" is isolated:
  total_drift      = real_kwh - simulated_kwh
  plug_drift       = (real_plug_kwh is measured, excluded) → 0
  profile_drift    = total_drift          (smart plugs are accurate; drift is in profile)

Phase 1 — < LEARNING_MIN_CALIBRATIONS:
  All profile slots scaled equally: new = old × (1 + damping × drift_ratio)

Phase 2 — ≥ LEARNING_MIN_CALIBRATIONS:
  slot_weight      = slot_profile_kwh[slot] / Σ slot_profile_kwh
  slot_correction  = profile_drift × slot_weight / slot_hours[slot] × 1000  (W)
  new_profile[slot]= old + damping × correction, clamped to ±MAX_CORRECTION_PCT

A persistent HA notification summarises every adaptation so the user can see
what changed. Adjustments are also written to the debug log.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Any

from homeassistant.components.persistent_notification import (
    async_create as pn_create,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
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
    LEARNING_MIN_CALIBRATIONS,
    LEARNING_DAMPING,
    LEARNING_MAX_CORRECTION_PCT,
    LEARNING_MIN_SLOT_HOURS,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 2
STORAGE_KEY = f"{DOMAIN}_{{entry_id}}"

ALL_SLOTS = (
    CONF_PROFILE_MORNING,
    CONF_PROFILE_DAY,
    CONF_PROFILE_EVENING,
    CONF_PROFILE_NIGHT,
)
SLOT_NAMES = {
    CONF_PROFILE_MORNING: "Morgen",
    CONF_PROFILE_DAY: "Tag",
    CONF_PROFILE_EVENING: "Abend",
    CONF_PROFILE_NIGHT: "Nacht",
}


def _hour_to_slot(hour: int) -> str:
    if 6 <= hour <= 9:
        return CONF_PROFILE_MORNING
    if 10 <= hour <= 17:
        return CONF_PROFILE_DAY
    if 18 <= hour <= 22:
        return CONF_PROFILE_EVENING
    return CONF_PROFILE_NIGHT


class EnergyMeterCoordinator:
    """Central state machine: simulation + adaptive profile learning."""

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
        light_entities: list[str] | None = None,
        light_watts: float = 8.0,
    ) -> None:
        self.hass = hass
        self.entry_id = entry_id

        # ── Mutable config (hot-updated via update_config) ────────────────────
        self._profiles: dict[str, float] = dict(profiles)
        self._power_sensors: list[str] = list(power_sensors)
        self._presence_persons: list[str] = list(presence_persons)
        self._presence_extra_watts: float = presence_extra_watts
        self._presence_away_factor: float = presence_away_factor
        self._light_entities: list[str] = list(light_entities or [])
        self._light_watts: float = light_watts

        # ── Persistent state ──────────────────────────────────────────────────
        self._total_kwh: float = initial_kwh
        self._last_update: datetime = dt_util.utcnow()
        self._last_calibration: datetime | None = None
        self._calibration_count: int = 0
        self._last_drift_kwh: float = 0.0

        # ── Per-slot accumulators (reset after each calibration) ──────────────
        # how many kWh the profile part contributed in each slot
        self._slot_profile_kwh: dict[str, float] = defaultdict(float)
        # how many hours we spent in each slot
        self._slot_hours: dict[str, float] = defaultdict(float)
        # simulated total at last calibration (to compute drift)
        self._kwh_at_last_calibration: float = initial_kwh

        # ── Live state ────────────────────────────────────────────────────────
        self._current_power_w: float = 0.0
        self._profile_power_w: float = 0.0
        self._presence_power_w: float = 0.0
        self._smart_plug_power_w: float = 0.0
        self._light_power_w: float = 0.0
        self._sensor_breakdown: dict[str, float] = {}
        self._active_persons: list[str] = []
        self._active_lights: list[str] = []
        self._persons_home: int = 0
        self._current_slot: str = CONF_PROFILE_NIGHT
        self._unavailable_sensors: list[str] = []

        self._store = Store(
            hass, STORAGE_VERSION, STORAGE_KEY.format(entry_id=entry_id)
        )
        self._listeners: list = []

    # ──────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        """Load persisted state; add offline background estimate."""
        stored = await self._store.async_load()
        if stored:
            self._total_kwh = stored.get("total_kwh", self._total_kwh)
            self._calibration_count = stored.get("calibration_count", 0)
            self._last_drift_kwh = stored.get("last_drift_kwh", 0.0)
            self._kwh_at_last_calibration = stored.get(
                "kwh_at_last_calibration", self._total_kwh
            )

            # Restore learned profiles (may override config defaults)
            for slot in ALL_SLOTS:
                key = f"learned_{slot}"
                if key in stored:
                    self._profiles[slot] = stored[key]
                    _LOGGER.debug(
                        "Restored learned profile %s = %.1fW", slot, stored[key]
                    )

            # Restore per-slot accumulators
            for slot in ALL_SLOTS:
                self._slot_profile_kwh[slot] = stored.get(f"acc_kwh_{slot}", 0.0)
                self._slot_hours[slot] = stored.get(f"acc_h_{slot}", 0.0)


            last_str = stored.get("last_update")
            if last_str:
                try:
                    last = datetime.fromisoformat(last_str)
                    now = dt_util.utcnow()
                    offline_h = (now - last).total_seconds() / 3600
                    if 0 < offline_h < 168:
                        offline_w = (
                            self._profiles[CONF_PROFILE_NIGHT]
                            * self._presence_away_factor
                        )
                        offline_kwh = (offline_w / 1000) * offline_h
                        self._total_kwh += offline_kwh
                        _LOGGER.info(
                            "Offline %.2fh → +%.4f kWh (night standby estimate)",
                            offline_h,
                            offline_kwh,
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
        light_entities: list[str] | None = None,
        light_watts: float | None = None,
        device_estimate_entities: list[str] | None = None,
    ) -> None:
        """Hot-update config (called from options flow or number entities)."""
        self._profiles = dict(profiles)
        self._power_sensors = list(power_sensors)
        self._presence_persons = list(presence_persons)
        self._presence_extra_watts = presence_extra_watts
        self._presence_away_factor = presence_away_factor
        if light_entities is not None:
            self._light_entities = list(light_entities)
        if light_watts is not None:
            self._light_watts = light_watts

    def set_light_watts(self, watts: float) -> None:
        """Update estimated watts per active light."""
        self._light_watts = watts

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

        local_hour = dt_util.as_local(now).hour
        slot = _hour_to_slot(local_hour)
        profile_w = self._profiles[slot]

        # Presence
        persons_home: list[str] = []
        for eid in self._presence_persons:
            state = self.hass.states.get(eid)
            if state and state.state == "home":
                persons_home.append(state.attributes.get("friendly_name", eid))

        if persons_home:
            effective_profile_w = profile_w
            presence_w = len(persons_home) * self._presence_extra_watts
        else:
            effective_profile_w = profile_w * self._presence_away_factor
            presence_w = 0.0

        # Smart plugs
        breakdown: dict[str, float] = {}
        unavailable: list[str] = []
        plug_w = 0.0
        for eid in self._power_sensors:
            state = self.hass.states.get(eid)
            if state is None or state.state in ("unavailable", "unknown", "none", ""):
                unavailable.append(eid)
                continue
            try:
                w = float(state.state)
                breakdown[eid] = round(w, 1)
                plug_w += w
            except (ValueError, TypeError):
                unavailable.append(eid)

        # Lights
        active_lights: list[str] = []
        for eid in self._light_entities:
            state = self.hass.states.get(eid)
            if state and state.state == "on":
                active_lights.append(eid)
        light_w = len(active_lights) * self._light_watts

        total_w = effective_profile_w + presence_w + plug_w + light_w
        kwh_delta = (total_w / 1000) * elapsed_h

        # ── Update accumulators for learning ──────────────────────────────────
        profile_kwh_delta = (effective_profile_w / 1000) * elapsed_h
        self._slot_profile_kwh[slot] += profile_kwh_delta
        self._slot_hours[slot] += elapsed_h

        # ── Integrate ─────────────────────────────────────────────────────────
        self._total_kwh += kwh_delta
        self._current_slot = slot
        self._profile_power_w = round(effective_profile_w, 1)
        self._presence_power_w = round(presence_w, 1)
        self._smart_plug_power_w = round(plug_w, 1)
        self._light_power_w = round(light_w, 1)
        self._current_power_w = round(total_w, 1)
        self._sensor_breakdown = breakdown
        self._active_persons = persons_home
        self._active_lights = active_lights
        self._persons_home = len(persons_home)
        self._unavailable_sensors = unavailable
        self._last_update = now

        await self._async_save()
        self._notify()

        _LOGGER.debug(
            "[%s] %s | profile=%.0fW presence=%.0fW plugs=%.0fW → %.0fW | total=%.3fkWh",
            dt_util.as_local(now).strftime("%H:%M"),
            SLOT_NAMES[slot],
            effective_profile_w,
            presence_w,
            plug_w,
            total_w,
            self._total_kwh,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Calibration + Learning
    # ──────────────────────────────────────────────────────────────────────────

    async def async_calibrate(self, real_kwh: float) -> None:
        """Sync to real meter and adapt profiles based on drift."""
        simulated_kwh = self._total_kwh
        drift_kwh = real_kwh - simulated_kwh
        self._last_drift_kwh = round(drift_kwh, 3)
        self._calibration_count += 1

        _LOGGER.info(
            "Calibration #%d: simulated=%.3f real=%.3f drift=%.3f kWh",
            self._calibration_count,
            simulated_kwh,
            real_kwh,
            drift_kwh,
        )

        # Only adapt if drift is meaningful (> 0.1 kWh)
        if abs(drift_kwh) > 0.1:
            await self._adapt_profiles(drift_kwh)
        else:
            _LOGGER.info(
                "Drift %.3f kWh below threshold — profiles unchanged", drift_kwh
            )

        # Reset state
        self._total_kwh = real_kwh
        self._last_calibration = dt_util.utcnow()
        self._last_update = dt_util.utcnow()
        self._kwh_at_last_calibration = real_kwh
        self._slot_profile_kwh = defaultdict(float)
        self._slot_hours = defaultdict(float)

        await self._async_save()
        self._notify()

    async def _adapt_profiles(self, drift_kwh: float) -> None:
        """Core learning logic — adjusts profile watts based on observed drift."""
        total_profile_kwh = sum(self._slot_profile_kwh[s] for s in ALL_SLOTS)

        if total_profile_kwh < 0.01:
            _LOGGER.warning("No accumulator data — skipping profile adaptation")
            return

        use_targeted = self._calibration_count >= LEARNING_MIN_CALIBRATIONS
        mode = "targeted (slot-aware)" if use_targeted else "proportional (simple)"
        _LOGGER.info(
            "Learning mode: %s (calibration #%d)", mode, self._calibration_count
        )

        changes: dict[str, tuple[float, float]] = {}  # slot → (old_w, new_w)

        for slot in ALL_SLOTS:
            old_w = self._profiles[slot]
            slot_hours = self._slot_hours[slot]

            if slot_hours < LEARNING_MIN_SLOT_HOURS:
                _LOGGER.debug("Slot %s: only %.2fh data — skipping", slot, slot_hours)
                continue

            if use_targeted:
                # Weight correction by how much this slot contributed to profile energy
                slot_weight = self._slot_profile_kwh[slot] / total_profile_kwh
                # Convert kWh drift → Watt correction for this slot
                correction_w = (drift_kwh * slot_weight / slot_hours) * 1000
            else:
                # Simple: spread drift equally across all slots by hours
                correction_w = (drift_kwh / sum(self._slot_hours.values())) * 1000

            # Dampen to avoid overcorrecting
            dampened_w = correction_w * LEARNING_DAMPING

            # Clamp to ±MAX_CORRECTION_PCT of current value
            max_delta = old_w * LEARNING_MAX_CORRECTION_PCT
            dampened_w = max(-max_delta, min(max_delta, dampened_w))

            new_w = max(1.0, old_w + dampened_w)
            self._profiles[slot] = round(new_w, 1)
            changes[slot] = (old_w, new_w)

            _LOGGER.info(
                "Profile %s: %.1fW → %.1fW (correction %.1fW, dampened %.1fW)",
                SLOT_NAMES[slot],
                old_w,
                new_w,
                correction_w,
                dampened_w,
            )

        # ── Send HA notification ───────────────────────────────────────────────
        if changes:
            lines = [
                f"**Kalibrierung #{self._calibration_count}** — Drift: {drift_kwh:+.3f} kWh",
                f"Lernmodus: _{mode}_",
                "",
                "| Slot | Alt | Neu | Änderung |",
                "|------|-----|-----|----------|",
            ]
            for slot, (old_w, new_w) in changes.items():
                delta = new_w - old_w
                lines.append(
                    f"| {SLOT_NAMES[slot]} | {old_w:.0f}W | {new_w:.0f}W | {delta:+.1f}W |"
                )
            lines += [
                "",
                "_Profile werden beim nächsten Zyklus verwendet._",
            ]
            pn_create(
                self.hass,
                "\n".join(lines),
                title="⚡ Stromzähler — Profile angepasst",
                notification_id=f"{DOMAIN}_learning_{self.entry_id}",
            )

    async def async_set_meter(self, kwh: float) -> None:
        self._total_kwh = kwh
        self._last_update = dt_util.utcnow()
        await self._async_save()
        self._notify()

    # ──────────────────────────────────────────────────────────────────────────
    # Storage
    # ──────────────────────────────────────────────────────────────────────────

    async def _async_save(self) -> None:
        data: dict[str, Any] = {
            "total_kwh": self._total_kwh,
            "last_update": self._last_update.isoformat(),
            "last_calibration": (
                self._last_calibration.isoformat() if self._last_calibration else None
            ),
            "calibration_count": self._calibration_count,
            "last_drift_kwh": self._last_drift_kwh,
            "kwh_at_last_calibration": self._kwh_at_last_calibration,
        }
        # Persist learned profiles
        for slot in ALL_SLOTS:
            data[f"learned_{slot}"] = self._profiles[slot]
        # Persist accumulators
        for slot in ALL_SLOTS:
            data[f"acc_kwh_{slot}"] = self._slot_profile_kwh[slot]
            data[f"acc_h_{slot}"] = self._slot_hours[slot]

        await self._store.async_save(data)

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
        return SLOT_NAMES.get(self._current_slot, self._current_slot)

    @property
    def light_power_w(self) -> float:
        return self._light_power_w

    @property
    def active_lights(self) -> list[str]:
        return self._active_lights

    @property
    def light_watts(self) -> float:
        return self._light_watts

    @property
    def unavailable_sensors(self) -> list[str]:
        return self._unavailable_sensors

    @property
    def last_calibration(self) -> str | None:
        return self._last_calibration.isoformat() if self._last_calibration else None

    @property
    def calibration_count(self) -> int:
        return self._calibration_count

    @property
    def last_drift_kwh(self) -> float:
        return self._last_drift_kwh

    @property
    def learning_mode(self) -> str:
        if self._calibration_count == 0:
            return "Noch keine Kalibrierung"
        if self._calibration_count < LEARNING_MIN_CALIBRATIONS:
            remaining = LEARNING_MIN_CALIBRATIONS - self._calibration_count
            return f"Einfach (noch {remaining}× bis Slot-Lernen)"
        return "Intelligent (Slot-basiert)"

    @property
    def learned_profiles(self) -> dict[str, float]:
        return {SLOT_NAMES[s]: self._profiles[s] for s in ALL_SLOTS}
