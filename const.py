"""Constants for Simulated Energy Meter."""

DOMAIN = "simulated_energy_meter"

# ── Basic config ──────────────────────────────────────────────────────────────
CONF_INITIAL_KWH        = "initial_kwh"
CONF_POWER_SENSORS      = "power_sensors"       # live-watt smart plug sensors

# ── Time-of-day profiles (Watt values for each slot) ─────────────────────────
CONF_PROFILE_MORNING    = "profile_morning"     # 06:00 – 09:59
CONF_PROFILE_DAY        = "profile_day"         # 10:00 – 17:59
CONF_PROFILE_EVENING    = "profile_evening"     # 18:00 – 22:59
CONF_PROFILE_NIGHT      = "profile_night"       # 23:00 – 05:59

DEFAULT_PROFILE_MORNING = 120.0   # W  (breakfast, coffee machine, lights)
DEFAULT_PROFILE_DAY     =  80.0   # W  (low activity / work from outside)
DEFAULT_PROFILE_EVENING = 200.0   # W  (TV, lighting, cooking)
DEFAULT_PROFILE_NIGHT   =  50.0   # W  (pure standby)

# ── Presence ──────────────────────────────────────────────────────────────────
CONF_PRESENCE_PERSONS       = "presence_persons"        # list[entity_id] of person.*
CONF_PRESENCE_EXTRA_WATTS   = "presence_extra_watts"    # W added per person at home
CONF_PRESENCE_AWAY_FACTOR   = "presence_away_factor"    # 0.0–1.0 multiplier when nobody home

DEFAULT_PRESENCE_EXTRA_WATTS  = 80.0    # W per person (lights, devices they use)
DEFAULT_PRESENCE_AWAY_FACTOR  = 0.6     # when away: only 60 % of time profile (standby)

# ── Misc ──────────────────────────────────────────────────────────────────────
DEFAULT_SCAN_INTERVAL   = 30    # seconds

# ── State attributes ──────────────────────────────────────────────────────────
ATTR_CURRENT_POWER_W        = "current_power_w"
ATTR_PROFILE_POWER_W        = "profile_power_w"
ATTR_PRESENCE_POWER_W       = "presence_power_w"
ATTR_SMART_PLUG_POWER_W     = "smart_plug_power_w"
ATTR_SENSOR_BREAKDOWN       = "sensor_breakdown"
ATTR_ACTIVE_PERSONS         = "active_persons"
ATTR_PERSONS_HOME           = "persons_home"
ATTR_CURRENT_TIME_SLOT      = "current_time_slot"
ATTR_LAST_CALIBRATION       = "last_calibration"
ATTR_UNAVAILABLE_SENSORS    = "unavailable_sensors"

# ── Services ──────────────────────────────────────────────────────────────────
SERVICE_SET_METER   = "set_meter_value"
SERVICE_CALIBRATE   = "calibrate"
ATTR_KWH_VALUE      = "kwh_value"
