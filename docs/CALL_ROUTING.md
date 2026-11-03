# Call routing

Owner decision, 25 October 2026. Status: the C1 telephony gateway and the C2 call agent are built and tested offline ([Implementation status (C1)](#implementation-status-c1), [Implementation status (C2)](#implementation-status-c2)); the C3 orchestration backend is built ([C3 orchestration](#c3-orchestration)); nothing has been verified against a live Twilio number, and the Calls view (C3b), C4 and C5 are not finished. Gate: `sim-call-routing` in [RELEASE_GATES.json](RELEASE_GATES.json).

## Decision

- **SIM calls first.** The owner keeps the existing SIM number; callers still dial it. The carrier conditionally forwards busy / no-answer / unreachable calls to a Twilio Malaysian local number that INARA answers.
- **WhatsApp later**, through a separate WhatsApp Business Cloud API number with the official Calling API. The personal WhatsApp account is not used. WhatsApp text replies and outgoing WhatsApp actions stay excluded (gate `whatsapp-actions`).
- **Parked:** the desktop bridge (Phone Link over Bluetooth, WhatsApp Desktop automation, virtual audio cables) is kept only as a possible "local-only mode" (gate `phone-call-feasibility`, superseded for the SIM path).
- **Models:** Gemini Live for voice and transcription (model `gemini-3.8-live`, built-in female voice, Kore default). Claude Sonnet 5.5 for triage and decisions; Claude Haiku 5.5 for fast summaries.

## Flow

```
Caller dials owner's SIM number
        |
        v
Owner's carrier: conditional forwarding (busy / no reply / unreachable)
        |
        v
Twilio Malaysian local number
        |  Voice webhook over HTTPS, X-Twilio-Signature validated
        v
Cloudflare named tunnel (only /telephony/* exposed)
        |
        v
INARA telephony gateway on the owner's PC (own local listener,
never the core Socket.IO port)
        |  TwiML <Connect><Stream>: bidirectional Media Stream
        |  (WebSocket, mu-law 8 kHz)
        v
Call agent <--> Gemini Live (16 kHz PCM in / 24 kHz out, resampled;
        |       context-window compression + session resumption)
        |  structured outcome via tools
        v
Claude triage and summary --> desktop notification / Calls view
```

## Carrier forwarding codes

Dialled on the owner's phone (GSM):

| Code | Effect |
| --- | --- |
| `**67*<number>#` | Forward when busy |
| `**61*<number>**<seconds>#` | Forward on no reply; owner sets 20-30 s |
| `**62*<number>#` | Forward when unreachable |
| `##002#` | Cancel all conditional forwarding |

Some Malaysian carriers do not allow forwarding to international numbers, so the target is a Malaysian local number.

## Call modes

1. **Screening inbound calls.** INARA opens with: "You've reached <owner>'s phone. I'm INARA, an AI assistant. This call is transcribed." It takes name, reason, urgency, callback number and message. It answers only from an owner-approved facts pack (for example availability) and never makes commitments.
2. **Owner briefing.** When triage says the owner's input is needed (or the caller is a VIP / urgent), INARA calls the owner's mobile from the INARA number, briefs, records the owner's decision and reads it back for confirmation. The owner's spoken confirmation is the approval for that one callback (optional spoken PIN for sensitive actions).
3. **Approved callback.** INARA delivers the approved message, answers clarifying questions within scope, takes a reply and reports back.
4. **Task calls** (for example a restaurant reservation). Claude prepares a call brief: goal, constraints, allowed flexibility and what may be shared (name, party size, time window; never payment details). The owner approves it as a one-use grant bound to the number and the brief hash, expiring after 10 minutes. INARA calls, stays within bounds, confirms details, records the outcome, creates a reminder and reports.

## Safety and policy

- Calls to the owner need no approval. Every other outbound call needs a one-use owner grant.
- AI disclosure at the start of every outbound call.
- Caller ID is INARA's Twilio number; no spoofing.
- Third-party calls: quiet hours (default 21:00-09:00), daily cap (default 10 outbound) and a per-number cooldown.
- Kill switch (tray and Calls view) routes all calls to voicemail.
- Transcripts only by default (no audio recording), DPAPI-encrypted, 7-day retention, deletable by the owner.
- Callers are told the call is transcribed; Malaysia's PDPA 2010 applies to stored personal data.

## Loop guard

If INARA calls the owner and the owner's SIM forwards that call back (busy / no answer), the inbound webhook sees INARA's own number as the caller. The gateway rejects it immediately, marks the owner unreachable and notifies on the desktop. The outbound ring timeout (about 15 s) is shorter than the owner's no-reply forwarding timer.

## Offline fallback

The Twilio number's fallback URL points to static TwiML voicemail ("INARA is offline; please leave a message") with recording and transcription. INARA fetches these when it is back online.

## Costs (indicative; verify current rates)

- Twilio Malaysia local number: about US$4/month.
- Twilio voice: about US$0.0555/min local, US$0.08/min mobile (Twilio pricing page, Aug 2026).
- Carrier forwarding: billed by the owner's carrier at local rates.
- Gemini Live: audio usage per minute.
- Claude triage: cents per call.

## Setup outline

Details will follow in a setup guide (C5).

1. Twilio account and a Malaysian local number (regulatory bundle: ID and proof of a local address). Malaysian verified caller IDs cannot be used for calls to Malaysia.
2. Store the Twilio Account SID, Auth Token and number, and the owner's mobile number, in INARA's encrypted key store. The Auth Token is required because Twilio signs webhooks with it.
3. Create a Cloudflare named tunnel and store its token.
4. Dial the carrier forwarding codes on the phone.
5. Make a test call.

## Build plan

- **C1 Telephony gateway:** separate listener for `/telephony/*`, signature validation, TwiML, Media Stream WebSocket, loop guard, tunnel.
- **C2 Call agent:** mu-law/PCM bridge to Gemini Live, disclosure, screening script, tools for structured outcomes.
- **C3 Approvals, orchestration and Calls view:** triage, owner briefings, one-use grants, limits, kill switch, transcript store.
- **C4 Reservation flow:** call briefs, grant binding, bounded task calls, reminders and reports.
- **C5 Setup guide:** Twilio, regulatory bundle, key store, tunnel, forwarding codes, test call.

## Implementation status (C1)

Built 26-27 October 2026 in `backend/telephony/`; covered by `tests/test_telephony.py` and `tests/test_telephony_gateway.py` (no network, no real Twilio). Off by default: with `calls.enabled` false nothing listens, nothing is spawned and the core starts without any telephony secret.

### What exists

| Part | File | Notes |
| --- | --- | --- |
| Gateway listener | `gateway.py` | Embedded uvicorn on `127.0.0.1`, default port 8790 (`INARA_TELEPHONY_PORT`; 8000 is refused), `SO_EXCLUSIVEADDRUSE`, no server/date headers, 64 KiB bodies and WebSocket frames, no compression. Started and stopped by the core as `calls.enabled` changes. Exactly four paths; anything else, including other methods, is an empty 404. |
| Signatures | `signature.py` | Twilio's algorithm: HMAC-SHA1 with the Auth Token over the public URL (`calls.public_base_url` + the exact raw path and query Twilio requested) + POST params sorted by name (`name+value`, repeated names sorted by value), base64, constant-time compare. The URL is accepted with and without the default `:443`, like Twilio's own libraries. Verified against Twilio's published example vectors. |
| Tokens | `tokens.py` | HMAC-SHA256 with a per-process secret. Stream tokens: bound to CallSid + direction, 2-minute expiry, single use. Outbound tickets: bound to INARA's own call record, 2 minutes, single use. A core restart invalidates both. |
| TwiML | `twiml.py` | ElementTree, so every value is escaped. Inbound: loop guard, then kill switch, then `<Connect><Stream url="wss://<host>/telephony/media">` with `token` and `direction` `<Parameter>`s (Twilio forbids query strings on Stream URLs). Nothing follows `</Connect>`, so closing the stream ends the call. |
| Media Streams | `media.py` | Twilio's bidirectional protocol (`connected`, `start`, `media`, `mark`, `dtmf`, `stop`; out: `media`, `mark`, `clear`). `start` must arrive within 10 s with `audio/x-mulaw` 8000 Hz mono, the configured AccountSid and a valid stream token. 30 s without any message, or one hour in total, ends the stream. |
| Audio | `audio.py` | Table-driven G.711 mu-law (matches the ITU / `audioop` table) and a streaming Kaiser-windowed polyphase resampler (transition band 3.4-4.6 kHz, about 60 dB stopband) for 8 <-> 16 kHz and 24/48 -> 8 kHz. Pure Python: about 2-3 % of one core per call. |
| Outbound | `client.py`, `grants.py` | `TwilioClient.place_call(to, purpose, context, grant=None)` (also `TelephonyService.place_call`); see the policy below. `hangup(call_sid)` ends a call (`Status=completed`). |
| Tunnel | `tunnel.py` | Supervises `cloudflared tunnel --no-autoupdate run` in a kill-on-close Windows job (`resident.win32.WorkspaceProcess`, which now accepts explicit arguments and extra environment). The token is in `TUNNEL_TOKEN` only. cloudflared is found via `INARA_CLOUDFLARED`, `PATH` or `Program Files\cloudflared`; it is never downloaded. Up to three restarts (2/10/30 s), then `failed`. States: `stopped`, `not_configured`, `missing_binary`, `starting`, `running`, `restarting`, `failed`. |
| Status | `service.py`, `transport/telephony.py` | Owner-only `calls_status`: kill switch, `when_disabled`, public URL, each telephony secret's configured/verified/source, gateway listening/host/port, tunnel state, agent (`none`/`stub`/`ready`), active calls, today's third-party call count, last start failure, and `ready` (enabled + required secrets + public URL + gateway listening + tunnel running). Never a secret value. |
| Stub agent | `stub_agent.py` | **Stub until C2.** Enabled only with `INARA_TELEPHONY_STUB_AGENT=1`: plays a 0.4 s synthesized 440 Hz tone, holds at most 10 s and hangs up. Without an agent, inbound calls take the `calls.when_disabled` path. |

### Security model

- **Webhooks:** every POST needs a valid `X-Twilio-Signature` over the public URL and its form params, `application/x-www-form-urlencoded`, and `AccountSid` equal to the stored SID. Missing configuration (no public URL or Auth Token) fails closed. Failures are 403 with an empty body; the log records only a reason code and the path (`inara.telephony.*`, redacted).
- **Media Stream:** the WebSocket upgrade needs `X-Twilio-Signature` over the public stream URL with no params (`wss://` or `https://` spelling, with or without `:443`), otherwise HTTP 403. The `start` message must then redeem the single-use stream token for its own CallSid and direction, so a leaked URL or a captured handshake cannot be replayed.
- **Outbound policy (enforced in code):** the owner's number needs nothing else. Any other number needs a grant from `TelephonyService.grants.issue(number, purpose, ttl)` (C3 issues it after approval): bound to the exact E.164 number and the SHA-256 of the purpose, expiring after at most 10 minutes, consumed by the first `place_call` that uses it. Grants built outside the registry are refused. Third-party calls also respect quiet hours (default 21:00-09:00 Asia/Kuala_Lumpur; equal start and end disables them), a daily cap (default 10) and a per-number cooldown (default 60 minutes), checked before the grant is consumed and recorded in the profile database (numbers stored as keyed hashes). `From` is always `twilio_phone_number`; there is no parameter to change it. The ring `Timeout` is 15 s; status callbacks go to `/telephony/status` (initiated, ringing, answered, completed). Twilio errors return only a code.
- **Loop guard (runs before the kill switch):** an inbound call whose `From` is INARA's own number gets `<Reject/>` and an internal `telephony.owner_unreachable` event (with the in-flight owner call, if any). A call with a withheld `From`, `ForwardedFrom` equal to the owner's number, and either `CallerName` equal to INARA's number or an owner call placed in the last two minutes, is rejected the same way. Without INARA's own number configured, inbound calls take the unavailable path because the guard cannot run.
- **Kill switch:** `calls.enabled` false stops the tunnel and the gateway (ending active streams); requests already in flight get voicemail or a hang-up per `calls.when_disabled`. With the gateway down, Twilio uses the number's Fallback URL (static voicemail TwiML, C5).

What Twilio sends for forwarded calls (from Twilio's voice webhook documentation; not verified on a Malaysian carrier): `From`/`Caller` carry the original caller ID as the forwarding carrier presents it (normally INARA's number when the owner's SIM forwards INARA's call back); withheld IDs arrive as `Anonymous`, `Restricted` or `Unknown`, or as keypad spellings such as `+266696687` (ANONYMOUS); `ForwardedFrom` is set only when the carrier passes diversion information; `CallerName` only when Caller ID lookup is enabled on the number. The `From` check is the primary guard; the withheld-caller rule is best effort.

Internal events (event bus only, never sent to a renderer): `telephony.owner_unreachable`, `telephony.call_status`, `telephony.voicemail` (CallSid, RecordingSid and duration after a voicemail).

### CallAudioSession (the C2 interface)

`TelephonyService.set_agent(agent, input_rate=16000)` installs `async def agent(session)`, awaited once per connected call:

- `async for frame in session` or `await session.read(timeout)`: inbound PCM16 LE mono at `session.input_rate` (8 or 16 kHz), about 20 ms per frame; end of iteration (or `None`) when the call ends. A slow reader loses the oldest frames (`dropped_frames`), never the newest.
- `await session.send(pcm16, rate)`: agent speech at 8, 16, 24 or 48 kHz, resampled to 8 kHz mu-law and sent in 20 ms media messages.
- `await session.mark(name=None)`: a future that resolves True when Twilio has played everything sent before it, False if cleared or the call ends; `session.playing` is true while marks are pending.
- `await session.clear()`: barge-in; Twilio drops unplayed audio and pending marks resolve False.
- `session.digits`: DTMF queue. `session.info`: direction and caller/forwarding details (inbound), or number, owner flag, purpose, context and call id (outbound).
- `await session.hangup()`: ends the stream, which ends the call. If the agent raises, the call ends; when the stream ends first, the agent has 1 s to return before it is cancelled.

### Settings and secrets

`calls.*` in `settings.json` (validated by `SettingsPatch.calls`, merged over the defaults): `enabled` (false), `public_base_url` (`""`; `https://` + hostname only, no path or port), `quiet_hours` `{start, end}` (`21:00` / `09:00`), `daily_outbound_cap` (10; 0-100), `number_cooldown_minutes` (60; 0-10080), `when_disabled` (`voicemail` or `hangup`; default `voicemail`). Secrets: `twilio_account_sid`, `twilio_auth_token`, `twilio_phone_number`, `owner_phone_number`, `cloudflare_tunnel_token` ([AI_PROVIDERS](AI_PROVIDERS.md#telephony-secrets-calls)). Environment: `INARA_TELEPHONY_PORT`, `INARA_CLOUDFLARED`, `INARA_TELEPHONY_STUB_AGENT` (developer only).

Voicemail is `<Say>` + one `<Record maxLength="120">` (stored by Twilio) + `<Hangup/>`; the recording result posts back to the inbound URL and is answered with a short goodbye. Fetching and deleting recordings belongs to C3.

### Not verified offline

- Whether Twilio always sends `X-Twilio-Signature` on the Media Stream upgrade and which URL spelling it signs (`wss://` and `https://` are both accepted). The first live test call must confirm this; otherwise Media Streams are refused with 403.
- Twilio's behaviour when it receives `clear` with marks pending (INARA resolves them locally either way) and any limit on buffered outbound audio.
- What a Malaysian carrier puts in `From` / `ForwardedFrom` when the owner's SIM forwards a call.
- cloudflared itself under the job object (tested with a stand-in process) and the Cloudflare ingress rule (`^/telephony/` -> `http://127.0.0.1:8790`), which is configured on the Cloudflare side.

### Remaining

- **C2 Call agent:** built; see [Implementation status (C2)](#implementation-status-c2).
- **C3 Approvals, orchestration and Calls view:** triage, owner briefings (`place_call` to the owner, handling `owner_unreachable`), issuing grants after approval, the kill switch in the tray and Calls view, a `calls_status` UI, transcripts (DPAPI, 7-day retention), voicemail retrieval and deletion.
- **C4 Reservation flow:** call briefs, grant binding to the brief hash, bounded task calls, reminders and reports.
- **C5 Setup guide:** Twilio number and regulatory bundle, webhook and Fallback URL configuration, tunnel ingress, installing cloudflared, forwarding codes and the first live test call (including the items above).

## Implementation status (C2)

Built 27 October 2026 in `backend/telephony/agent.py` (CallAgent), `briefs.py` (CallBrief, instructions, tool schemas) and `triage.py`; records in `backend/calls/records.py`. Covered by `tests/test_call_agent.py` with a fake Live session and C1's real `CallAudioSession` (no network, no Twilio, no provider). The core installs the agent at startup (`INARA_TELEPHONY_STUB_AGENT=1` still selects the developer stub); calls stay off by default and nothing needs a telephony secret to start. Without a Gemini key the agent reports `unavailable` in `calls_status` and inbound calls take the `calls.when_disabled` path.

### Calls and briefs

Every call runs from a `CallBrief`: mode, direction, counterpart (E.164), owner name (`assistant.owner_name`), facts pack (`calls.facts`), and for outbound modes the briefed call, the approved message, or the task goal and constraints. `CallBrief.purpose()` embeds the brief's SHA-256, so a C1 grant for that purpose binds the number and the exact brief.

| Mode | Direction | Start | Tools |
| --- | --- | --- | --- |
| `screening` | inbound (default) | "Hi, you've reached <owner or 'this number'>. I'm INARA, an AI assistant. This call is transcribed." | `record_message`, `end_call` |
| `owner_briefing` | outbound, owner's number only, no grant | "Hi <owner>, it's INARA, your AI assistant, with a call briefing." | `verify_pin` (only with a briefing PIN: the `call_briefing_pin` secret since C3), `record_owner_decision`, `end_call` |
| `approved_callback` | outbound, one-use grant | "Hello, this is INARA, an AI assistant calling on behalf of <owner>. This call is transcribed." | `record_outcome`, `end_call` |
| `task` | outbound, one-use grant | same disclosure | `record_outcome`, `end_call` |

- `CallAgent.call(brief, grant=None)` places an outbound call and returns a handle whose `result` resolves to a `CallResult` (record id, outcome, captured fields and, after a confirmed briefing, the approved callback brief with its grant). Callbacks and task calls without a grant are refused before anything is sent; `place_call` checks the grant against the number and brief hash and consumes it. The stream finds its brief by a single-use token in the call context, so a brief runs once; an outbound stream without one is hung up before Live connects. Calls that end unanswered are recorded as `no_answer`. When to place a briefing or a callback is C3's decision.
- Briefing decisions: `record_owner_decision(confirmed=false)` returns the read-back; `confirmed=true` is refused unless the same decision was read back and the owner's words since contain an explicit yes and no negation. A confirmed callback issues one grant (10 minutes) for the caller's confirmed number. The PIN is compared in code, never placed in the instruction, logs or record (spoken digits are redacted from captions); the call details reach the model only after it matches; three failures end the call.
- Arguments are validated with pydantic; failures go back to the model as `{"is_error": true, "error", "message"}`.

### Audio and limits

Caller mu-law 8 kHz -> PCM16 16 kHz (C1) -> Live; Live PCM16 24 kHz -> `session.send` (8 kHz mu-law); `interrupted` -> `session.clear()`. Automatic voice activity detection is on; context-window compression and session resumption (GoAway and up to three reconnects) work as for desktop voice, through the shared `live_connect_config`. Caller audio is held until the disclosure has played (its mark returns, at most 12 s), so the disclosure is always heard first. `end_call` hangs up once Twilio has played the audio before a final mark (15 s cap). Limits: `calls.max_call_minutes` (default 10; a nudge one minute before, a goodbye at the limit, a hard stop 25 s later); 20 s without speech -> a polite check, 10 s more -> goodbye; a usage budget reached mid-call -> goodbye. The stream ending (caller, kill switch, shutdown) closes the Live session at once. Gaming and resident mode do not stop phone calls.

### Records, triage and notices

After every call the record is saved first (CallRecords, DPAPI, 7-day retention, at most 256 records; the oldest gives way): schema 2 with `direction`, `mode`, `counterpart` (`{"masked": "+60 12-•••• 6789", "key": per-profile HMAC}`), timestamps, `duration_seconds`, `fields` (what the tools captured), `transcript` (captions only, no audio), `outcome`, `end_reason`, `brief_hash`, `triage`, `triage_state`. Schema 1 call-lab records are read with empty structured fields. Triage then runs off the call path on the router's `fast` task (Claude Haiku 5.5, else the Gemini text model) and stores `{summary (two sentences at most), urgency, needs_owner, suggested_actions}`, or a failure code without touching the record. The owner's renderers then get `call_record_ready` with the record id only; with no renderer open, the native tray shows a generic notice ("A call record is ready").

Usage: Live turns are metered per turn (`call_live`), triage as `call_triage`, and Twilio minutes as list-price estimates (`call_twilio`: US$0.0555/min local and inbound, US$0.08/min to +60 1x mobiles, billed per started minute; `llm/pricing.py`).

Settings added to `calls.*`: `facts` (free text, at most 1,000 characters, default empty), `briefing_pin` (4-8 digits, or empty for none; moved to the `call_briefing_pin` secret in C3), `max_call_minutes` (2-30, default 10). There is no settings UI for them yet.

### Not verified offline

- Gemini Live's handling of the kickoff text (`send_realtime_input(text=...)`) and whether `gemini-3.8-live` speaks the opening line verbatim, in English, before anything else.
- Voice activity detection and barge-in on 8 kHz phone audio upsampled to 16 kHz, including the line echo of INARA's own voice.
- Twilio playing marks in order and the `clear` behaviour mid-goodbye; end-to-end latency.
- Caption quality for Malaysian English and Malay, and digit-by-digit callback numbers.
- Tray notices on the native host, and Electron (legacy host) shows none for calls.

## C3 orchestration

Built 4 November 2026 (C3a, backend) in `backend/telephony/orchestrator.py` (CallOrchestrator) and `backend/transport/telephony.py` (CallsTransport); covered by `tests/test_call_orchestration.py` (no network: Twilio is an httpx mock and call results are simulated). Calls stay off by default; nothing is placed unless `calls.enabled` is true. The Calls view itself is C3b.

### Rules

- **Owner briefing policy.** When `call_record_ready` fires for an inbound screening record (after triage), INARA phones the owner with `CallAgent.call(owner_briefing_brief(record, owner_number=...))` and no grant, only if all of these hold:
  - `calls.brief_by_phone` allows it: `off` never; `urgent` (default) when triage urgency is `urgent`; `needs_owner` when triage says `urgent` or `needs_owner`. A record without a finished triage is never briefed.
  - The owner is away from the PC: no owner renderer connected, the native window hidden, or no `presence_ping` for 5 minutes (the renderer sends it on user input, at most once a minute; a fresh core start counts as activity).
  - It is not quiet hours (`calls.quiet_hours`), unless the call is urgent.
  - The owner's number is configured, and the record has not been briefed or marked done already (a record is briefed at most once).

  Otherwise the owner gets only C2's desktop notice. The briefing state (`calling`, `completed`, `no_answer` or `failed`, with the decision) is kept on the original record, and both records are linked through `related_ids`.
- **Voice-confirmed callbacks.** A briefing that ends with a confirmed callback returns C2's approved brief and its one-use grant (10 minutes); the callback is placed at once with `CallAgent.call(brief, grant)`. If quiet hours, the daily cap or the per-number cooldown refuse it, the grant is revoked, the original record gets `callback` state `blocked` with the reason (`quiet_hours`, `daily_cap`, `cooldown`), and the owner is notified (`call_record_ready` to the renderers, else a generic tray notice). Nothing is retried automatically; the owner retries from the Calls view, which re-approves and issues a fresh grant. A callback that fails or is not answered is marked the same way (`failed` / `no_answer`) and notified.
- **Desktop-approved callbacks.** "Approve call" (`calls_callback_approve`) from the authenticated owner renderer is the approval. The core checks `calls.enabled`, the record's callback number, that INARA is not already on a call or calling about this record, readiness and the third-party limits; then it issues one grant through `TelephonyService.grants` for exactly that E.164 number and the `approved_callback` brief's hash, and places the call immediately (`place_call` checks the limits again and consumes the grant).
- **Budget exhausted on an inbound call.** When the usage budget would refuse a new provider step (daily or monthly limit, or receipt capacity; `UsageService.admission_blocked`, read-only), the inbound webhook answers with the voicemail TwiML (as with `calls.when_disabled="voicemail"`) instead of connecting a stream that would hang up silently, and stores a minimal record: `state` `missed`, `outcome` `{"status": "missed", "reason": "budget"}`, masked counterpart, no transcript, triage `skipped`. The owner gets `call_record_ready`, and the record counts as `needs_you` (in `calls_list` and `needs_you_count`) until it is marked done.
- **Briefing PIN.** The optional PIN is a secret, `call_briefing_pin` (4-8 digits, no online check, developer override `INARA_CALL_BRIEFING_PIN`; [AI_PROVIDERS](AI_PROVIDERS.md#telephony-secrets-calls)), and the call agent reads it from the encrypted store. At startup a legacy `calls.briefing_pin` in settings.json is stored as the secret (an already stored secret wins), removed from settings, and the settings file is saved. If the store cannot be written, the setting stays and the agent still honours it until a later start migrates it. `briefing_pin` is refused by `SettingsPatch` (extra field). The PIN is never logged or returned: `calls_status.briefing_pin_set` and `secrets_status` show configured yes/no only, and its hint is always null.
- **Done.** The owner's "done" mark is stored on the record (`done`, `done_at`), not in settings.

### Settings

`calls.brief_by_phone`: `off`, `urgent` (default) or `needs_owner`, validated by `SettingsPatch.calls` and changed through the existing `update_settings` route. `calls.briefing_pin` was removed (see above).

### Owner-only RPCs (Calls view contract)

Every route needs the authenticated, unlocked owner renderer (`authentication_required` or `permission_denied` otherwise). Phone numbers only ever leave masked (`+60 19-•••• 5432`). Unknown ids return `not_found`; bad payloads return `invalid_arguments` (pydantic details are never echoed).

| Route | Request | Response |
| --- | --- | --- |
| `calls_list` | `{filter: "needs_you"\|"all"\|"done", limit?: 1-100 (default 50)}` | `{ok, calls: [{id, direction, mode, counterpart_masked, name\|null, started_at (ISO, UTC), duration_seconds, urgency\|null, needs_owner, summary\|null, status, outcome_status\|null}]}`, newest first |
| `calls_get` | `{id}` | `{ok, call: {...list fields, fields: {name, reason, urgency, callback_number_masked, message}\|null, triage: {summary, urgency, needs_owner, suggested_actions}\|null, triage_state, transcript: [{role: "caller"\|"inara"\|"owner", text}], outcome: {status, details}\|null, related_ids}}` |
| `calls_mark_done` | `{id}` | `{ok}` |
| `calls_delete` | `{id}` | `{ok}`; the record is deleted now |
| `calls_callback_draft` | `{id}` | `{ok, message}`: a blocked or failed callback's owner-approved words, else the triage's `suggested_reply` (addressed to the caller), else `""`; at most 300 characters. The triage's `suggested_actions` are instructions to the owner and are never used as the draft |
| `calls_callback_approve` | `{id, message (1-500)}` | `{ok, call_id}` or `{ok: false, code: "calls_disabled"\|"not_ready"\|"no_callback_number"\|"quiet_hours"\|"daily_cap"\|"cooldown"\|"busy", message}` |
| `presence_ping` | `{}` | `{ok}` |
| `calls_status` | `{}` | C1's status plus `answering` (= `calls.enabled`), `needs_you_count`, `active_call` (`{id, mode, direction, state}` or null), `briefing_pin_set` and `inara_number` (INARA's Twilio number in E.164, or null when not set; owner-only, for the carrier forwarding codes) |

`status` is decided per record, in this order: `done` (marked done); `in_progress` (a briefing or callback is being placed or is running, or triage is pending); `callback_blocked`; `failed` (the callback failed or was not answered); `done` (the briefing decision was "ignore", or the callback completed); `needs_you` (a missed incoming call: voicemail because the budget ran out, or the agent failed); `in_progress` (triage pending); `failed` (a call INARA placed that failed); `needs_you` (triage `needs_owner` or `urgent`); otherwise `done`. The `needs_you` filter is: triage `needs_owner` or `urgent`, a missed incoming call, or a blocked, failed or unanswered callback, and not marked done. Owner briefing records never need the owner, because the owner was on the call. The `done` filter returns the records whose status is `done`. `outcome.details` is the outcome's details, the approved callback words, or, for a screening record whose callback did not go through, a short reason ("Callback not placed: it is quiet hours.").

### Triage reply suggestion

Triage (C2's `fast` task) also returns `suggested_reply`: a short, plain message for the caller (no promises of times, no commitments on the owner's behalf), or `""` when no reply makes sense. It is validated with the other fields: missing means `""`; more than 600 characters makes the whole triage invalid (`triage_invalid`); otherwise it is cleaned to one printable line and cut to 300 characters at a word boundary. It is stored with the triage and used only as the `calls_callback_draft` text; the owner edits and approves the final words.

### Events to the owner's renderers

- `call_record_ready` `{record_id}`: after every call (C2), and also when a record changes in a way the owner must see (a blocked, failed or unanswered callback).
- `call_progress` `{call_id, record_id|null, mode, direction, state, message?}`, with state `dialing`, `ringing`, `in_progress`, `completed`, `no_answer` or `failed`. `message` is present only for `failed` and `no_answer`: plain text of at most 200 characters, never provider internals ("No one answered.", "The line was busy.", "The call was cancelled before anyone answered.", "The call could not be connected."). Outbound calls follow Twilio's status callbacks and the Media Stream opening and closing; `call_id` is C1's call id (the one `calls_callback_approve` returns), and `record_id` is the record a briefing or callback is about (null otherwise). Inbound calls report `in_progress` when the stream opens and `completed` when it closes, with a random `call_id` (never the CallSid) and `record_id` null; the new record arrives with `call_record_ready`. States never go backwards, and a call's last event is a terminal state. Sent only while the owner is authenticated.

Internal: the gateway service emits `telephony.session` on the event bus (never to a renderer) when a Media Stream opens or closes.

### Not verified offline

- The presence signal on the native host (`state.visible`) and the renderer's `presence_ping` cadence (sent by C3b).
- Twilio's status callback order for a callback placed right after a briefing. A briefing and its callback never overlap: the callback is placed after the briefing call has ended.

## Sources

- Twilio Malaysia voice guidelines: https://www.twilio.com/en-us/guidelines/my/voice
- Twilio Malaysia regulatory requirements: https://www.twilio.com/en-us/guidelines/my/regulatory
- Twilio Malaysia voice pricing: https://www.twilio.com/en-us/voice/pricing/my
- Meta WhatsApp Cloud API Calling: https://developers.facebook.com/docs/whatsapp/cloud-api/calling
- Google Gemini Live API: https://ai.google.dev/gemini-api/docs/live
