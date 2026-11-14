# 9NovWork — build specs (S1–S16)

Each section is self-contained: goal, libraries, file layout, data, tools, settings, UI,
tests, done-when, risks. Read section 0 once, then only the section you are building.
Tags: **[repo]** checked in code, **[web]** web search Nov 2026, **[recall]** unverified —
confirm the API in the package itself before writing code against it.

---

## 0. How this repo is built (pattern card) [repo]

**Stack.** Python 3.13 core (socket.io server on port 8000) · Electron 44 + React 18.2 +
zustand + Tailwind 3.4 + three 0.160 / react-three-fiber renderer · a resident tray host
(`backend/resident/host.py`, `win32.py`) · an overlay Electron app (`electron/overlay-*`,
`src/overlay`) · sidecars and workers.

**Add a backend feature.**
1. Service: `backend/services/<name>.py`, class `XService(app)`.
2. Socket RPCs: `backend/transport/<name>.py`, class `XTransport(app)`.
3. Wire both in `backend/application.py` (`self.x = XService(self)`,
   `self.x_transport = XTransport(self)`), next to similar services.
4. Every new RPC goes into `config/ROUTE_POLICY_MATRIX.json` (tests enforce it).
5. Brain tools: `ToolSpec(name, description, ArgsModel, execute, execution_timeout=,
   permission=, model_visible=True, review=, always_ask=False, ask_when=None)` from
   `backend/services/tools.py`. Args are pydantic models. Copy the registration pattern
   in `backend/services/world_tools.py` (near line 402) or `home_assistant.py`.
   - `always_ask=True`: the owner approves every call.
   - `ask_when(validated, context) -> bool`: per-call approval (per device, per recipient).
   - `review(validated, context) -> dict`: extra facts on the approval card.
6. Settings: `backend/services/settings.py` — add an `X_DEFAULTS` dict, register it in the
   defaults merge (near line 821) and in the list of patchable top-level keys (near 846).
7. Secrets: `backend/services/secrets.py` `SecretSpec` (owner-facing or internal). Never
   pass a secret in argv or write it to a log; hand it to child processes over stdin or env.
8. Events to the UI: `self.app.sio.emit(event, payload, room=...)`; jobs through
   `EventDelivery` (`backend/transport/delivery.py`). An in-process bus exists (`app.bus`).
9. Outbound HTTP: `httpx` with `services.tls.provider_ssl_context()` (Avast-safe).

**Add a sidecar (external program).** Copy `backend/services/world_view.py`: start on
demand, health check, idle stop, pause in gaming mode, loopback only. If it speaks MCP,
register it as a built-in server in `backend/services/mcp_registry.py` (like `gev`) and it
is reached through `backend/services/mcp_client.py` (stdlib JSON-RPC over stdio). Tools
appear to the brain as `mcp__<id>__<tool>` with a policy of `never_ask`, `ask` or `deny`.
Node sidecars use the portable Node 24 at `C:\Users\nojiq\tools\node-v24.22.2-win-x64`
with `NODE_USE_SYSTEM_CA=1`. npm 11 does not run install scripts by default.

**Add an isolated Python worker.** Copy `backend/workers/cad_worker.py`: JSON lines over
stdin/stdout, its own interpreter, timeout, kill the process tree on cancel.

**Add UI.** Feature folder `src/features/<name>/` (JSX + one CSS file + a pure
`*Model.js` with the logic, tested without React). Navigation: `src/app/workspaceNavigation.js`
and `src/app/features.js`. Tokens: `src/app/tokens.css`. Primitives: `src/shared/ui/`.
Core: `src/app/JarvisCore.jsx`, `coreScene.js`, `PresenceRing.jsx`. Voice stage:
`src/app/stageModel.js`, `useVoiceStage.js`. Settings pages: `src/features/settings/`.

**Verify.** ruff, eslint, tsc, pytest, client tests, `npm run build` (CSP intact),
harnesses `scripts/verify-*` under the QA lock, captures in `.runtime/ui-qa/<feature>/`.
Tests live in `tests/` (pytest; there is no `backend/tests`). They use fakes for
network, audio and camera; nothing binds port 8000.

**Installed in the core `.venv` [repo, 14 Nov 2026].** Python 3.13.0 · anthropic 2.3.0 ·
google-genai 2.30.0 · httpx 0.28.1 · websockets 16.1.1 · psutil 7.2.2 ·
python-socketio 5.17.0 · pydantic 2.14.1 · onnxruntime 1.31.0 · numpy 2.5.4 ·
sounddevice 0.5.6 · truststore 0.10.5. Not installed: pyserial.

**Machine quirks.** pip needs `--use-feature=truststore`; git needs
`-c http.sslBackend=schannel`; system Node is 22.11; no Android SDK; the agent's shell
sees a private AppData, so the owner starts the live app and copies logs.

---

## 0.1 Integration architecture: how all the outside projects stay in harmony

Everything external enters through one of four seams and leaves through one bus.

```
            ┌──────────────── JARVIS core (Python) ────────────────┐
 voice ───► │ ConversationService ─► ToolDispatcher (approvals,    │
 chat  ───► │        ▲                 taint rule)                 │
 channels ► │        │                    │                        │
            │   Proactive engine ◄── Signals bus ◄── producers     │
            └───┬──────────┬──────────────┬──────────────┬─────────┘
   seam 1: MCP sidecars   seam 2: isolated   seam 3: embedded   seam 4: native
   (stdio, per-tool        workers (own      views (iframe +    HTTP adapters
   policy)                 venv / process)   postMessage)       (httpx, read-first)
   GEV, WhatsApp bridge,   build123d CAD,    God's Eye View,    Home Assistant,
   Playwright, Windows     Blender scenes,   cameras, charts    Open-Meteo, Proxmox,
   control, GitHub…        local speech                         Telegram, Gmail…
```

Rules:
- A project is adopted at exactly one seam, pinned to a commit or lockfile, and never
  given secrets it does not need.
- Every source of events publishes a normalised **Signal** (S7). Nothing speaks to the
  owner directly except the proactive engine and the active conversation.
- Every visual result is shown as a **Stage panel** (S13b) through one panel registry, so
  the globe, a CAD model, a camera and a chart all appear the same way.
- Every side effect goes through `ToolDispatcher`, so approvals and the taint rule (S15)
  apply to all of them.

---

## S1. No more stalls: instant answers, time budgets, real progress — tier Careful

**Goal.** A simple question never hangs, whatever the cause. This plan does not depend on
the owner's log.

**Why it stalls today [repo].** Five things line up:
1. There is no weather tool and no web search tool.
2. `backend/services/world_tools.py:109-117` sends weather questions to the God's Eye
   View tools, which only have weather map layers.
