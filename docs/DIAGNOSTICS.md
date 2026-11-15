# Diagnostics

## Flight recorder (S4.1)

JARVIS keeps a short record of what it did in each recent turn, so a slow or failed
answer can be explained without reading logs. The recorder is
`backend/services/trace.py` (`TraceService`, wired in `backend/application.py` as
`app.trace`).

### What it keeps

One trace per turn:

- every brain turn: desktop chat, voice `ask_brain`, phone chat and Show JARVIS;
- every voice exchange Gemini Live answered on its own: a quick answer (weather, agenda,
  home) or a reply Live gave without the brain.

Each trace has:

| Field | Meaning |
| --- | --- |
| `id` | The turn's request id (a new id for a Live-only exchange) |
| `origin` | `chat`, `voice`, `phone` or `vision` |
| `started_at` | ISO time the turn started (UTC) |
| `provider`, `model`, `effort` | The brain that answered (`gemini_live` for Live-only) |
| `outcome` | `ok`, `budget`, `error`, `cancelled` (brain); `ok`, `interrupted` (Live-only) |
| `total_ms`, `first_token_ms` | Turn length and the time to the first streamed content |
| `spans` | `{kind, name?, start_ms, ms, outcome}`; kinds `wake`, `speech_in`, `model`, `tool`, `approval`, `speech_out` |
| `tokens` | `{input, output}` summed over the turn's model steps (null for Live-only) |
| `cost_usd` | List-price estimate from `llm/pricing.py`, or null when the model is not priced |
| `approvals` | `{tool, asked_ms, answer}` with `answer` `approved`, `denied` or `timeout` |

`start_ms` is relative to the trace's start. For a voice brain turn that is the brain
turn's start, so the speech that came before it (`wake`, `speech_in`) has a negative
`start_ms`. A `speech_out` span named `progress` is a progress line JARVIS said while the
brain was still working. `wake` (on the first exchange of a "Hey Jarvis" session) runs
from the detection to Live being ready.

Tool names are kept. Message text, tool arguments, places and people's names are not.

### Including text

`diagnostics.include_text` (a setting, default **off**; changed through
`update_settings` as `{diagnostics: {include_text: true}}`). When it is on, each
new trace also has `request_text` and `answer_text`, each cut to 500 characters. Traces
recorded while it was off never gain text. Turn it off again and new traces have none.

### Retention

Memory only: the last 200 turns. Nothing is written to disk, and a restart clears the
list. `trace_clear` empties it on demand.

### Routes and events

Owner-only, unlocked renderer (see `docs/ROUTE_POLICY_MATRIX.json`):

- `trace_recent {limit?}` (1-200, default 50) answers `{ok: true, traces}`, newest first.
- `trace_clear {}` answers `{ok: true}`.

`trace_added {id, origin, outcome, total_ms}` goes to the owner's renderers whenever a
trace is recorded or updated. A voice brain turn is announced twice: when the brain
finishes and again when its speech spans arrive (same `id`; replace the row).

### Failure handling

Tracing never breaks a turn or a voice session. A hook that fails logs one warning with
the exception type only, never the text.
