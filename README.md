# Simulated Energy Meter

A Home Assistant custom integration that simulates an energy meter based on:

- **Smart plug power sensors** (live Watt readings)
- **Time-of-day profiles** (Morgen / Tag / Abend / Nacht)
- **Presence detection** via `person.*` entities
- **Adaptive learning** — profiles auto-adjust after each calibration

## Installation via HACS

1. HACS → Integrations → ⋮ → Custom repositories
2. Add: `https://github.com/YOURUSERNAME/simulated_energy_meter`
3. Category: **Integration**
4. Install → Restart HA

## Manual Installation

Copy `custom_components/simulated_energy_meter/` into your HA `config/custom_components/` folder and restart.

## Setup

Settings → Integrations → Add → **Simulated Energy Meter**

Enter your current real meter reading (kWh), select your smart plug power sensors, configure time-of-day profiles and presence persons.

## Calibration & Learning

Call the service `simulated_energy_meter.calibrate` with your current real meter reading.
The system automatically adjusts profiles based on the drift — slot-targeted learning kicks in after 3 calibrations.

```yaml
service: simulated_energy_meter.calibrate
data:
  kwh_value: 4923.441
```
