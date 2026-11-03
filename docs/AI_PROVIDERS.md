# AI providers

INARA uses two providers. Claude is the assistant's brain; Gemini handles audio.

| Work | Model | Provider | Notes |
| --- | --- | --- | --- |
| Chat, planning and tool use (desktop chat, quick assistant, reviewed voice input, phone chat) | Claude Sonnet 5.5 (`claude-sonnet-5-5`) | Anthropic | Gemini text model when no Anthropic key is configured |
| Fast summaries and classification (`fast` / `summary` routes; call summaries later) | Claude Haiku 5.5 (`claude-haiku-5-5`) | Anthropic | Gemini text model when no Anthropic key is configured |
| Transcription of reviewed push-to-talk | Gemini (`INARA_TRANSCRIPTION_MODEL`, else the text model) | Google | Always Gemini |
| Live voice (later), vision and legacy CAD | Gemini | Google | Vision and legacy CAD follow the text model |

| Key | Used for | Where to get it | Name in INARA |
| --- | --- | --- | --- |
| Anthropic API key (starts with `sk-ant-`) | Claude, the assistant's brain | [Anthropic Console](https://console.anthropic.com/) | `anthropic_api_key` |
| Gemini API key (starts with `AIza`, about 39 characters) | Transcription and voice; the assistant when no Anthropic key is set | [Google AI Studio](https://aistudio.google.com/app/apikey) | `gemini_api_key` |

Both are optional: INARA starts without them, and AI features report that a key is missing ("Add an Anthropic or Gemini API key in Setup (AI providers) or Preferences").

## Telephony secrets (calls)

The telephony gateway ([CALL_ROUTING](CALL_ROUTING.md#implementation-status-c1)) keeps its credentials in the same encrypted store, with the same status-only rules. All are optional; INARA starts without them and calls stay off (`calls.enabled` is false by default).

| Value | Format | Used for | Name in INARA | Developer override |
| --- | --- | --- | --- | --- |
| Twilio Account SID | `AC` + 32 hex characters | REST calls (basic auth user) and checking that webhooks and Media Streams come from this account | `twilio_account_sid` | `INARA_TWILIO_ACCOUNT_SID` |
| Twilio Auth Token (primary) | 32 hex characters | REST basic auth password **and** the key Twilio signs every webhook and Media Stream upgrade with (`X-Twilio-Signature`) | `twilio_auth_token` | `INARA_TWILIO_AUTH_TOKEN` |
| INARA's Twilio number | E.164 Malaysian number, `+60...` | Caller ID for every outbound call (never anything else) and the loop guard | `twilio_phone_number` | `INARA_TWILIO_PHONE_NUMBER` |
| Owner's mobile number | E.164 | Owner briefings need no grant; every other number does | `owner_phone_number` | `INARA_OWNER_PHONE_NUMBER` |
| Cloudflare tunnel token | The token from the named tunnel's install command (starts with `ey`) | Running `cloudflared tunnel run`; passed to cloudflared as the `TUNNEL_TOKEN` environment variable, never on its command line | `cloudflare_tunnel_token` | `INARA_CLOUDFLARE_TUNNEL_TOKEN` |
| Call briefing PIN (optional) | 4-8 digits | Spoken by the owner on a briefing call before INARA shares the call details (formerly `calls.briefing_pin` in settings.json; moved here at startup and refused as a setting since C3) | `call_briefing_pin` | `INARA_CALL_BRIEFING_PIN` |

Checks: the Account SID and Auth Token are tested together with one `GET https://api.twilio.com/2010-04-01/Accounts/<sid>.json` (basic auth, 10 second timeout, Windows certificate store); testing one before the other is saved returns `incomplete`. The phone numbers, the tunnel token and the briefing PIN have no online check (`no_check`); their format is validated when saved. The overrides use `INARA_`-prefixed names so a developer's global `TWILIO_*` variables are never picked up by accident. Set them with `scripts/inara-secrets.py set <name>` (standard input only) or the owner-only `secrets_set` route; there is no Preferences screen for them yet.

## Which model answers (task router)

`backend/llm/router.py` picks the provider for each request; nothing is decided at startup.

- `chat` uses Claude Sonnet 5.5 when an Anthropic key is configured, otherwise the Gemini text model (`INARA_TEXT_MODEL`, default `gemini-3.8-flash`).
- `fast` and `summary` use Claude Haiku 5.5 when an Anthropic key is configured, otherwise the Gemini text model.
- `transcription` always uses Gemini.

Settings (`settings.json`, validated by `SettingsPatch`):

| Setting | Values | Effect |
| --- | --- | --- |
| `assistant.brain` | `auto` (default), `claude`, `gemini` | `auto` follows the rules above. `claude` without an Anthropic key is a configuration error (`provider_not_configured`), never a silent switch to Gemini. `gemini` always uses Gemini. |
| `assistant.owner_name` | Up to 80 printable characters, default empty | Adds "The owner's name is ...; use it sparingly." to the system prompt. |

Environment overrides: `INARA_BRAIN_MODEL` (default `claude-sonnet-5-5`) and `INARA_FAST_MODEL` (default `claude-haiku-5-5`).

The capability center reports the active brain (`brain` in `capability_diagnostics`, and the text card's model and "AI model: Claude Sonnet 5.5" reason); the `text_ready` socket event carries the same `brain` object.

## How INARA calls Claude

- One stable system prompt (the INARA persona) for both providers, with no timestamps. Volatile facts (local time, project name, and the memory-is-untrusted note when project memory is attached) go in a mid-conversation `{"role": "system"}` message right after that turn's user message.
- Adaptive thinking with `output_config.effort`: `medium` for the desktop assistant (desktop chat, quick assistant and reviewed voice share one conversation), `low` for phone chat and Haiku routes. Effort never changes within a conversation. No `temperature`, `top_p` or `top_k`; `tool_choice` stays at its `auto` default.
- Tools come from the existing dispatcher schemas, sorted by name, with `eager_input_streaming`. Every tool input is validated by the dispatcher; invalid input, a disabled tool or a declined approval goes back to Claude as a `tool_result` with `is_error: true`. All results of one assistant turn return in one user message.
- Each assistant turn is stored verbatim, including thinking blocks and signatures, and replayed unchanged; history is append-only. Requests send beta `thinking-binding-controls-2026-08-01` with `block_binding.prefix_mismatch_behavior: "drop_block"`, so an unavoidable edit (history trimmed after 10 turns, a changed tool list) drops old reasoning instead of failing. The desktop and phone only ever receive the text of each turn.
- Sonnet requests opt into server-side refusal fallback (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`). Haiku 5.5 has no server-side fallback, so its requests do not send it. A refusal shows a plain message; the category is not shown.
- Top-level automatic prompt caching (`cache_control: {"type": "ephemeral"}`), streaming with the SDK's stream helper and `max_tokens` 32000 (lower when a usage cap is enabled). The SDK's default retries (2) stay on.
- Errors: rejected key (`provider_key_invalid`), rate limited (`provider_rate_limited`, with the retry-after time), provider unavailable including overloaded (`provider_unavailable`), network or TLS (`provider_network`), timeout (`provider_timeout`), refusal (`provider_refused`), anything else `provider_failed`. Keys and prompts are never logged.

## Costs

Every Claude request has a usage receipt (Usage center) with `input_tokens`, `output_tokens`, `cache_creation_input_tokens` and `cache_read_input_tokens`, and a list-price estimate `estimated_cost_microusd`. Estimates are not invoices. Prices live in one table, `backend/llm/pricing.py`:

| Model | Input | Output | Cache write (5 min) | Cache read |
| --- | --- | --- | --- | --- |
| Claude Sonnet 5.5 | $2.00 | $10.00 | $2.50 | $0.20 |
| Claude Haiku 5.5, prompts up to 100K tokens | $0.10 | $0.50 | $0.125 | $0.01 |
| Claude Haiku 5.5, prompts over 100K tokens | $0.50 | $2.50 | $0.625 | $0.05 |

Prices are US dollars per million tokens. When a refused Sonnet request is rescued by the server-side fallback, the receipt sums every attempt (`usage.iterations`) and records `fallback_attempts`.

## Fallback to Gemini

With no Anthropic key (and `assistant.brain` at `auto`), chat, phone chat and fast work use the Gemini text model with the same persona. Gemini keeps text-only history; signed tool content stays within the request. Turns from either provider share one history, so the brain can change between turns.

## Where keys are stored

Keys are stored in the profile database (`assistant.sqlite3` in the data directory), one `secrets` document per key, encrypted with Windows DPAPI for your Windows account like the rest of INARA's private data. They are not written to `.env`, settings files or logs.

- Installed versions: `<installation>/data/<version>/database`, the directory the launcher passes as `INARA_DATA_DIR`. Each installed version has its own profile, so keys saved for one version are not visible to another. Encrypted backups and recovery copies carry the stored keys with the rest of the profile.
- Development: `INARA_DATA_DIR` if set, otherwise `%LOCALAPPDATA%\INARA\data-v1`.

Key values never leave the backend. The UI and the command line only see a status: whether a key is configured, its source (`env` or `store`), its last four characters, and the result of the last check.

## Adding keys

**Setup.** After installing and selecting a version, open **04 AI providers** in INARA Setup. Enter either key, use **Test** to check it with the provider, then **Save**. Save checks each key first; a key the provider rejects is not saved. If the provider cannot be reached, the key is saved and marked as not yet verified. **Skip for now** leaves keys unset. Setup runs the selected version's own Python with `scripts/inara-secrets.py` and passes each key on standard input only.

**Preferences.** Keys can also be managed from Preferences inside INARA (owner-only `secrets_status`, `secrets_set`, `secrets_test` and `secrets_clear` routes; the Preferences screen is a later task).

**Command line.** `scripts/inara-secrets.py` reads keys from standard input only and refuses keys on the command line:

```powershell
# Development profile (INARA_DATA_DIR or %LOCALAPPDATA%\INARA\data-v1)
.venv\Scripts\python.exe scripts\inara-secrets.py set anthropic_api_key --verify   # prompts without echo
.venv\Scripts\python.exe scripts\inara-secrets.py status
.venv\Scripts\python.exe scripts\inara-secrets.py test gemini_api_key
.venv\Scripts\python.exe scripts\inara-secrets.py clear gemini_api_key

# An installed version (selected version by default, or --slot <id>)
<installation>\versions\<id>\runtime\python\python.exe -I -B <installation>\versions\<id>\scripts\inara-secrets.py --installation-root <installation> status

# Any explicit profile database directory
... inara-secrets.py --data-dir C:\path\to\database status
```

Exit codes: `0` ok, `2` invalid input, `3` the provider check failed, `4` storage error (including "installation is busy" while INARA from that installation is running; quit it first or use Preferences).

`scripts/bootstrap.ps1 -ConfigureKeys` prompts for both keys with hidden input and stores them in the development profile through the same tool.

## Checks

A check makes one cheap authenticated request with a 10 second timeout: Anthropic `GET /v1/models`, Gemini list models. Results are `ok`, `invalid_key` (401/403, or Google's invalid-key 400), `rate_limited` (429), `network_error`, `tls_error` or `unexpected`.

Provider requests verify HTTPS against the Windows certificate store (the `truststore` package), so antivirus HTTPS scanning and corporate proxies whose root is trusted by Windows work. This applies only to provider calls (`services.tls.provider_ssl_context()`); INARA's own pinned connections, such as the mobile companion, keep their own certificate checks.

## Developer override

A real value in the `ANTHROPIC_API_KEY` or `GEMINI_API_KEY` environment variable (or a local `.env`) takes precedence over the store. Placeholder values such as `your_api_key_here` or `changeme` are ignored, so the stored key is used. Bootstrap no longer creates `.env`; copy `.env.example` yourself if you want other overrides.
