# AI providers

JARVIS uses two providers. Claude is the assistant's brain; Gemini handles audio.

| Work | Model | Provider | Notes |
| --- | --- | --- | --- |
| Chat, planning and tool use (desktop chat, quick assistant, reviewed voice input, phone chat) | Claude Sonnet 5.5 (`claude-sonnet-5-5`) | Anthropic | Gemini text model when no Anthropic key is configured |
| Fast summaries and classification (`fast` / `summary` routes; call summaries later) | Claude Haiku 5.5 (`claude-haiku-5-5`) | Anthropic | Gemini text model when no Anthropic key is configured |
| Transcription of reviewed push-to-talk | Gemini (`JARVIS_TRANSCRIPTION_MODEL`, else the text model) | Google | Always Gemini |
| Live voice (later), vision and legacy CAD | Gemini | Google | Vision and legacy CAD follow the text model |

| Key | Used for | Where to get it | Name in JARVIS |
| --- | --- | --- | --- |
| Anthropic API key (starts with `sk-ant-`) | Claude, the assistant's brain | [Anthropic Console](https://console.anthropic.com/) | `anthropic_api_key` |
| Gemini API key (new keys start with `AQ.`; older ones start with `AIza`, about 39 characters) | Transcription and voice; the assistant when no Anthropic key is set | [Google AI Studio](https://aistudio.google.com/app/apikey) | `gemini_api_key` |

Both are optional: JARVIS starts without them, and AI features report that a key is missing ("Add an Anthropic or Gemini API key in Setup (AI providers) or Preferences").

## Telephony secrets (calls)

The telephony gateway ([CALL_ROUTING](CALL_ROUTING.md#implementation-status-c1)) keeps its credentials in the same encrypted store, with the same status-only rules. All are optional; JARVIS starts without them and calls stay off (`calls.enabled` is false by default).

| Value | Format | Used for | Name in JARVIS | Developer override |
| --- | --- | --- | --- | --- |
| Twilio Account SID | `AC` + 32 hex characters | REST calls (basic auth user) and checking that webhooks and Media Streams come from this account | `twilio_account_sid` | `JARVIS_TWILIO_ACCOUNT_SID` |
| Twilio Auth Token (primary) | 32 hex characters | REST basic auth password **and** the key Twilio signs every webhook and Media Stream upgrade with (`X-Twilio-Signature`) | `twilio_auth_token` | `JARVIS_TWILIO_AUTH_TOKEN` |
| JARVIS's Twilio number | E.164 Malaysian number, `+60...` | Caller ID for every outbound call (never anything else) and the loop guard | `twilio_phone_number` | `JARVIS_TWILIO_PHONE_NUMBER` |
| Owner's mobile number | E.164 | Owner briefings need no grant; every other number does | `owner_phone_number` | `JARVIS_OWNER_PHONE_NUMBER` |
| Cloudflare tunnel token | The token from the named tunnel's install command (starts with `ey`) | Running `cloudflared tunnel run`; passed to cloudflared as the `TUNNEL_TOKEN` environment variable, never on its command line | `cloudflare_tunnel_token` | `JARVIS_CLOUDFLARE_TUNNEL_TOKEN` |
| Call briefing PIN (optional) | 4-8 digits | Spoken by the owner on a briefing call before JARVIS shares the call details (formerly `calls.briefing_pin` in settings.json; moved here at startup and refused as a setting since C3) | `call_briefing_pin` | `JARVIS_CALL_BRIEFING_PIN` |

Checks: the Account SID and Auth Token are tested together with one `GET https://api.twilio.com/2010-04-01/Accounts/<sid>.json` (basic auth, 10 second timeout, Windows certificate store); testing one before the other is saved returns `incomplete`. The phone numbers, the tunnel token and the briefing PIN have no online check (`no_check`); their format is validated when saved. The overrides use `JARVIS_`-prefixed names so a developer's global `TWILIO_*` variables are never picked up by accident. Set them with `scripts/jarvis-secrets.py set <name>` (standard input only) or the owner-only `secrets_set` route; there is no Preferences screen for them yet.

## Which model answers (task router)

`backend/llm/router.py` picks the provider for each request; nothing is decided at startup.

- `chat` uses the chosen Claude model (`assistant.claude_model`, Sonnet 5.5 by default) at the chosen effort (`assistant.effort`, medium by default) when an Anthropic key is configured, otherwise the chosen Gemini model (`assistant.gemini_model`, default `gemini-3.8-flash`).
- `fast` and `summary` use Claude Haiku 5.5 at `low` effort when an Anthropic key is configured, otherwise the default Gemini text model. The model and effort settings never change them.
- `transcription` always uses Gemini.

Settings (`settings.json`, validated by `SettingsPatch`):

| Setting | Values | Effect |
| --- | --- | --- |
| `assistant.brain` | `auto` (default), `claude`, `gemini` | `auto` follows the rules above. `claude` without an Anthropic key is a configuration error (`provider_not_configured`), never a silent switch to Gemini. `gemini` always uses Gemini. |
| `assistant.owner_name` | Up to 80 printable characters, default empty | Adds "The owner's name is ...; use it sparingly." to the system prompt. |
| `assistant.address` | `sir` (default), `maam`, `name`, `none` | How the Classic JARVIS persona addresses the owner: "sir" ("tuan" in Malay), "ma'am" ("puan"), by name (needs `owner_name`), or no form of address. Preferences > AI, "How JARVIS addresses you". Calls to third parties never use it. |
| `assistant.web_search` | `true` (default), `false` | Lets the Claude brain search and fetch the web (see "Web search and web fetch (Claude)"). The Gemini brain never searches. |
| `assistant.claude_model` | `claude-sonnet-5-5` (default), `claude-haiku-5-5` | The Claude brain for chat: Sonnet 5.5 is the smartest, Haiku 5.5 the fastest and cheapest. |
| `assistant.effort` | `low`, `medium` (default), `high` | `output_config.effort` on the Claude brain's chat turns. Higher effort thinks longer and costs more. `xhigh` and `max` are rejected on purpose: slow and costly for an assistant. Does not apply to Gemini, which manages its own thinking (every thinking config hung on `gemini-3.8-flash` on 7 Nov 2026, `llm/gemini.py`). |
| `assistant.gemini_model` | A `gemini-` model id, 1-80 characters (letters, digits, `.`, `_`, `-`), default `gemini-3.8-flash` | The Gemini brain for chat, picked from the `brain_models` list. An empty or stale saved value falls back to the default; a model Google rejects gives the usual plain provider error. |

Environment overrides: `JARVIS_BRAIN_MODEL` (wins over `assistant.claude_model`), `JARVIS_FAST_MODEL` (default `claude-haiku-5-5`) and `JARVIS_TEXT_MODEL` (wins over `assistant.gemini_model`).

**Switching model mid-conversation** drops the old reasoning: thinking blocks are bound to the model that wrote them, and requests send `block_binding.prefix_mismatch_behavior: "drop_block"`, so a switch drops them instead of failing. Prompt caches are per model, so the first turn after a switch is uncached.

**`brain_models`** (owner-only socket route, read-only; `backend/llm/catalog.py`, served by `SettingsTransport`) answers `{ok, claude: [{id, label, note}], gemini: [{id, label}], efforts: ["low", "medium", "high"]}` for the Preferences picker. The Claude list is fixed (Sonnet 5.5 "Smartest", Haiku 5.5 "Fastest, cheapest"). The Gemini list comes from one google-genai `client.aio.models.list` call: `gemini-*` models whose `supported_actions` include `generateContent`, without TTS, Live, embedding, image or audio models. It is bounded to 10 s and cached for an hour per key (a failed call is retried after 5 minutes). The default text model and the saved `assistant.gemini_model` are always included; with no Gemini key, or when the call fails, the list is just those.

`TaskRouter.status()` also reports the saved `effort`, `claude_model` and `gemini_model`.

The capability center reports the active brain (`brain` in `capability_diagnostics`, and the text card's model and "AI model: Claude Sonnet 5.5" reason); the `text_ready` socket event carries the same `brain` object.

## How JARVIS calls Claude

- One stable system prompt (the JARVIS persona) for both providers, with no timestamps. Volatile facts (local time, project name, and the memory-is-untrusted note when project memory is attached) go in a mid-conversation `{"role": "system"}` message right after that turn's user message.
- Adaptive thinking with `output_config.effort`: `assistant.effort` (default `medium`) for the desktop assistant (desktop chat, quick assistant and reviewed voice share one conversation), `low` for phone chat and Haiku routes. Effort only changes within a conversation when the owner changes the setting. No `temperature`, `top_p` or `top_k`; `tool_choice` stays at its `auto` default.
- Tools come from the existing dispatcher schemas, sorted by name, with `eager_input_streaming`. Every tool input is validated by the dispatcher; invalid input, a disabled tool or a declined approval goes back to Claude as a `tool_result` with `is_error: true`. All results of one assistant turn return in one user message.
- Each assistant turn is stored verbatim, including thinking blocks and signatures, and replayed unchanged; history is append-only. Requests send beta `thinking-binding-controls-2026-08-01` with `block_binding.prefix_mismatch_behavior: "drop_block"`, so an unavoidable edit (history trimmed after 10 turns, a changed tool list) drops old reasoning instead of failing. The desktop and phone only ever receive the text of each turn.
- Sonnet requests opt into server-side refusal fallback (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`). Haiku 5.5 has no server-side fallback, so its requests do not send it. A refusal shows a plain message; the category is not shown.
- Top-level automatic prompt caching (`cache_control: {"type": "ephemeral"}`), streaming with the SDK's stream helper and `max_tokens` 32000 (lower when a usage cap is enabled). The SDK's default retries (2) stay on.
- Errors: rejected key (`provider_key_invalid`), rate limited (`provider_rate_limited`, with the retry-after time), provider unavailable including overloaded (`provider_unavailable`), network or TLS (`provider_network`), timeout (`provider_timeout`), refusal (`provider_refused`), anything else `provider_failed`. Keys and prompts are never logged.

## Web search and web fetch (Claude)

With `assistant.web_search` on (the default), `backend/llm/router.py` builds the `chat` route's `ClaudeProvider` with `web_search=True`, and `ClaudeProvider.request()` appends two Anthropic server tools after the dispatcher's tools:

```json
{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}
{"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 3}
```

- Anthropic runs them; JARVIS executes nothing. The `_20260209` versions filter results with code execution under the hood, so the code execution tool is never declared. `max_uses` caps each tool at 3 uses per turn (a resumed turn counts as the same turn). Web fetch only opens URLs already in the conversation (typed by the owner or found by a search).
- Only tool-using brain turns get them: desktop chat, the Quick assistant and reviewed voice. Deliberately tool-free requests stay tool-free (phone chat, a camera look), and the `fast` and `summary` routes (call triage, summaries, the stalled-step retry) are built with `web_search=False`. Exception: a request whose history already holds server tool blocks always declares both tools so the history can replay; on Haiku they are declared with `allowed_callers: ["direct"]`. Turning the setting off therefore takes full effect in a new conversation.
- Results arrive as content blocks, never exceptions: `server_tool_use` (the query or URL), `web_search_tool_result`, `web_fetch_tool_result`, and with dynamic filtering the code execution blocks behind it. A failed search or fetch is a result block whose `content` is an error object (for example `max_uses_exceeded`); Claude reads it and answers. All of these stay in the stored turn verbatim (including `encrypted_content` and `encrypted_index`, which the API needs back) and replay unchanged. Only `tool_use` blocks are client calls; server blocks never reach the dispatcher.
- Cited answers come back split into several `text` blocks, each cited one carrying a `citations` list. The spoken and visible text is the text blocks joined (one space where a search sits between two runs); citation objects stay only in the stored blocks.
- `pause_turn`: a long server tool loop can stop with `stop_reason: "pause_turn"`. The provider sends the same request again with the paused content appended verbatim as the trailing assistant message (no "continue" user message), up to 3 times, so callers see one finished turn whose blocks are every part's blocks in order. A turn still paused after that fails with `provider_incomplete` ("Claude's web search didn't finish in time. Try again.") and nothing is stored. Each resumed request's content block starts count as progress for the first-token deadline, and the whole loop runs inside the step's time budget.
- Queries, URLs and results are never logged.
- CAD planning (`services/cad.py`, `services/cad_changes.py`, through `create_text_provider()`) builds the chat route with `web_search=False`: planning never searches the web. `TaskRouter.provider(task, web_search=False)` forces it off whatever the setting.

## Tool search

JARVIS has more brain tools (about 50) than a model picks well from at once. Past **25 client tools** (`TOOL_SEARCH_THRESHOLD`, `backend/services/tool_groups.py`) a turn stops loading every definition. At or below it nothing changes.

**Claude** (`ClaudeProvider.request()`, `with_tool_search` in `backend/llm/claude.py`; Sonnet 5.5 and Haiku 5.5 both support it, per the Anthropic tool search page's model table):

```json
{"type": "tool_search_tool_bm25_20251119", "name": "tool_search_tool_bm25"}
```

- Every tool is still declared on every request (the API needs the definitions to search and to expand what it finds). The core set loads; every other client tool is sent with `"defer_loading": true` and loads only when Claude's search returns it as a `tool_reference`. No beta header is needed.
- Core set (`CORE_TOOLS`; names that are not registered are skipped): `weather`, `memory_search`, `memory_remember`, `list_reminders`, `create_reminder`, `calendar_events`, `home_devices`, `home_control`, `start_live_design`, `look_through_camera`, `look_at_screen`, `routine_run`, `load_skill`.
- Never deferred: the search tool itself, and the server tools `web_search` and `web_fetch`. At least one tool is always loaded, so the API's "all tools deferred" 400 can't happen. No deferred tool carries `cache_control` (also a 400).
- The whole list (client tools, search tool, web tools) is sorted by name, so the cached tools + system prefix is byte-stable from turn to turn; deferred definitions sit outside the cached prefix.
- The world gate (S1.3, "When the brain is offered the globe" in [WORLD_VIEW.md](WORLD_VIEW.md)) changes from "leave out" to "defer": `world_show`, `world_tour` and `mcp__gev__*` are always declared but deferred, and load as core only on a turn the gate allows (a globe request, the World page open, a follow-up to a world turn). A weather turn never loads them: `weather` is core.
- The search's blocks (`server_tool_use` named `tool_search_tool_bm25`, `tool_search_tool_result`) stay in the stored turn verbatim like the web ones; a history that holds them always replays with tool search on. A tool search result is not web content, so it never taints the turn, and it is not announced as a progress step.

**Gemini** (and any other non-Claude brain) has no server-side search. `backend/services/tool_index.py` keeps a small BM25 index over the model-visible tools' names (counted twice), descriptions and argument names and descriptions, lower-cased, split on non-letters (`print_stl` → `print`, `stl`) with a light suffix strip ("printer", "printing" → "print"). It is cached and rebuilt when the dispatcher's tool set changes. Each step declares the core set, then the world group if the gate allows it, then the top 8 matches for the owner's request, never more than 30 tools; a call to a tool left out gets `tool_unavailable`. Nothing is logged from the index.

The `turn_timing` line (below) carries `tools_declared=<n> deferred=<n>`: the client tools the turn's last model step declared, and how many of them were deferred (always 0 on Gemini, which narrows instead).

## Streamed replies (typed chat)

Typed desktop chat (the workspace and the Quick assistant) streams the answer as the model writes it, for both providers. Live voice (`ask_brain`) and phone chat call the same service without a stream and still get the final text only.

- Claude streams through the SDK's stream helper (`text` events). Gemini streams with `generate_content_stream`; the turn is reassembled from every streamed part, signed parts included, so tool steps replay exactly as before. Usage receipts and the 45 s per-step budget are unchanged.
- While text arrives the core sends `transcription_delta` `{request_id, conversation_id, step, text}` to the socket that sent the request. `step` is the 0-based tool-loop step and `text` is that step's text so far (cumulative within the step, capped at 128,000 characters); each step starts again from empty. At most one event per 50 ms, latest text wins. A step that ends in tool calls first delivers its text, then sends `text_status` `{state: "processing", phase: "tool", ...}`.
- Text written before a tool call is narration, not the answer. The desktop moves it under the JARVIS · WORKING line (text-3, at most two lines) while the tool runs; the JARVIS message shows only the newest step's text and starts empty for the next step. The narration clears when the next step's text starts or the final arrives.
- The final `transcription` is unchanged and authoritative: the desktop replaces the streamed text with it, and because the message holds only the last step's text, the replace never shrinks it. No delta is sent after it.
- Failures: before any text, the same mapped provider errors as before, including Gemini's one retry on 500/503. After some text, no retry; the request ends with the mapped `error` and the partial text is never stored in history.
- `cancel_conversation` cancels the request at once: the provider stream closes, no further delta, result or transcription is sent, only the usual `text_status` idle. The desktop keeps the partial text marked STOPPED (also after a failure or a disconnect mid-stream); if the message is empty because a tool step was running, the last narration becomes its text.
- The Quick assistant log follows the newest message while the owner has not scrolled up, and again once they are back near the bottom.
- The timing line adds `first_text_ms` (time to the first streamed text, `-` when nothing streamed). Reply text is never logged.

## Costs

Every Claude request has a usage receipt (Usage center) with `input_tokens`, `output_tokens`, `cache_creation_input_tokens` and `cache_read_input_tokens`, and a list-price estimate `estimated_cost_microusd`. Estimates are not invoices. Prices live in one table, `backend/llm/pricing.py`:

| Model | Input | Output | Cache write (5 min) | Cache read |
| --- | --- | --- | --- | --- |
| Claude Sonnet 5.5 | $2.00 | $10.00 | $2.50 | $0.20 |
| Claude Haiku 5.5, prompts up to 100K tokens | $0.10 | $0.50 | $0.125 | $0.01 |
| Claude Haiku 5.5, prompts over 100K tokens | $0.50 | $2.50 | $0.625 | $0.05 |

Prices are US dollars per million tokens. When a refused Sonnet request is rescued by the server-side fallback, the receipt sums every attempt (`usage.iterations`) and records `fallback_attempts`.

Web search is billed per request on top of tokens: **$10 per 1,000 searches** ($0.01 each; a search that fails with an error is not billed). Web fetch has no per-request charge. Search results and fetched pages are billed as input tokens, in the turn and every later turn that replays them. The receipt records `web_search_requests` and `web_fetch_requests` from `usage.server_tool_use` (summed over a resumed `pause_turn`, kept out of `total_tokens`), and the estimate adds the search price (`CLAUDE_SERVER_TOOL_PRICES` in `pricing.py`). With `max_uses: 3`, one turn adds at most $0.03 in search fees.

## Fallback to Gemini

With no Anthropic key (and `assistant.brain` at `auto`), chat, phone chat and fast work use the Gemini text model with the same persona. Gemini keeps text-only history; signed tool content stays within the request. Turns from either provider share one history, so the brain can change between turns.

## Where keys are stored

Keys are stored in the profile database (`assistant.sqlite3` in the data directory), one `secrets` document per key, encrypted with Windows DPAPI for your Windows account like the rest of JARVIS's private data. They are not written to `.env`, settings files or logs.

- Installed versions: `<installation>/data/<version>/database`, the directory the launcher passes as `JARVIS_DATA_DIR`. Each installed version has its own profile, so keys saved for one version are not visible to another. Encrypted backups and recovery copies carry the stored keys with the rest of the profile.
- Development: `JARVIS_DATA_DIR` if set, otherwise `%LOCALAPPDATA%\JARVIS\data-v1`.

Key values never leave the backend. The UI and the command line only see a status: whether a key is configured, its source (`env` or `store`), its last four characters, and the result of the last check.

## Adding keys

**Setup.** After installing and selecting a version, open **04 AI providers** in JARVIS Setup. Enter either key, use **Test** to check it with the provider, then **Save**. Save checks each key first; a key the provider rejects is not saved. If the provider cannot be reached, the key is saved and marked as not yet verified. **Skip for now** leaves keys unset. Setup runs the selected version's own Python with `scripts/jarvis-secrets.py` and passes each key on standard input only.

**Preferences.** Keys can also be managed from Preferences inside JARVIS (owner-only `secrets_status`, `secrets_set`, `secrets_test` and `secrets_clear` routes; the Preferences screen is a later task).

**Command line.** `scripts/jarvis-secrets.py` reads keys from standard input only and refuses keys on the command line:

```powershell
# Development profile (JARVIS_DATA_DIR or %LOCALAPPDATA%\JARVIS\data-v1)
.venv\Scripts\python.exe scripts\jarvis-secrets.py set anthropic_api_key --verify   # prompts without echo
.venv\Scripts\python.exe scripts\jarvis-secrets.py status
.venv\Scripts\python.exe scripts\jarvis-secrets.py test gemini_api_key
.venv\Scripts\python.exe scripts\jarvis-secrets.py clear gemini_api_key

# An installed version (selected version by default, or --slot <id>)
<installation>\versions\<id>\runtime\python\python.exe -I -B <installation>\versions\<id>\scripts\jarvis-secrets.py --installation-root <installation> status

# Any explicit profile database directory
... jarvis-secrets.py --data-dir C:\path\to\database status
```

Exit codes: `0` ok, `2` invalid input, `3` the provider check failed, `4` storage error (including "installation is busy" while JARVIS from that installation is running; quit it first or use Preferences).

`scripts/bootstrap.ps1 -ConfigureKeys` prompts for both keys with hidden input and stores them in the development profile through the same tool.

## Checks

A check makes one cheap authenticated request with a 10 second timeout: Anthropic `GET /v1/models`, Gemini list models. Results are `ok`, `invalid_key` (401/403, or Google's invalid-key 400), `rate_limited` (429), `network_error`, `tls_error` or `unexpected`.

Provider requests verify HTTPS against the Windows certificate store (the `truststore` package), so antivirus HTTPS scanning and corporate proxies whose root is trusted by Windows work. This applies only to provider calls (`services.tls.provider_ssl_context()`); JARVIS's own pinned connections, such as the mobile companion, keep their own certificate checks.

## Time budgets

Every brain turn runs inside a budget of wall time (`TurnBudget`, `services/conversation.py`), so no turn can stall for minutes:

- **The budget.** 60 s for a voice brain turn (`VOICE_TURN_BUDGET_S`, usage feature `voice_brain`, from `ask_brain`), 120 s for everything else: desktop chat, the Quick assistant and phone chat (`TURN_BUDGET_S`). `reply(turn_budget=...)` overrides it (tests use milliseconds).
- **Model steps.** Each step is capped at the smaller of 45 s and the time left. First-token deadline: a step that shows no progress (no streamed content of any kind: text, thinking, tool input) within 20 s (`FIRST_TOKEN_S`) is cancelled and retried once, on the fast route (Claude Haiku 5.5) when the brain is Claude, else once on the same model (Gemini). The retry has only the cap.
- **Tools.** An ordinary tool runs for at most the smaller of its own timeout and the time left, less a reserve kept for the answer (10 s, or a sixth of a shorter budget). A cut tool's result is `{"error": "action_timeout", ...}`, so the model can still answer; a tool with no time left is not run. While a **long-running** tool runs (`ToolSpec.long_running`: `generate_cad`, `build_live_design`, `generate_image`, `world_tour`, `place_task_call`) the budget clock is paused; its own timeout still bounds it. Time the owner spends on an approval card pauses it too.
- **When it runs out.** The loop stops, any unanswered `tool_use` gets a timed-out result (the stored history stays valid for the next turn), and JARVIS answers truthfully with what finished, in the persona's form of address: "I couldn't finish that in time, sir. I got as far as checking the forecast." Logged as `outcome=budget` (below). Never silence.
- **Tool groups.** The world group (`world_show`, `world_tour`, every `mcp__gev__*` tool) is declared only when the request mentions the globe, the World page is open, or the turn follows one that used it ([WORLD_VIEW.md](WORLD_VIEW.md#when-the-brain-is-offered-the-globe)); a weather question gets the `weather` tool ([WEATHER.md](WEATHER.md)). With no JARVIS window, `world_show` and `world_tour` fail at once (`world_no_window`) before the globe is started.

## Voice: quick answers and two-phase `ask_brain`

- **Quick answers.** The Live session answers `quick_weather`, `quick_agenda` and `quick_home` itself, read-only and within 5 s, with no brain turn ([WEATHER.md](WEATHER.md#quick-answers-by-voice), [VOICE_CONNECTION_POLICY.md](VOICE_CONNECTION_POLICY.md#quick-answers-s12)).
- **Two-phase `ask_brain`.** A brain turn that finishes within 4 s answers the Live call directly. Later, the call is answered at 4 s with `{"status": "working", "say": "<phrase>, sir.", "then": "wait silently"}`, where the phrase comes from a tool that really started (`PROGRESS_PHRASES`, e.g. "Checking the forecast") or is "Working on it". Further real progress lines follow as Live text turns ("Say exactly: …", at most one per 12 s), and the answer comes as a final text turn ("Answer for the owner's request: …"). The voice model is told never to describe delays or status itself. If the session closes mid-task, the brain finishes, the answer is stored in the conversation and nothing is sent to the closed session. Details: [VOICE_CONNECTION_POLICY.md](VOICE_CONNECTION_POLICY.md#two-phase-answers-s15).

## Why JARVIS never hangs

A simple question used to hang for minutes. Five causes lined up (docs/handover/9NovWork-specs.md S1); each now has a fix:

1. No weather tool: the brain has `weather` ([WEATHER.md](WEATHER.md)) and, with Claude, web search and fetch (above).
2. Weather questions went to the globe: the world group is offered only for globe requests, and `world_show`'s description sends weather to the `weather` tool.
3. No limit on a turn: the 60 s / 120 s budget, the 20 s first-token deadline and the truthful budget answer (Time budgets).
4. Tools that wait minutes: every ordinary tool is cut at the budget, and the globe tools fail in under a second with no window instead of starting the globe first.
5. Voice waiting in silence and inventing status: quick answers with no brain hop, and the two-phase `ask_brain` with real progress lines only.

`tests/test_no_stall.py` proves this end to end with fake providers and millisecond budgets, one test per guard, each naming the cause it covers: a weather turn is never offered the world group; a silent model falls back at the first-token deadline and ends inside the budget; a hanging tool is cut and the turn still answers with a valid history; a long-running tool pauses the budget; `ask_brain` answers in two phases and a closed session still stores the answer; `quick_weather` answers without a brain turn; `world_show` with no window fails in under a second without starting the globe. Run it with `.venv\Scripts\python.exe -m pytest -q tests/test_no_stall.py`. To see it on a real setup, press **Run a check** (below) and read the `turn_timing` lines.

## Turn timing and the brain check

Every brain turn (desktop chat, the Quick assistant, phone chat and reviewed voice) ends with one content-free INFO line from `services.conversation`, whatever its outcome:

```
turn_timing request_id=6f0c… origin=voice provider=claude model=claude-sonnet-5-5 effort=medium first_token_ms=1430 total_ms=4210 outcome=ok steps=[model:1610,weather:380,model:2190] input_tokens=10520 output_tokens=212 tools_declared=51 deferred=39 memory_facts=0
```

- `origin`: `voice` for a voice brain turn (usage feature `voice_brain`), else `chat`.
- `provider`, `model`: the turn's brain (a stalled step's retry on the fast route still shows the brain; its step appears as another `model:` entry). `effort`: what a Claude turn sends; `-` for Gemini.
- `first_token_ms`: wall time from the turn's start to the first progress (any streamed content) of the first model step; a step that does not stream counts its answer. `-` when no model step answered.
- `total_ms`: the whole turn, wall time (approval waits included).
- `outcome`: `ok`, `budget` (the turn budget ran out and JARVIS answered with what finished), `error` (any failure, including no provider configured) or `cancelled`.
- `steps`: every model step and tool in order with its ms (`?` if it never recorded one). Tool names only; a name that is not a plain identifier reads `tool`. Claude's server-side web search runs inside a model step.
- `input_tokens`, `output_tokens`: summed over the turn's model steps (Claude's cached prompt tokens included in input).
- `tools_declared`, `deferred`: client tools declared to the brain and how many were deferred ([Tool search](#tool-search)); server tools are not counted.
- Never message text, places, tool arguments or results. The service keeps the last one as `ConversationService.last_turn_timing` (a dict with the same fields; `steps` as `[{name, ms}]`).
- The older lines stay: `AI provider request: …` (per request, with the failure code and the first streamed text time) and, on a budget stop, `Brain turn stopped: … outcome=budget` (with the budget and the unheld time used).

**Run a check** (Preferences > AI, under Brain; RPC `brain_check`, owner renderer only): sends "Reply with the single word: ready." through the chat route with no tools and web search off (30 s cap, metered as `brain_check`), then looks up the weather for the home town ([WEATHER.md](WEATHER.md#the-brain-check)). The answer is `{ok: true, brain: {ok, provider, model, label, effort, ms, code?, message?}, weather: {...}}`; `ok: true` means the check ran, each half says how it went. The page shows lines such as "Claude Sonnet 5.5 · Medium effort answered in 1.8 s", and a failure in the warn colour with the core's plain message. One log line: `brain_check provider=… model=… brain_ms=… weather_ms=… outcome=ok|brain_<code>|weather_<code>`. It spends a few tokens, so it runs only when the owner presses the button; tests use fakes.

## Developer override

A real value in the `ANTHROPIC_API_KEY` or `GEMINI_API_KEY` environment variable (or a local `.env`) takes precedence over the store. Placeholder values such as `your_api_key_here` or `changeme` are ignored, so the stored key is used. Bootstrap no longer creates `.env`; copy `.env.example` yourself if you want other overrides.
