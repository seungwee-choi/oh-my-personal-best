---
name: pb-weather
description: Weather-aware running advice — forecast, air quality, and how to adjust today's run
level: 3
---

<Purpose>
pb-weather brings the runner's local forecast and air quality into the coaching loop so a session
is prescribed for the conditions, not in a vacuum — shift a quality session earlier in a heatwave,
add fluids and drop intensity in humidity, move indoors on a high-AQI day. It's a live query
(Met.no forecast + Open-Meteo air quality), cached 2h, layered on top of `session-coach`.
</Purpose>

<Use_When>
- "오늘 뛰기 어때?", "지금 달려도 돼?", "날씨 보고 조정해줘", "what's it like to run today?"
- Before today's session when conditions might matter (heat, cold, rain, dust/미세먼지)
</Use_When>

<Do_Not_Use_When>
- No location is set and the runner doesn't want to give one → skip weather silently; prescribe
  normally. Never surface "weather unavailable" as a coaching limitation.
</Do_Not_Use_When>

<Routing>
Delegate to `oh-my-personal-best:session-coach`, which reads `ompb_core.weather_forecast(home)` +
`weather_advise(...)` as an input to today's prescription.
</Routing>

<Steps>

## Step 1 — Resolve location (once)
`ompb_core.weather_forecast(home)` reads the location cached in `config.json` (`wx_*`). If none is
set, ask the runner for a city/area once and store it:
```
python3 "$CLAUDE_PLUGIN_ROOT/scripts/weather.py" set-location --place "<city/area>"
```
(Geocodes the place; lat/lon/tz optional.)

## Step 2 — Fetch + advise
```
python3 "$CLAUDE_PLUGIN_ROOT/scripts/weather.py" forecast
```
Returns today's forecast (temp, apparent temp, humidity, precip, wind, WMO condition) + air quality
(PM2.5 / AQI). `weather_advise(day, workout_type)` turns it into a running adjustment.

## Step 3 — Fold into the session
session-coach combines the advice with the planned session and the injury guardrail: heat/humidity →
earlier start, lower intensity, more fluids; cold → warm-up longer; high AQI → quality indoors or
substitute. Keep it one or two concrete lines — actionable, not a weather report.

</Steps>

<Stop_Conditions>
- `$CLAUDE_PLUGIN_ROOT` unset → run `python3 scripts/weather.py …` from the repo.
- Network unavailable / forecast fails → prescribe normally without weather; don't block the session.
</Stop_Conditions>
