# Systems rail

The right-hand context inspector shows the **Systems rail** (S13a.5): always-true facts about the
owner's day and this PC. It replaced the inspector's old SYSTEM and TODAY panels; the panel, its
open/close toggle (title bar, "Context inspector") and its width are unchanged, and the presence
panel still sits above it outside the Assistant view.

Code: `src/app/SystemsRail.jsx`, `src/app/systemsRail.css`, the pure `src/app/systemsRailModel.js`
(tested by `tests/test_systems_rail.mjs`); the core side is `backend/services/vitals.py` and the
routes in `backend/transport/vitals.py` (tested by `tests/test_vitals.py`).

## Sections and sources

Each section hides when it has no source. Order:

| Section | Shows | Source | Refresh |
|---|---|---|---|
| Now | Clock (HH:MM) and date ("Sunday 15 November") | The renderer's clock | Each minute boundary |
| Weather | One line for the home town ("Kuala Lumpur: 31°C, feels like 36, light rain.") | `weather_now` → `WeatherService.lookup(None, "now")` and `summary_line` | Every 15 min while visible, and after a `settings` update (a new home town) |
| Next | The next timed calendar event today with a countdown ("Design review in 42 min"), then the reminders due today (count and the first one) | `agenda_next` → the same reads as the voice `quick_agenda` (`CalendarService.today_events`, the reminder store, the briefing's `reminder_items`) | Every minute while visible, and when the renderer's reminder list changes; the countdown re-renders each minute |
| Home | The one-line home summary | `home_summary` → `voice_quick.home` (`HomeAssistantService.list_for_brain` shaped by `home_summary`) | Every minute while visible |
| This PC | CPU, memory and network with 120×24 sparklines of the last 60 samples; disk (system drive) and battery as plain values; GPU only when NVML is present | `vitals` events while the rail watches (`vitals_watch`) | Every 2 s, every 5 s on low battery |
| Jobs | Running creative jobs (name and phase) in this project | The renderer's activity list (`cad_job` / `image_job`) | Live |
| JARVIS | Resource mode, voice and workspace memory | Unchanged from the old SYSTEM panel | Live |

Hidden when: no home town (Weather); no upcoming timed event today and no reminders due, or the
calendar is not connected, its "read events" switch is off, or the permission is not "never ask"
(Next); Home Assistant not connected or the summary not readable (Home); no samples yet (This PC,
except in gaming mode); no running job (Jobs). Offline, only Now and JARVIS show.

## Routes and events

All four routes are owner-only (authenticated, unlocked desktop owner renderer), never brain
tools, and listed in `docs/ROUTE_POLICY_MATRIX.json`.

- `vitals_watch {on: bool, low_battery?: bool}` → `{ok, watching, paused, interval}`.
- `weather_now {}` → `{ok, home: false}` or `{ok, home: true, line, temp, condition}`.
- `agenda_next {}` → `{ok, calendar, event: {title, time, at} | null, reminders: {count, first: {title, time}} | null}`; `at` is epoch seconds. Titles and times only: no places, attendees or notes.
- `home_summary {}` → `{ok, connected, line}`.
- Event `vitals` (to watching owner renderers only):
  `{t, cpu, mem: {used, total}, disk: {used, total}, net: {up, down}, battery?: {percent, plugged}, gpu?: {percent}}`.
  `t` epoch seconds; `cpu` and `percent` in %; bytes for memory and disk; bytes per second for the network.

## Sampling rules

- The core samples only while at least one owner renderer watches. The renderer watches while the
  rail is mounted (the inspector is open), the window is visible and the core is connected; it
  sends `{on: false}` when it closes, hides, or enters gaming mode. Disconnect drops the watch.
- **Gaming mode:** the renderer stops watching and shows "Paused in gaming mode" for This PC; the
  core also takes no samples while the resource state is gaming, even with a watcher.
- **Low battery:** the renderer passes its Battery API reading (discharging at 20% or less) as
  `low_battery`; the core samples every 5 s when any watcher says so or when its own reading shows
  the PC discharging at 20% or less, else every 2 s.
- **Reduced motion:** nothing on the rail animates; values just update.
- **GPU:** read through `pynvml` (`nvidia-ml-py`) only if it is already importable. It is not
  installed and JARVIS never installs it.

## Privacy

Everything is local: psutil reads this PC; weather is the existing Open-Meteo lookup (no key,
cached 10 minutes); calendar, reminders and Home Assistant are the reads JARVIS already makes for
the voice quick answers. Nothing is stored. Nothing is logged: not the vitals, not event or
reminder titles, not places or device names (failures log only an exception type). Samples go to
the watching owner renderer only, never to the phone, the overlay or the brain.