3. A brain turn has no overall time limit. `backend/services/conversation.py`: up to
   `TOOL_STEPS = 5` steps (line 64), 45 s of model time per step (line 251), so 225 s of
   model time alone.
4. Tools may wait a long time: each globe data tool up to 135 s
   (`mcp_registry.py:621`, `GEV_TIMEOUT = 60`), the globe start up to 60 s
   (`world_view.py:65`), `world_show` 150 s, `world_tour` 240 s.
5. `backend/services/voice.py:1029` waits for the brain with no deadline, and the voice
   model is told to say "One moment" and then fills the silence with invented status.

Each layer below removes one cause. Layers 4 and 5 are the safety net: they bound the turn
even if a cause nobody has found yet appears.

### Layer 1 — instant tools at the voice layer (no brain hop)

`backend/services/live_config.py`: add function declarations beside `ASK_BRAIN`:
- `quick_weather(place?: STRING, when?: "now"|"today"|"tomorrow"|"week")`
- `quick_agenda()` — today's calendar events and reminders
- `quick_home()` — one-line home summary (only when Home Assistant is connected)

Description for each: "Answer directly in one or two sentences. Do not call ask_brain for
this." Put the current date, time and time zone in the Live system text at session start.

`backend/services/voice.py` `tool_call`: add a branch for these names that calls the same
service functions as the brain tools (weather service, calendar list, reminders, home
summary), each inside `asyncio.timeout(5)`, read-only, never asking; on failure respond
`{"error": "unavailable", "message": "<plain reason>"}`. They do not create a brain turn.

### Layer 2 — a weather tool for the brain (no key)

New `backend/services/weather.py` (`WeatherService(app)`, wired in `application.py`).
- Geocode: `GET https://geocoding-api.open-meteo.com/v1/search?name=<place>&count=1&language=en`
- Forecast: `GET https://api.open-meteo.com/v1/forecast?latitude=..&longitude=..&current=temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,wind_speed_10m&hourly=temperature_2m,precipitation_probability&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=auto&forecast_days=3`
  (URLs are **[recall]**: fetch each once in a test script and adjust field names before coding.)
- `httpx` with `provider_ssl_context()`, 6 s timeout, 10 minute cache per place.
- Tool `weather(place: str | None, when: Literal["now","today","tomorrow","week"] = "today")`,
  never asks. Map WMO `weather_code` to plain words. Return a compact dict.
- Setting `assistant.home_place = {name, lat, lon}` or null. When null and no place is
  given, return `{"need_place": true}`; JARVIS asks once for the home town and saves it
  (a Preferences field "Home town" too).
- Open-Meteo is free for non-commercial use: note it in `docs/` and flag for M5.

### Layer 3 — web search and fetch for Claude

`backend/llm/claude.py` `request()`: when `assistant.web_search` is on (default on),
append `{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}` and
`{"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 3}`.
- Installed SDK: `anthropic 2.3.0` **[repo]**. Before coding, load the `claude-api` skill
  and read `shared/tool-use-concepts.md` and `python/claude-api/tool-use.md` for the
  exact block types and the `pause_turn` rule.
- Do not also declare code execution. On `stop_reason == "pause_turn"`, re-send to
  continue. Server tool errors arrive as result blocks, not exceptions.
- History is already verbatim, so result blocks replay unchanged.
- Add the search price to `backend/llm/pricing.py` and the usage receipt.
- Gemini brain: leave search off unless a test proves grounding works with tools.

### Layer 4 — the globe is opt-in and fails fast

- `SHOW_DESCRIPTION` in `world_tools.py`: remove "weather" from the list of questions to
  answer with the globe; add "For a plain weather question use the weather tool. Use the
  globe only when the owner asks to see something."
- Tool gate in `ConversationService` (new `tool_groups.py`): the world group
  (`world_show`, `world_tour`, every `mcp__gev__*`) is offered only when the request
  mentions the globe (globe, world, map, flights, ships, vessels, satellites, earthquake,
  quake, wildfire, tour, "show me" + place) or the World page is open. With S5 this
  becomes "deferred" instead of dropped.
- `world_view.py` `show_view`: check for an open window (`open_pages()` / `owner_rooms()`)
  **before** `ensure_ready()`, so a voice request with no window fails in under a second
  instead of starting the globe first.

### Layer 5 — a budget for every turn

`backend/services/conversation.py`:
- `TURN_BUDGET_S`: 60 for voice (`usage_feature == "voice_brain"`), 120 for chat.
- New `ToolSpec.long_running: bool = False` (`services/tools.py`). Set True on CAD build,
  image generation, `world_tour`, call placement, web agent runs. While a long-running
  tool executes, the budget clock is paused.
- Every other tool is capped at `min(its own timeout, time left in the budget)`.
- First-token deadline: if a model step yields nothing for 20 s, cancel it and retry once
  on the fast route (Haiku 5.5 when the brain is Claude; otherwise the same model once).
- When the budget runs out: stop the loop and return a truthful answer built from what
  finished ("I couldn't finish that in time, sir. I got as far as …"). Log
  `outcome=budget`. Never return silence.

### Layer 6 — two-phase `ask_brain` (real progress only)

