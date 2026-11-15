# Signals (S7.1)

Every source of events that might be worth telling the owner publishes one normalised
**Signal**. Nothing on this page speaks to the owner: delivery (scoring, presence, quiet
hours, gaming mode, the "Don't tell me about this again" mute) is the proactive engine
(S7.2, not built yet). Code: `backend/services/signals.py`, route:
`backend/transport/signals.py`, tests: `tests/test_signals.py`.

## The Signal

A frozen dataclass:

| Field | Meaning |
| --- | --- |
| `kind` | One of the kinds below; anything else is refused. |
| `source` | The producer (`calendar`, `weather`, `battery`, `calls`, `cad`, `image`, `web`). |
| `at` | When it happened (aware datetime). |
| `title` | One line for the owner (at most 160 characters). |
| `body` | Optional detail (at most 500 characters). |
| `data` | Read-only mapping of facts for the engine (ids, times, flags). |
| `urgency` | 0 FYI, 1 worth a mention, 2 soon, 3 now. |
| `dedupe_key` | Repeats of the same key are dropped while the first is live. |
| `expires_at` | After this the signal is dropped (aware datetime). |
| `person_id` | The matched person from the people list (P1), when known. |

`signal(kind, source, title, *, at, dedupe_key, expires_at=None, ttl=None, ...)` builds one;
without `expires_at` it lives `ttl` (default one hour).

Kinds: `calendar.soon`, `weather.rain_soon`, `call.missed`, `call.vip`,
`message.received`, `job.finished`, `home.state`, `home.alert`, `homelab.alert`,
`system.battery`, `routine.due`.

## The hub

`app.signals` (`SignalHub`):

- `publish(signal)` returns True when the signal was accepted. It drops an expired signal and
  a `dedupe_key` already seen while that earlier signal is live (an acknowledged signal
  still counts as seen). Accepted signals go on `app.bus` under `signal` and
  `signal.<kind>` with `data={"signal": Signal}` (fire-and-forget, `emit_nowait`).
- `pending()`: the live, unacknowledged signals, oldest first; at most 100 (newest kept).
- `ack(dedupe_key)`: takes one off the pending list.
- Everything is in memory: a restart starts empty.

Logs carry the kind, source and urgency only (`Signal call.vip from calls (urgency 2)`),
never a title, body, name, place or `data` value. Producer failures log the exception type
only.

## Producers

Each is a small class with `start()` / `stop()`; `SignalProducers` starts them all in
`Application.start()` and stops them first in `Application.close()`. Polling producers wait
30 s after start, then poll on their interval, and skip every poll while
`app.resources.state == "gaming"` (resident/tray mode keeps polling).

| Producer | Schedule / trigger | Signal |
| --- | --- | --- |
| Calendar | Every 60 s; today's events re-read at most every 5 min through `voice_quick.today_events` (calendar connected, `read_events` switch, `calendar_read` permission that never asks). | `calendar.soon` for timed events: T-30 (urgency 1), T-10 (urgency 2); "Design review in 30 minutes". Once per event and offset (`calendar.soon:<event id>:<30\|10>`); an event first seen inside 10 minutes gets only T-10. Expires at the start. `data`: `event_id`, `start` (ISO), `location?`. |
| Weather | Every 15 min, only with `assistant.home_place` (no home town: no request). `WeatherService.rain_soon()`: one hourly Open-Meteo request (`precipitation_probability,precipitation`, `forecast_hours=3`), cached 10 min like the forecast, same timeouts. | `weather.rain_soon` (urgency 1) when an hour in the next 2 hours has a chance of at least 60% or at least 0.5 mm. Once per rain spell: a later poll that sees the same run of rainy hours stays quiet; a dry poll after the spell ends re-arms. Key `weather.rain_soon:<date>:<start hour>`. |
| Battery | Every 2 min, `psutil.sensors_battery()` (in a thread). | `system.battery` while discharging: 20% (urgency 1), 10% (urgency 2); once each per discharge, plugging in re-arms; a drop straight past both gives only the 10% one. |
| Calls | The bus event `call_record_ready` (`telephony/agent.py`), then the stored record. | Inbound screening records only (outbound, task calls, blocked callers and spam skipped). A VIP's call is `call.vip` (urgency 2, "Aisyah called" / "Missed call from Aisyah", the triage summary as body when ready); anyone else's missed call is `call.missed` (urgency 1). `person_id` is the record's `contact_id`. One signal per record: the VIP's second announcement after triage is a repeat. |
| Jobs | Chained onto `CadService.on_update` and `ImageService.on_update` (after the live design's own hook) and around `BrowserService.runner`; acts only while started. | `job.finished`: `succeeded` (urgency 1) and `failed` (urgency 2); cancelled and interrupted jobs say nothing. `data`: `job`, `request_id`, `state`, `project?`, and for CAD `live` (the owner's live design's job). |

## Route

`signals_pending {}` (owner-only renderer, unlocked; debug for the later Activity view):
`{ok: true, signals: [{title, kind, urgency, at}]}`, newest first. Read only. Listed in
`docs/ROUTE_POLICY_MATRIX.json`.

## Not built yet

- The proactive engine, heartbeat and routines (S7.2+): nothing is delivered to the owner.
- Calendar travel time to the event's place.
- Producers for `home.state` / `home.alert` (S12 WebSocket), `homelab.alert` (S12),
  `message.received` (channels, S8) and `routine.due` (routines).
- Task-queue plans (multi-step desktop tasks) as `job.finished`.
- Persistence: pending signals and dedupe keys do not survive a restart.
