"""Constants for Simulated Energy Meter."""

DOMAIN = "simulated_energy_meter"

# ── Basic config ──────────────────────────────────────────────────────────────
CONF_INITIAL_KWH            = "initial_kwh"
CONF_POWER_SENSORS          = "power_sensors"

# ── Time-of-day profiles ──────────────────────────────────────────────────────
CONF_PROFILE_MORNING        = "profile_morning"     # 06:00–09:59
CONF_PROFILE_DAY            = "profile_day"         # 10:00–17:59
CONF_PROFILE_EVENING        = "profile_evening"     # 18:00–22:59
CONF_PROFILE_NIGHT          = "profile_night"       # 23:00–05:59

DEFAULT_PROFILE_MORNING     = 120.0
DEFAULT_PROFILE_DAY         =  80.0
DEFAULT_PROFILE_EVENING     = 200.0
DEFAULT_PROFILE_NIGHT       =  50.0

# ── Presence ──────────────────────────────────────────────────────────────────
CONF_PRESENCE_PERSONS       = "presence_persons"
CONF_PRESENCE_EXTRA_WATTS   = "presence_extra_watts"
CONF_PRESENCE_AWAY_FACTOR   = "presence_away_factor"

DEFAULT_PRESENCE_EXTRA_WATTS  = 80.0
DEFAULT_PRESENCE_AWAY_FACTOR  = 0.6

# ── Learning system ───────────────────────────────────────────────────────────
LEARNING_MIN_CALIBRATIONS   = 3        # need at least this many before slot-targeted learning
LEARNING_DAMPING            = 0.4      # how strongly one calibration shifts profiles (0–1)
LEARNING_MAX_CORRECTION_PCT = 0.40     # max ±40 % change per calibration
LEARNING_MIN_SLOT_HOURS     = 0.5      # ignore slots with < 30 min data (too little signal)

# ── Misc ──────────────────────────────────────────────────────────────────────
DEFAULT_SCAN_INTERVAL       = 30       # seconds

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
ATTR_CALIBRATION_COUNT      = "calibration_count"
ATTR_LEARNING_MODE          = "learning_mode"
ATTR_LAST_DRIFT_KWH         = "last_drift_kwh"

# ── Services ──────────────────────────────────────────────────────────────────
SERVICE_SET_METER           = "set_meter_value"
SERVICE_CALIBRATE           = "calibrate"
ATTR_KWH_VALUE              = "kwh_value"