`voice.py` `ask_brain`, `live_config.py`, `conversation.py`:
- `ConversationService.reply(..., on_progress=callback)`: call it when a tool starts with
  a phrase from `PROGRESS_PHRASES`, keyed by tool-name prefix (`weather` → "Checking the
  forecast", `web_search` → "Searching the web", `mcp__gev__` → "Pulling the live map
  data", `calendar_` → "Checking your calendar", default "Working on it").
- Phase 1: no result after 4 s → answer the pending Live tool call with
  `{"status": "working", "say": "<phrase>, sir.", "then": "wait silently"}`.
- Phase 2: when the brain finishes → inject a Live text turn (the
  `send_realtime_input(text=...)` path the morning briefing uses): "Answer for the
  owner's request: <text>. Speak it now, unchanged in meaning."
- Further progress lines, at most one every 12 s, the same way: "Say exactly: …".
- Rewrite the end of the `ASK_BRAIN` description: remove "(for example 'One moment')";
  add "Never describe delays or status yourself. Say only a progress line you are given."
- If the session closes mid-task, the answer still lands in the conversation.

### Layer 7 — see it and prove it

- One content-free log line per turn: `turn_timing request_id=… origin=voice|chat
  provider=… model=… effort=… first_token_ms=… total_ms=… outcome=ok|budget|error
  steps=[tool:ms,…] input_tokens=… output_tokens=…`.
- RPC `brain_check` and a Preferences > AI button "Run a check": a one-line prompt with no
  tools (latency), then `weather` for the home town; shows both timings; logs them.
- `tests/test_no_stall.py` (fake providers, fake clock):
  1. a weather turn is never offered the world tool group;
  2. a model that never answers → fallback at 20 s, and an answer or a truthful failure
     inside the budget;
  3. a tool that hangs is cut at the budget and the turn still returns text;
  4. a long-running tool pauses the budget;
  5. `ask_brain`: interim reply at 4 s, final injection, closed-session path;
  6. `quick_weather` answers without creating a brain turn;
  7. `world_show` with no window fails in under 1 s and does not start the globe.

**Done when.** All seven tests pass; the full suite is green; `docs/AI_PROVIDERS.md` and a
new `docs/WEATHER.md` describe the tools, budgets and the check button.

---

## S2. Brain model and effort picker — tier Medium (design rule: RUNBOOK section 7)

**API facts** (claude-api skill, cached 6 Oct 2026):
- Request field: `output_config: {"effort": "low"|"medium"|"high"|"xhigh"|"max"}`.
- API defaults: Sonnet 5.5 `high`, Haiku 5.5 `medium`. JARVIS always sends effort
  explicitly; `ClaudeProvider` already defaults to `"medium"` **[repo]**.
- Thinking is adaptive on both; `{"type":"disabled"}` is a 400 on Sonnet 5.5; no
  `temperature`; no forced `tool_choice`; Haiku 5.5 has no server-side refusal fallback
  (`supports_fallback()` already handles it).
- Prices per million tokens: Sonnet 5.5 $2 in / $10 out; Haiku 5.5 $0.10 in / $0.50 out.
- Switching model mid-conversation: thinking blocks are model-bound. The provider already
  sends `block_binding.prefix_mismatch_behavior: "drop_block"`, so a switch drops old
  reasoning instead of failing. Prompt caches are per model, so the first turn after a
  switch is uncached.

**Settings** (`ASSISTANT_DEFAULTS` in `services/settings.py`):
- `assistant.brain`: `"auto" | "claude" | "gemini"` (exists).
- `assistant.claude_model`: `"claude-sonnet-5-5"` (default) | `"claude-haiku-5-5"`.
- `assistant.effort`: `"low" | "medium" | "high"`, default `"medium"`. (xhigh/max are left
  out on purpose: slow and costly for an assistant.)
- `assistant.gemini_model`: string, default = today's `model_id("text")`; must be in the
  fetched list.

**Backend** (`backend/llm/router.py`):
- `brain_model(settings)`: env `BRAIN_MODEL` wins, else `assistant.claude_model`.
- `TaskRouter.provider("chat")` → `ClaudeProvider(api_key, model, effort=assistant.effort)`;
  the `fast` task stays Haiku at `low`. Telephony keeps `effort="low"`
  (`telephony/agent.py:1093`).
- Gemini: `GeminiProvider(model=assistant.gemini_model)`. Effort does not apply: on
  7 Nov every thinking config on gemini-3.8-flash hung past 60 s (`llm/gemini.py:36-45`).
- New RPC `brain_models` → `{claude: [{id, label, note}], gemini: [{id, label}], efforts}`.
  Gemini list from `models.list`, filtered to `gemini-*` text models that support
  generateContent, cached 1 hour, with the current default always included.
- `status()` gains `effort` and `claude_model`.

**UI** (`src/features/settings/AiSettings.jsx`, `aiSettingsModel.js`): replace the
three-way `BrainControl` with:
- "Brain" select: Auto · Claude Sonnet 5.5 (smartest) · Claude Haiku 5.5 (fastest,
  cheapest) · Gemini. Picking Gemini reveals a model select.
- "Effort" segmented control Low / Medium / High with a one-line helper: "Higher effort
  thinks longer and costs more. Medium suits most requests." Disabled with the note
  "Gemini manages its own thinking" when the brain is Gemini.
- The existing active-model line stays ("Using Claude Sonnet 5.5 · Medium effort").

**Tests.** Router matrix (setting × keys present), settings validation, provider request
carries the chosen effort, UI model mapping.

---

## S3. M7 K1 — real CAD engine on build123d — tier Careful

**State.** `.venv-cad/` at the repo root, Python 3.13, `build123d==0.13.0` installed and
checked. The core's own lock is untouched.

**Design.** The brain never writes Python. It emits a validated **feature tree**; an
isolated worker turns it into geometry.

```json
{"units": "mm",
 "features": [
  {"id": "body", "op": "box", "size": [60, 40, 20], "at": [0, 0, 10], "material": "titanium"},
  {"id": "h1", "op": "hole", "target": "body", "face": "top", "at": [10, 5], "diameter": 5, "depth": "through"},
  {"op": "pattern", "of": "h1", "kind": "linear", "count": [2, 2], "spacing": [40, 30]},
  {"op": "fillet", "target": "body", "edges": "vertical", "radius": 3},
  {"op": "chamfer", "target": "body", "edges": "top", "distance": 1},
  {"op": "cut", "target": "body", "tool": {"op": "box", "size": [20, 10, 30], "at": [0, 0, 10]}},
  {"op": "shell", "target": "body", "thickness": 2, "open": "top"},
  {"op": "text", "target": "body", "face": "top", "text": "JARVIS", "size": 8, "depth": 0.6, "mode": "engrave"}],
 "export": ["glb", "stl", "step"]}
```

Ops for v1: `box`, `cylinder`, `sphere`, `l_bracket`, `enclosure`, `hole` (through, blind,
counterbore), `slot`, `cut`, `union`, `fillet`, `chamfer`, `shell`, `text`, `pattern`
(linear, polar), `mirror`. Edge selectors: `all`, `vertical`, `top`, `bottom`.

**Files.**
- `backend/services/cad_features.py`: pydantic models for the tree; limits (≤ 40
  features, sizes 0.1–2000 mm, text ≤ 40 characters); stable hash of the tree.
- `backend/workers/cad_kernel_worker.py`: runs under `.venv-cad\Scripts\python.exe -I`,
  JSON lines in/out, no network, working directory = a temp job folder. Commands:
  `build {tree, export, quality}` → `{ok, facts: {volume, bbox, faces, edges, valid},
  files: {...}, warnings}`; `ping`.
- `backend/services/cad_kernel.py`: finds the venv, starts and reuses the worker,
  timeouts, kill tree, maps kernel errors to plain messages ("A 3 mm fillet does not fit
  a 4 mm edge"), exposes `available()`. Falls back to today's box engine when the venv is
  missing or an op is unsupported.
- `backend/services/cad_design.py` (`LiveDesigns`): new step kinds for the feature ops;
  draft preview is a low-quality GLB from the worker, cached by tree hash (target under
  1.5 s per step).
- `src/features/liveDesign/LiveDesignCanvas`: load the GLB when the kernel is active and
  apply the blueprint material; keep the primitive path for the fallback.
- `scripts/setup-cad-engine.ps1` + `requirements-cad-kernel.lock` (from `pip freeze` in
  `.venv-cad`, with hashes) for fresh installs; owner-run, never in-app.
- Update the live-design tool descriptions: remove "no holes, fillets or booleans".

**build123d 0.13.0 calls [repo — run in `.venv-cad` on 14 Nov 2026].** Algebra mode;
all of these exist and were executed:
- Shapes and placement: `Box(l, w, h)`, `Cylinder(radius, height)`, `Sphere`,
  `Pos(x, y, z) * shape`, `Rot`, `Plane`, `Axis`, `Locations`, `GridLocations`,
  `PolarLocations`, `Hole`, `CounterBoreHole`, `mirror`.
- Booleans: `a - b`, `a + b`.
- `fillet(objects, radius)` and `chamfer(objects, length, length2=None, angle=None)`
  take edges, for example `fillet(edges, 3)`.
- Shell: `offset(part, amount=-2, openings=top_face)` where
  `top_face = part.faces().sort_by(Axis.Z)[-1]`.
- Text: `extrude(Text("JARVIS", font_size=8), amount=0.6)`.
- Export: `export_gltf(shape, path, unit=Unit.MM, binary=False, linear_deflection=0.001,
  angular_deflection=0.1)` (pass `binary=True` for GLB; raise the deflections for fast
  drafts), `export_step(shape, path)`, `export_stl(shape, path, tolerance=0.001,
  angular_tolerance=0.1)`, `import_step`.
- Facts: `part.volume` (float), `part.bounding_box().size`, `part.is_valid` is a **bool
  property**, not a method.
- Gotcha: `part.edges().filter_by(Axis.Z)` on a box with a through-hole returns 5 edges
  (the four corners plus the hole's seam). For "vertical corner" fillets, keep only edges
  whose midpoint lies on the bounding-box corners.

**Tests.** Tree validation; worker protocol with a fake kernel; opt-in real-kernel tests
(skipped without the venv): through-hole volume, fillet validity, STEP export re-import
volume match, timeout and kill.

**Done when.** "Make a 60 by 40 bracket with four 5 mm holes and rounded corners" builds,
previews step by step, exports STEP.

---

## S4. Diagnostics export and flight recorder — tier Medium

**Why.** The builder cannot read the owner's real AppData. Every live bug costs a round trip.

- Tray menu and Preferences: "Export diagnostics". Writes
  `<repo>\.runtime\live-logs\diagnostics-<timestamp>.zip` (the folder is a setting,
  default `%USERPROFILE%\Documents\JARVIS diagnostics` outside a dev checkout): last 2,000
  log lines, `turn_timing` lines, settings with secrets removed, key status (configured or
  not, never values), versions, sidecar states, audio device names, the last 20 turn traces.
- Flight recorder: `backend/services/trace.py`, a ring buffer of the last 200 turns:
  spans (wake, speech in, first token, each tool with name and duration, speech out),
  token counts, cost, approvals asked and answered. No message text unless
  `diagnostics.include_text` is on.
- UI: "Activity → What JARVIS did": one row per turn, expandable to spans. This is also
  the audit log S11 and S15 need.

---

## S5. Tool search and skills — tier Careful

**Tool search (Claude).** In `ClaudeProvider.request()` when more than 25 tools are present:
- Keep a core set loaded (about 12: weather, web search, reminders, calendar list, home
  devices, home control, live design start, world show, look through camera, memory
  search, load skill, routine run).
- Mark the rest `"defer_loading": true` and add
  `{"type": "tool_search_tool_bm25_20251119", "name": "tool_search_tool_bm25"}`.
- Never defer everything; the search tool itself is never deferred (the API returns 400).
- Keep the list sorted by name so prompt caching holds.

**Gemini brain.** No equivalent: send the core set plus the tools whose description
matches the request (a small local BM25 in `backend/services/tool_index.py`).

**Skills.** `backend/services/skills.py`.
- Folder format (the open Agent Skills layout): `skills/<slug>/SKILL.md` with YAML front
  matter (`name`, `description`) and instructions; optional `scripts/`.
- Locations: `<user data>\skills\` (owner's) and `<repo>\skills\` (shipped).
- The system prompt lists one line per skill; the tool `load_skill(name)` returns the body.
- "Teach JARVIS": the owner says "remember how to do this"; JARVIS drafts a `SKILL.md`;
  an approval card shows the file; saved on approve.
- Scripts run only through existing approved local-action paths. No registry, no
  auto-install (341 of 2,857 audited public skills were malicious **[web]**).

---

## S6. Long-term memory ("What JARVIS knows") — tier Careful

**Decision.** Native SQLite, no outside service. v1 has no downloads.

**Data** (in the core's encrypted database):
`memory_facts(id, kind, subject, text, confidence, pinned, sensitivity, source_conversation_id,
source_turn, created_at, valid_from, valid_to, superseded_by)` with `kind` in
`profile | preference | person | place | routine | episode`; an FTS5 table over `subject`
and `text`. Old facts are superseded, never silently overwritten.

**Write path.** `backend/services/memory_owner.py`. Two minutes after a conversation goes
idle, one Haiku 5.5 call (effort low, structured output via `output_config.format`) gets
the new turns plus related existing facts and returns `add | update | supersede | none`
operations. Rules in the prompt: no secrets, card numbers or passwords; health and
finances only if the owner said "remember"; minimal detail about other people. A pause
switch stops all writes.

**Read path.** Before each brain turn: pinned profile block (≤ 600 tokens) plus the top 8
facts by BM25 on the owner's text, weighted by recency. Put this block **after** the last
cache breakpoint (in the user turn or a late system block) so the cached prefix stays stable.

**Tools.** `memory_search(query)` never asks; `memory_remember(text)` never asks and shows
a "Remembered" toast; `memory_forget(query | id)` asks.

**UI.** `src/features/memory/`: facts grouped by kind; edit, delete, pin; "from the
conversation on 8 Nov" source link; pause; export. A read-only Markdown mirror at
`<user data>\memory\MEMORY.md`, regenerated on change.

**v2 (needs a download OK).** `sqlite-vec` extension plus a local multilingual embedding
model through `fastembed` (ONNX; English and Malay), then hybrid BM25 + vector ranking.
This build can load it: Python 3.13.0, SQLite 3.45.3, FTS5 present and
`enable_load_extension` available **[repo]**.

**Not chosen.** mem0 (its open-source path needs its own LLM pipeline and adds a vector
store), Letta (a whole agent runtime), Graphiti (needs a graph database) **[web]**.

---

## S7. Signals bus, proactive engine, heartbeat, routines — tier Careful

**Signal** (`backend/services/signals.py`):
`Signal(kind, source, at, title, body, data, urgency: 0-3, dedupe_key, expires_at, person_id=None)`.
Publish on `app.bus`. Kinds: `calendar.soon`, `weather.rain_soon`, `call.missed`,
`call.vip`, `message.received`, `job.finished`, `home.state`, `home.alert`,
`homelab.alert`, `system.battery`, `routine.due`.

**Producers** (each a small class with `start()`/`stop()`): calendar (T-30 and T-10
minutes, plus travel time when the event has a place), weather (rain within 2 hours at
`home_place`), calls and jobs (existing events), home (S12 WebSocket), homelab (S12),
channels (S8).

**Engine** (`backend/services/proactive.py`):
- Score = urgency × person weight (VIP) × time relevance; thresholds per
  `assistant.chattiness` (`quiet | balanced | chatty`); quiet hours; gaming mode.
- Delivery by presence: workspace focused → speak in the voice stage; PC in use → overlay
  card with a sound; away → Telegram push (S8) or the "while you were away" digest;
  urgency 3 → the existing phone-call path.
- At most one spoken interruption per 10 minutes on Balanced.
- Every delivery is listed under Activity with "Don't tell me about this again", which
  writes a mute rule (kind + source + person).

**Heartbeat.** Every 30 minutes while resident, and only if signals need judgment, one
Haiku call with the pending signals and the owner's `HEARTBEAT.md` (standing
instructions, editable in Preferences). Output: `notify | speak | run_routine | none`.
No pending signals means no model call.

**Routines.** Table `routines(id, name, trigger, steps, enabled)`; trigger is a phrase, a
schedule, or a signal filter; steps are `{tool, args}` run through `ToolDispatcher`, so
approvals still apply. Tools: `routine_run(name)`, `routine_save(...)` (asks). UI page
under Tasks (a `routines` feature flag already exists in `workspaceNavigation.js`).
Use the existing `SchedulerAgent`; no new scheduler library.

---

## S8. Channels: Telegram remote, then WhatsApp without WhatsApp Business — tier Careful

**Package** `backend/services/channels/`: `base.py` (`Channel` protocol: `start`, `stop`,
`send_text`, `send_approval`; `InboundMessage(channel, chat_id, sender, text, media, at,
is_owner)`), `gateway.py` (owner messages → `ConversationService.reply`; other people's
messages → Signals and the Inbox), `telegram.py`, `whatsapp.py`.

### 8a. Telegram (official Bot API, no ban risk)

- Plain `httpx`, no library: long-poll `getUpdates` (timeout 50), `sendMessage`,
  `sendChatAction`, `sendPhoto`, `getFile` (voice notes are OGG/Opus → the existing Gemini
  transcription route), `answerCallbackQuery`. Inline keyboard buttons for approvals;
  `callback_data` is a signed approval id.
- Setup: the owner creates a bot with BotFather and saves the token as the secret
  `telegram_bot_token`. Preferences shows a pairing code; the owner sends `/start <code>`;
  the core stores `owner_chat_id`. Every other chat is ignored.
- Remote approvals are allowed for ordinary tools. Off by default for the "physical
  security" class (unlock, open gate, disarm) and for computer use; the owner can change it.
- Bot chats are not end-to-end encrypted: say so in Preferences.

### 8b. WhatsApp messages (linked device)

- **Library:** `@whiskeysockets/baileys` (MIT) in a Node 24 sidecar,
  `sidecars/whatsapp/bridge.mjs`, pinned by lockfile. Chosen over whatsmeow because Node
  24 is already installed for World view and the code is plain JavaScript that can be
  audited; whatsmeow (Go) is the fallback if Baileys breaks. Both are unofficial and
  carry the same terms-of-service and ban risk **[web]**.
- **Calls used [recall — confirm against the pinned version]:** `makeWASocket({auth})`,
  events `connection.update` (QR and state), `messages.upsert`, `call`;
  `sock.sendMessage(jid, {text})`, `sock.sendPresenceUpdate('composing', jid)`,
  `sock.readMessages(keys)`, `sock.rejectCall(callId, from)`.
- **Shape:** the bridge is an MCP stdio server registered as built-in server `wa` in
  `mcp_registry.py`. Tools: `wa_status`, `wa_list_chats`, `wa_read_chat`, `wa_search`
  (all `never_ask`); `wa_send_text(chat, text)` (`ask`, the card shows the recipient and
  the exact text); `wa_mark_read`; `wa_reject_call`. It also sends JSON-RPC notifications
  `wa/qr`, `wa/state`, `wa/message`, `wa/call`, which `whatsapp.py` turns into Signals.
- **Secrets:** the bridge keeps nothing on disk. Auth state is read and written through
  RPCs `auth_get` / `auth_set`; the core stores it encrypted (internal `SecretSpec`).
  This avoids Baileys' default plaintext JSON session files. Messages are cached in the
  core's encrypted database, not in the sidecar.
- **Rules (ban risk and manners):** one-to-one chats only; never groups, broadcasts or
  status; never message a stranger first; every send needs the owner's approval, except
  a per-contact "busy auto-reply" the owner switched on (one message per contact per
  12 hours, starting "This is JARVIS, <owner>'s AI assistant."); 2–6 s typing delay;
  hard caps of 20 sends per hour and 100 per day; a tray kill switch; if WhatsApp logs
  the device out, stop and tell the owner — never re-pair automatically.
- **Consent screen** in Preferences before pairing: unofficial, may break, the number
  could be restricted. Read-only mode is offered as a choice. The owner agreed to the
  linked device on 14 Nov 2026; the screen still appears, because pairing is their step.
- **No-risk alternative** if the owner declines: the Android companion's notification
  listener with direct-reply actions (the Inbox pipeline). Needs the Android SDK.

### 8c. WhatsApp calls

No library can carry WhatsApp call audio; they see the call offer and can reject it
**[web]**. So:
- Call arrives → Signal `call.whatsapp` → overlay card "WhatsApp call from <name>".
- If busy mode is on: reject, then send the disclosed auto-text and run a bounded
  message-taking chat (who, what, how urgent; at most four exchanges; no commitments, no
  personal details) → the normal VIP and briefing paths.
- Voice answering is only possible through a Bluetooth hands-free node (S9c).

---

## S9. Phone calls: pluggable transport, GSM modem for Malaysia — tier Heavy (hardware spike first)

**Decision (owner, 14 Nov 2026: "whichever you suggest").** Build the seam and the modem
transport now, tested against a fake serial port. `calls.transport` stays `twilio` by
default and switches to `modem` only when the owner picks it after a modem is found.
Recommended hardware: a SIM7600G-H class USB LTE dongle whose listing says voice calls
are supported, plus a prepaid SIM. The first real call test is the owner's step.

**Seam.** `backend/telephony/transport_base.py`:

```python
class CallLeg(Protocol):
    caller_id: str | None
    async def answer(self) -> None: ...
    async def hangup(self) -> None: ...
    def audio_in(self) -> AsyncIterator[bytes]: ...   # PCM16 mono 8 kHz, 20 ms frames
    async def send_audio(self, pcm: bytes) -> None: ...

class CallTransport(Protocol):
    async def start(self, on_incoming: Callable[[CallLeg], Awaitable[None]]) -> None: ...
    async def place(self, number: str) -> CallLeg: ...
    async def stop(self) -> None: ...
```

Wrap today's Twilio path (`telephony/gateway.py`, `media.py`) as `TwilioTransport`; the
agent (`telephony/agent.py`) talks only to `CallLeg`. Setting `calls.transport`:
`twilio | modem`.

### 9a. Modem transport (recommended)

- **Hardware:** a USB LTE modem with voice (SIMCom SIM7600G-H dongle, or Quectel EC25-E
  on a USB adapter) and a second prepaid SIM. The main number forwards unanswered, busy
  and unreachable calls to it (codes in `docs/CALL_ROUTING.md`).
- **Spike before any code (30 minutes with a serial terminal):** place and receive a
  voice call on the chosen carrier; confirm audio both ways; note LTE (VoLTE) or 2G during
  the call (`AT+CPSI?` on SIMCom). Malaysia switched 3G off in 2021; whether a data modem
  gets VoLTE, and whether 2G is still up, depends on the carrier and is **unverified**.
- **SIM7600 commands [recall]:** `AT+CLIP=1` (caller ID), `RING`, `ATA`, `ATD<number>;`,
  `AT+CHUP`, `AT+CPCMREG=1` after connect to start PCM on the audio serial port (8 kHz,
  16-bit mono), `AT+CPCMREG=0` before hanging up.
- **EC25 commands [web, Quectel forum]:** `AT+QPCMV=1,0` (PCM on the NMEA serial port,
  8 kHz 16-bit mono; the host must write 1600 bytes every 100 ms), `AT+QAUDMOD=3`. The
  setting resets on reboot. The USB audio class mode (`=1,2`) is reported broken on
  several firmwares, so use serial PCM. Some firmware has a VoLTE uplink bug.
- **Code:** `backend/telephony/modem.py` — `pyserial` in two threads (AT port with a
  line parser for unsolicited results; audio port reader and a clock-paced writer with a
  60–120 ms jitter buffer and silence fill), bridged to asyncio queues. Echo: gate the
  uplink to the model while JARVIS speaks (as today) and enable the modem's own echo
  canceller. Port discovery by USB vendor/product id, overridable in Preferences.
  `requirements-call-modem.txt` with `pyserial`.
- **Tests:** a fake serial pair that plays a scripted call.
- The USB driver is a system change: the owner installs it.

### 9b. Twilio

Already built; stays for anyone without the hardware.

### 9c. Bluetooth hands-free node (stretch, only if WhatsApp voice matters)

- Windows `PhoneLineTransportDevice` is **rejected**: it only works from an MSIX-packaged
  app and is reported broken since Windows 11 22H2 **[web]**.
- Workable shape **[recall]**: a small Linux box (Raspberry Pi) paired to the owner's
  phone as a hands-free unit (BlueZ with oFono, or Asterisk `chan_mobile`), audio through
  PipeWire, bridged to the core over the LAN as another `CallTransport`. It can answer
  the owner's real number and place calls showing the owner's caller ID. On Android,
  WhatsApp calls usually surface to Bluetooth headsets and car kits — check on the
  owner's phone before building. Works only while the phone is near the node.

Approval and AI-disclosure rules for calls do not change.

---

## S10. Voice quality — tier Heavy

- **10a. Direct speech pipeline** (setting `voice.pipeline: live | direct`, default
  `live` until measured). `direct` = voice activity detection → speech-to-text → Claude
  streaming → text-to-speech sentence by sentence, so the answer is spoken as it is
  written, once. VAD: Silero ONNX (onnxruntime is installed). Turn end: 700 ms silence;
  optionally the `pipecat-ai/smart-turn` ONNX model **[recall]**. Speech in and out can
  stay on Gemini (same Kore voice) or go local (10d). Measure time-to-first-audio for both
  with S16 before changing the default.
- **10b. Echo cancellation, natural barge-in.** Feed the playback signal as the reference
  to a WebRTC audio processing module in `backend/services/audio_devices.py`. Candidate:
  the `livekit` Python package's `rtc.AudioProcessingModule` (echo cancellation, noise
  suppression, gain; 10 ms frames; `process_stream` / `process_reverse_stream`)
  **[recall — check the wheel and API]**. Then barge-in = speech detected on the cleaned
  microphone while JARVIS talks, no wake word needed.
- **10c. Only my voice.** First M10 V1 (a custom verifier on the existing wake-word
  embeddings, numpy only). Upgrade path: a speaker-embedding model through sherpa-onnx.
- **10d. Local fallback.** `sherpa-onnx` (Apache-2.0) as the one local speech runtime:
  streaming recognition, VAD, keyword spotting, speaker ID and text-to-speech on Windows
  x64 **[web]**; PyPI listings showed wheels for CPython 3.8–3.12, so check for 3.13
  first. A small local model (through a llama.cpp server the owner installs) for lights,
  timers and routines when offline. Owner-deferred until the RAM/VRAM decision.
- **10e. Voice.** The owner keeps a woman's voice (decided 14 Nov 2026). Kore stays the
  default. Preferences may list other female Gemini voices with a preview. No male
  preset. Never imitate a real person's voice.
- **10f. JARVIS in every room.** An OpenAI-compatible `/v1/chat/completions` endpoint on
  the core (off by default, LAN only, bearer token) so Home Assistant's voice pipeline and
  its room satellites can use JARVIS as the conversation agent. Opening the firewall is
  the owner's step.

---

## S11. Computer use beyond the browser — tier Heavy

- **v1 (quick):** a Windows control MCP server (for example `CursorTouch/Windows-MCP`,
  MIT **[recall — verify repo and licence]**) through the MCP connector, every action tool
  on `ask`.
- **v2 (native):** `backend/services/computer_use.py` with Claude's computer-use tool.
  On Sonnet 5.5 the Claude API accepts only `computer_toolset_20260801`
  (`computer_20251124` returns 400). Read the claude-api skill's
  `shared/model-migration.md` for the toolset's exact shape before coding.
  - `backend/services/desktop_input.py`: screenshots with `mss`, mouse and keyboard
    through `SendInput` (ctypes), element names through Windows UI Automation
    (`pywinauto` or `uiautomation`) to label targets and to detect forbidden windows.
  - One approval per task (goal and the apps it may touch). A banner "JARVIS is using
    your computer" (reuse the overlay process with a new role). Global Esc stops at once.
  - Deny-list by process (banking, password managers, Windows Security). Never types
    passwords, card or ID numbers. Sends, purchases, deletes and settings changes pause
    for an on-screen approval.
  - Every action lands in the flight recorder (S4) with a thumbnail kept 7 days.
- Idea from UFO² **[web]**: run the task on a separate virtual desktop so the owner's
  mouse is not taken over. Consider after v2.

---

## S12. Home in realtime, homelab pack, cameras — tier Careful

- **Home Assistant events.** In `backend/services/home_assistant.py` add a WebSocket
  client (`/api/websocket`, auth with the stored token, `subscribe_events` for
  `state_changed`). Tiles update instantly; owner-selected entities publish Signals
  (door open over 5 minutes, leak, alarm). Use `websockets` (16.1.1 is
  already installed **[repo]**).
- **Home page.** Its own navigation entry (not under Connections); a summary line per
  room; sensors (temperature, humidity, energy); a scenes row; camera tiles from
  `/api/camera_proxy/<entity>`.
- **Homelab that can run anything** `backend/services/homelab/` (owner: "make it so it
  can run anything"). No new dependencies.
  - `base.py`: `Entity(id, host, kind, name, state: ok|warn|down|unknown, metrics, detail)`;
    `Adapter` protocol: `async probe() -> list[Entity]`, `actions: list[str]`,
    `async act(action, args)`.
  - `registry.py`: reads the setting `homelab.hosts`, a list of
    `{id, name, adapter, address, options, secret, named_actions}`; polls each adapter
    on its own interval; publishes Signals on threshold changes.
  - **Generic adapters (these cover any system):**
    - `ping` and `tcp`: reachability and open ports (stdlib sockets; `ping.exe` as a subprocess).
    - `http_json`: GET a URL with an auth header from the secret store; map fields with
      dotted paths to metrics; `ok_when` is a small comparison list, never code.
    - `prometheus`: read any exporter's `/metrics` text, or query a Prometheus server
      (`/api/v1/query`); pick series by name and labels.
    - `ssh`: Windows' OpenSSH client (`%SystemRoot%\System32\OpenSSH\ssh.exe`, else
      `ssh` on PATH) with key auth and `BatchMode=yes`. Read-only command presets per OS
      (`uptime`, `df -P`, `free -m`, `systemctl is-active <unit>`,
      `docker ps --format json`, `sensors -j`). The first connection shows the host key
      fingerprint on an approval card. The model can never send free-form shell text.
    - `wol`: Wake-on-LAN magic packet (stdlib socket).
  - **Presets built on the generics:** Proxmox VE (`/api2/json/cluster/resources`, token
    header `PVEAPIToken=…`), Docker through Portainer
    (`/api/endpoints/{id}/docker/containers/json`, `X-API-Key`), Uptime Kuma (its
    Prometheus `/metrics`), Glances (`/api/4/all`) or Netdata, TrueNAS, Pi-hole or
    AdGuard, NUT for the UPS, Tailscale status. (Endpoints are **[recall]**: confirm each
    against the product's docs when its preset is built; a preset is only a saved config
    for a generic adapter plus a field map.)
  - **Two more routes to "anything":** whatever Home Assistant already integrates shows
    up through the Home page; any homelab MCP server added under Connections → Tools
    works through the connector.
  - **Add a system** (Preferences → Systems → Add): pick a preset or "Something else";
    give the address; JARVIS probes ping and common ports (22, 80, 443, 8006, 9090,
    9100, 3001, 8123, 9000) and proposes a config; the owner approves it. Brain tool
    `homelab_propose(address, hint)` returns a config for approval.
  - **Actions:** only owner-defined named actions per host (for example "restart plex" =
    one fixed command). `homelab_action(host, action)` and `homelab_wake(host)` always
    ask, and the card shows the exact command. `homelab_status(scope)` never asks.
  - Signals: host down, service down, disk over 90 %, high temperature, backup failed,
    UPS on battery.
  - Tests: fake subprocess for `ssh` and `ping`, fake httpx, a sample `/metrics` text.
- **Cameras.** Frigate (MIT) events → "Someone is at the front door" with a snapshot on
  the overlay. Object labels only (person, car, package). No face recognition.
- **PC vitals** for the Systems rail: `backend/services/vitals.py` with `psutil` and
  NVIDIA's `nvidia-ml-py`; emitted at 1 Hz only while a renderer shows the rail.
- **Remote access.** Tailscale (owner installs). Never expose port 8000 to the internet.

---

## S13. The JARVIS design language — tier Careful (design rule: RUNBOOK section 7)

### S13a. Language, life and sound (no layout change)

**Tokens** to add in `src/app/tokens.css`:
```css
--bg-void: radial-gradient(120% 90% at 50% 35%, #0a141d 0%, #05080c 60%);
--bg-glass: rgba(10,16,23,.72);      /* with backdrop-filter: blur(14px) */
--grid-dot: rgba(112,224,237,.06);
--glow-accent: 0 0 14px rgba(112,224,237,.35);
--glow-strong: 0 0 28px rgba(112,224,237,.45);
--accent-warm: #ffb454;              /* JARVIS acting / needs you */
--accent-hot: #dff9ff;               /* brightest highlights */
--dur-draw: 160ms; --dur-fill: 200ms; --dur-exit: 120ms; --stagger: 40ms;
--font-display: "Saira Variable", var(--font-sans);
--text-xs: .75rem;                   /* was .6875rem */
```

**Components.**
- `src/shared/ui/HudFrame.jsx` + `hud.css`: chamfered corners with `clip-path`, corner
  brackets, optional tick ruler and index ("01 · WORLD"). For Stage panels and overlays only.
- `src/shared/motion/materialise.js`: the enter sequence (border draws 160 ms → content
  fades and rises 8 px in 200 ms → children stagger 40 ms) and the reverse exit in 120 ms.
  Use the `motion` package (MIT, successor to Framer Motion; import from `motion/react`)
  for presence and exit animation **[recall — confirm React 18 support]**.
- Core glow: an additive sprite behind the core first (no dependency). Bloom through
  `@react-three/postprocessing` only if the sprite is not enough; pin a release that
  matches three 0.160; on mains power and outside gaming mode only.
- `src/app/SystemsRail.jsx` replaces the inspector's content: clock and date, weather
  now, next event countdown, home summary, PC vitals with sparklines (`uplot`, MIT, or
  hand-drawn SVG), homelab dots, running jobs. Each block hides when it has no source.
- Idle life: the core's slow drift (exists), a 4 s breathing glow, a faint dot grid with
  2–4 px pointer parallax.

**Sound** (`src/services/sound/uiSounds.js`, WebAudio synthesis, no files): one timbre
family (sine plus a soft triangle, short envelopes, a little reverb send). Eight cues:
wake, listening start, thinking (very quiet, optional), confirm, deny or alert, panel
open, panel close, notification. A master "Interface sounds" switch and volume; silent in
gaming mode, during calls, and when Windows is muted.

**All of it** sits behind the existing reduced-motion, gaming and low-battery switches.

### S13b. Stage, navigation and Ambient mode (layout)

- **Stage-first Assistant** (`src/features/stage/`): at rest the core is the hero
  (160–220 px, centred), with "Say 'Hey Jarvis', hold the mic, or type." In voice, large
  captions sit under the core, revealed word by word; the owner's speech shows as a
  waveform. The transcript becomes a collapsible right rail. The composer stays at the bottom.
- **Panel registry** (`src/features/stage/panels.js`): `world`, `model`, `camera`,
  `chart`, `table`, `devices`, `document`, `media`, `approval`. A tool result with a
  `panel` field materialises a panel beside the core (the Live design split and the World
  tour become two cases of this). New brain tool `stage_show(panel, data)`.
- **Navigation:** a 56 px icon rail with labels on hover: Assistant, Home, World, Make,
  People, Work, Systems, then Preferences. The project chip moves into the title bar.
- **One page header** component; remove the "feature workspace inside a page" header and
  its close button; World and Home become full-bleed pages.
- **Ambient mode, an option that is off by default** (owner, 14 Nov 2026). Settings
  `ambient.enabled`, `ambient.display`, `ambient.idle_minutes`; a tray item "Ambient
  mode" when enabled. (`src/features/ambient/`, route `?ambient=1`, an Electron
  full-screen window on the chosen display): large core, clock, weather, next event, home summary, a
  slowly turning globe, the latest proactive item. Starts after a set idle time or from
  the tray. Serve the same view to a LAN tablet later.
- **Overlay cards:** extend the talking overlay to show proactive cards (incoming call
  with the caller, timers, door events).

**Acceptance.** Captures in `.runtime/ui-qa/jarvis-language/` for rest, voice, a
materialising panel, the Systems rail and Ambient mode, in normal and reduced-motion;
frame rate at rest above 50 fps on the owner's laptop on mains; nothing animates in
gaming mode.

---

## S14. Work and design pack — tier Medium each

- **Email triage (M9 A7).** Add the `gmail.readonly` scope to the Google OAuth client
  (re-consent). `backend/services/gmail.py`: unread and important → Haiku triage → the
  briefing and "summarise my inbox". Never sends.
- **Files knowledge.** Owner-chosen folders (an Obsidian vault is just a folder).
  `markitdown` (MIT) turns PDF and Office files into Markdown; index with FTS5 (vectors
  with S6 v2). Tool `files_search(query)` returns passages with file links.
- **Meeting notes.** "JARVIS, take notes": record the microphone (optionally system audio
  through WASAPI loopback) with a visible indicator → transcription → summary and action
  items → reminders. Remind the owner to tell the other participants.
- **Remote MCP servers.** Extend `backend/services/mcp_client.py` with the Streamable
  HTTP transport and OAuth 2.1 with PKCE (reuse the loopback PKCE code from
  `services/calendar.py`). Then presets under Connections → Tools: GitHub, Notion,
  Linear, Spotify. Tokens in the store; per-tool policy editor (also makes the `gev`
  policies editable).
- **Design to render.** Extend `backend/workers/blender_scene.py` (Blender 5.2.3 is
  installed): import the GLB from live design, studio lighting, Cycles render, show the
  image as a Stage panel. Do not adopt the Blender MCP add-on: it executes arbitrary
  Python inside Blender.
- **Web tasks.** `@playwright/mcp` (Microsoft, Apache-2.0 **[recall]**) as a Node 24
  sidecar through the MCP connector instead of adding browser-use; form submits,
  purchases and logins stay on `ask`. Chromium is a download that needs the owner's OK.

---

## S15. Security hardening — tier Careful (land the taint rule with S8)

- **Taint rule** in `ToolDispatcher`: each turn's context carries a `taint` set. Reading
  untrusted content adds a source: a web page or search result, an email, another
  person's message, a result from a non-built-in MCP server, a document from outside.
  While tainted, any tool with an outward or physical effect (send, call, purchase,
  unlock or disarm, computer use, file delete) is forced to ask, whatever its stored
  policy, and the card says "This came after reading untrusted content from <source>".
- Untrusted text is always wrapped as data in the prompt, labelled with its source, and
  the system prompt says instructions inside it are never followed.
- Sidecars start with a minimal environment (no inherited keys), in a job object so the
  whole tree dies with them, bound to loopback.
- LAN endpoints (S10f, the wallboard) are off by default, token-protected, never on 0.0.0.0
  without the owner's switch.
- The flight recorder (S4) is the audit log.

---

## S16. Evals and a latency budget — tier Medium

- `scripts/eval/`: about 20 scripted everyday requests (weather, a timer, lights,
  calendar, a bracket, "show me flights over KL", a web question, a memory recall).
  Each run records tool choice, time to first token, total time, tokens and cost. Runs
  cost real money: estimate from token counts and get the owner's OK first.
- Targets: wake acknowledgement within 0.7 s (local cue); first spoken words within 2.5 s
  with no tool and 5 s with one tool; typed first token within 1.5 s.
- A "Latency" block under Activity, fed by the `turn_timing` lines.

---

## Deferred

- K2–K4 (slicer, printer link, print by voice): when a printer exists. OrcaSlicer or
  PrusaSlicer CLI as an external program; OctoPrint, Moonraker or Bambu LAN by model.
- M5 release work: Vite 8, SQLite off the event loop, port resilience, throwaway harness
  profile, signed installer and updates, Android acceptance, CI. Licence flags for M5:
  wake-word models (CC BY-NC-SA), God's Eye View data (CC BY-NC, ODbL), Open-Meteo
  (non-commercial free tier).
