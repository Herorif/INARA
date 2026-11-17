# Routines (S7.4)

A routine is a named list of up to 12 tool steps that JARVIS runs in order when the owner
says a phrase, at a time of day, or when a signal comes in. Every step goes through the same
`ToolDispatcher.dispatch` a brain turn uses, so approvals, deny and the taint rule are never
bypassed.

Code: `backend/services/routines.py` (store, runner, triggers, brain tools),
`backend/transport/routines.py` (owner-only routes), `backend/agents/scheduler_agent.py`
(routine timers), `src/features/routines/` (the Routines page under Tasks). Tests:
`tests/test_routines.py`, `tests/test_routines_model.mjs`.

## Storage

Table `routines` in the core database (`assistant.sqlite3`), migration `routines:v1`:

| column | |
| --- | --- |
| `id` | UUID |
| `name`, `trigger`, `steps` | DPAPI ciphertext (`Database.encode`, scoped `routine:<id>:<field>`) |
| `enabled` | 0 or 1 |
| `created_at`, `updated_at`, `last_run_at` | ISO UTC |
| `last_outcome` | DPAPI ciphertext, or NULL before the first run |

At most 100 routines. Names are unique (case and spacing ignored). An enabled routine's
phrases are its own: saving or turning on a routine whose phrase another enabled routine
already uses is refused (`routine_conflict`).

## Triggers

```json
{"type": "phrase", "phrases": ["movie time", "masa wayang"]}
{"type": "schedule", "at": "07:30", "repeat": "daily" | "weekdays" | "weekly", "day": "mon"}
{"type": "signal", "kind": "calendar.soon", "filter": {"minutes": 10}}
```

- **Phrase.** 1-5 phrases of up to 80 characters. Before every conversation reply
  (`ConversationService.reply`, wrapped in `application.py`; the conversation's `on_request`
  hook only receives the owner, so it can't see the text or stop the turn), an owner request
  whose normalised text is exactly one of an enabled routine's phrases starts that routine in
  the background and answers **"Running Movie time."** without starting a brain turn. Normalising
  casefolds, turns punctuation into spaces, collapses spaces, and drops a leading "Jarvis" /
  "hey Jarvis" and a trailing "please" / "tolong" / "Jarvis". The whole request must be the
  phrase ("is it movie time yet" does not match). Phrases match as written, English or Malay;
  nothing is translated. Turns from other people (`channel` phone_call, telegram, whatsapp)
  never match. Typed chat, tray and workspace voice (`ask_brain`), speech and Show JARVIS all
  pass through the same reply. The phrase exchange is not added to the conversation history.
  A phrase for a routine that is already running answers "Movie time is already running."
- **Schedule.** The `SchedulerAgent`'s routine timers (`schedule_routine`, `cancel_routine`,
  `close_routines`) on the calendar its recurring reminders use: every day, Monday to
  Friday, or one weekday, at `HH:MM` in Asia/Kuala_Lumpur (DST-safe through
  `local_instant`). Nothing is stored as a reminder and nothing shows in the Reminders list.
  A timer wakes at least every 30 s, so a clock jump is noticed; a run more than 10 minutes
  late (the PC was asleep) is skipped and logged, and the timer waits for the next time.
  Cron expressions and one-off dates are not supported (the scheduler has neither).
- **Signal.** The runner subscribes to the bus topic `signal` (`services/signals.py`). A
  routine runs when the signal's kind matches and every filter field equals the signal's
  field: its `data`, plus `source`, `urgency` and `person_id`. Equality is on plain values
  (`10` and `"10"`, `true` and `"true"`, `"KL"` and `"kl"` are equal); at most 5 fields.
  `calendar.soon` carries `data.minutes` (30 or 10), so `{"minutes": 10}` is "When an event
  starts in 10 minutes". A signal raised by someone else (`call.missed`, `call.vip`,
  `message.received`) starts its run tainted with "a phone caller" / "a message from someone
  else", so outward steps ask.

Schedule and signal triggers are **skipped in gaming mode** (`resources.state == "gaming"`):
the skip is logged with the routine's id and recorded as the last outcome
(`{"state": "skipped", "reason": "gaming"}`). Run now and the brain's `routine_run` still
work in gaming mode; each step's own gaming rules still apply.

## Steps

```json
[{"tool": "home_control", "args": {"entity_id": "light.living", "action": "turn_off"},
  "say": "Enjoy the film."}]
```

- 1 to 12 steps. `tool` must be one of the brain's model-visible tools at save time;
  `routine_run` and `routine_save` can never be steps (no recursion). `routine_list` may be.
- `args` must fit the tool's own pydantic model (checked at save and again by the dispatcher
  at run time); at most 4000 characters of JSON.
