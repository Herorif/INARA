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

## Diagnostics export (S4.2)

The builder cannot read the owner's AppData, so JARVIS can pack what a bug report needs
into one zip. Export it from the tray ("Export diagnostics": a balloon says "Saved to
<folder>") or from Preferences > Diagnostics ("Export diagnostics"; the saved path is shown
under the button). The service is `backend/services/diagnostics.py` (`DiagnosticsService`,
wired as `app.diagnostics`); the route is `backend/transport/diagnostics.py`.

### Where it goes

`diagnostics-<YYYYMMDD-HHMMSS>.zip` (a second export in the same second adds `-1`) in the
folder named by `diagnostics.folder`. Empty (the default) means:

- in a dev checkout (no `desktop-pilot.json` at the repo root, the same marker
  `backend/resident/layout.py` reads): `<repo>\.runtime\live-logs`;
- otherwise: `%USERPROFILE%\Documents\JARVIS diagnostics`.

`diagnostics.folder` accepts an absolute path (up to 240 characters) or `""`, through
`update_settings` as `{diagnostics: {folder: "D:\Support"}}`.

### What the zip contains

| File | Contents |
| --- | --- |
| `log.txt` | The last 2,000 lines of `<user data>\logs\jarvis.log`, preceded by `jarvis.log.1` when the current file is shorter |
| `turn_timing.txt` | Every `turn_timing` and `brain_check` line in those files |
| `settings.json` | The settings snapshot, redacted (below) |
| `keys.json` | `[{name, configured}]` for every secret JARVIS knows; never a value or a hint |
| `versions.json` | App version, Python, OS and build, Electron (Node is not known to the core: `null`), whether this is a dev checkout, and the anthropic, google-genai, httpx and websockets versions |
| `sidecars.json` | State strings for world view, each MCP server (`{id, state}`), the CAD kernel (`running`, `available` or `unavailable`), the wake word and tray voice |
| `audio.json` | Microphone and speaker names from the device list, and the chosen ones (`default` or a name) |
| `traces.json` | The last 20 flight-recorder traces. `request_text`/`answer_text` only while `diagnostics.include_text` is on at export time |

### What is removed

In `settings.json`:

- the value of every key whose name contains a word starting or ending with token, key,
  secret, password, auth, cookie or pin (`api_key`, `authToken`, `pairing_pin`); a
  true/false value is kept;
- phone numbers (nine or more digits with phone punctuation) in any text value;
- `assistant.owner_name`, `assistant.home_place` and `calls.facts`.

Then a last pass over every file in the zip replaces with `[removed]`:

- Anthropic (`sk-ant-…`) and Google (`AIza…`, `AQ.…`) keys, `Bearer …` tokens;
- runs of 32 or more base64/hex characters that mix letters and digits (UUIDs, such as
  trace ids, are kept);
- email addresses;
- the owner's name and home place, and each of their words of three letters or more.

The log records the number of replacements only. Key values are never read into the zip.

### Route

`diagnostics_export {}` (owner-only, unlocked renderer) answers `{ok: true, path}`, or
`{ok: false, code, message}` with `authentication_required`, `permission_denied`,
`invalid_arguments` or `diagnostics_failed`. One export runs at a time.
