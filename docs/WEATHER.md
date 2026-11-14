# Weather

JARVIS answers weather questions itself, with no key and no globe: `backend/services/weather.py`
(`WeatherService`) asks Open-Meteo for the current conditions and a 7-day daily forecast.

## The brain's `weather` tool

`weather(place?: str, when: "now" | "today" | "tomorrow" | "week" = "today", remember_as_home: bool = false)`

- Permission `weather`, default `False`: it never asks. `"deny"` turns it off.
- No `place`: it uses the owner's home town (`assistant.home_place`). With no home town it
  answers `{"need_place": true, "message": ...}`, and the brain asks the owner once, then
  calls again with `place` and `remember_as_home=true`, which saves the resolved place as the
  home town (owner only).
- Answer: `place` {name, country, lat, lon}, `now` {temp, feels_like, humidity,
  precipitation, condition, wind_kmh}, `days` [{date, condition, min, max, rain_chance}]
  (none for `now`, one for `today` and `tomorrow`, seven for `week`), `units`, `when` and
  `source: "Open-Meteo"`. Conditions are plain words from the WMO weather codes.
- Failures are answers, never exceptions: `{"error": "unavailable", "message": ...}` when
  Open-Meteo can't be reached, times out or answers oddly; `{"error": "not_found", ...}`
  for an unknown place.
- 6 s per request, 9 s per lookup, 10 s tool timeout. Answers are cached in memory for
  10 minutes per place name and per coordinates.

`WeatherService.lookup(place, when)` and `summary_line(result)` (one or two spoken sentences,
e.g. "Kuala Lumpur: 31°C, feels like 36, light rain; today 25 to 33 with a 70% chance of
rain.") are public so the voice layer's quick answers can reuse them.

Requests carry only the place name or coordinates. Logs carry codes only, never places.

## Home town

- Setting `assistant.home_place`: `{name, lat, lon}` or `null` (default). The name is at most
  120 printable characters (for example "Kuala Lumpur, Malaysia"); lat is -90..90 and lon
  -180..180. It is validated on every patch and re-checked when read.
- Preferences > AI > Assistant > **Home town**: type a town, Save, and the row shows the
  resolved place or "Not set".
- RPC `weather_home_set {place: str | null}` (owner renderer only): geocodes the place and
  saves it, or clears it with `null`. Answers `{ok, home_place}` or `{ok: false, code,
  message}` (`not_found`, `weather_unavailable`, `invalid_arguments`).

## Source and licence

Weather data by [Open-Meteo.com](https://open-meteo.com/) (CC BY 4.0), geocoding from
GeoNames through Open-Meteo. Endpoints:

- `https://geocoding-api.open-meteo.com/v1/search?name=<place>&count=1&language=en`
- `https://api.open-meteo.com/v1/forecast?latitude=..&longitude=..&current=...&daily=...&timezone=auto&forecast_days=7`

The free API is for **non-commercial use only**. **Flag for release (M5):** a commercial or
public release needs an Open-Meteo API plan (or another provider), and the attribution above
shown in the app.