- `say` (optional, at most 200 characters) is spoken after the step works, as a Live text
  turn in the owner's running voice session. With no voice session it is not spoken.

## Running

`RoutineRunner` runs the steps in order with the owner's context (`principal`, the current
project or the turn's, the origin socket, the conversation, and the run's taint):

- **Approvals.** Each step is a full dispatch: its stored policy, `always_ask`, `ask_when`,
  `deny` and the taint rule apply. The approval card is the step's own card (with `routine`
  set to the routine's name in the payload). A phrase run's approvals go where the turn's
  would; Run now's go to the window that pressed it; `routine_run`'s go to the turn's
  approver. A schedule or signal run sends the card to every open workspace window of the
  owner; with none open it **waits** (polling every 2 s, up to 30 minutes) until one opens,
  then the dispatcher's usual approval timeout applies.
- **Taint.** A run starts with the taint of whatever started it (a tainted brain turn for
  `routine_run`; the signal's source for someone else's signal; empty for the owner's phrase,
  Run now and schedules). A step whose tool has `untrusted_output` adds its source, so later
  outward steps ask.
- **Stops** at the first step that raises (`ServiceError`, invalid arguments, any error), that
  answers `{success: false}`, `{ok: false}` or `{error: ...}`, or whose approval is declined.
- **One run per routine at a time.** A second start answers `routine_running`; a schedule or
  signal trigger during a run is skipped and logged.
- **Outcome**, stored as `last_outcome` with `last_run_at`:
  `{state, origin, steps, done, started_at, finished_at, step?, tool?, code?, message?}`.
  `state` is `running`, `ok`, `failed`, `declined`, `skipped` or `interrupted` (the core
  stopped mid-run; a `running` record left by a crash becomes `interrupted` at the next
  start). `origin` is `phrase`, `schedule`, `signal`, `manual` or `brain`.
- After every change and run state, `routines_changed {id}` (content-free) goes to the
  owner's renderers; the page reloads its list.

## Brain tools

| tool | asks | notes |
| --- | --- | --- |
| `routine_run(name)` | never itself (`permissions.routine_run` default `False`) | Runs and waits; returns `{routine, state, steps_done, steps, outcome}` in plain words. Long running; 900 s timeout. |
| `routine_save(name, trigger, steps)` | always (`always_ask`) | Saving an existing name replaces it. The card lists the name, the routine it replaces, the trigger and each step in plain words ("1. Home control: entity_id light.living, action turn_off. Says 'Enjoy the film.'"). An invalid routine is refused before any card. |
| `routine_list()` | never (`permissions.routine_list` default `False`) | `[{name, trigger, enabled, steps, last_run_at, last_outcome}]`, trigger and outcome in plain words. |

All three are for the authenticated desktop owner only (`authorize_owner`). Defaults are in
`backend/server.py`.

## Routes (owner renderer, unlocked)

| route | request | answer |
| --- | --- | --- |
| `routines_list` | `{}` | `{ok, routines}` sorted by name |
| `routines_tools` | `{}` | `{ok, tools: [{name, description, parameters}]}`: the model-visible tools a step may use |
| `routines_save` | `{id?, name, trigger, steps, enabled?}` | `{ok, routine}` |
| `routines_delete` | `{id}` | `{ok, deleted}` (refused while it runs) |
| `routines_toggle` | `{id, enabled}` | `{ok, routine}` |
| `routines_run` | `{id}` | `{ok, started}`; the run continues in the background |

Errors are `{ok: false, code, message}` with codes `invalid_arguments`, `routine_conflict`,
`routine_not_found`, `routine_running`, `routines_full`, `routines_unavailable`,
`authentication_required`, `permission_denied`. See `docs/ROUTE_POLICY_MATRIX.json`.

## The Routines page

Tasks > Routines (the `routines` feature, `showRoutineWindow`). The list shows each
routine's name, trigger in plain words, step count, the last run and its outcome, an on/off
switch, Run now, Edit and Delete (with an inline confirm). The editor has the name, the
trigger type and its fields (phrases separated by commas; time, repeat and day; the signal
kind, "10 / 30 minutes before" for calendar events and an optional JSON filter), and the
ordered steps: a tool picker from `routines_tools`, a small JSON arguments box checked
against the tool's schema, and an optional line to say; steps can be added, removed and moved
up or down. Everything is keyboard reachable; Escape cancels the editor and the delete
confirm. Text is 12 px or larger. Logic lives in `routinesModel.js`.

## Privacy

Names, phrases, step arguments and say lines are encrypted at rest and never logged. Logs
carry the routine id, the trigger origin, the state, step counts and error codes only.
