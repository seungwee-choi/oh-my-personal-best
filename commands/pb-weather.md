---
description: "Weather-aware running advice — forecast, air quality, adjust today's run"
---

# pb-weather

## Dispatch

Invoke the `oh-my-personal-best:pb-weather` skill. It routes to `session-coach`, which reads the
runner's local forecast + air quality (`ompb_core.weather_forecast`) and folds the conditions into
today's session (heat/humidity → earlier + easier + fluids; high AQI → indoors/substitute).

If no location is set, ask once for a city/area and store it; if none is given, prescribe normally
without weather (never surface the absence as a limitation).

Pass any context from the runner as:

```text
$ARGUMENTS
```
