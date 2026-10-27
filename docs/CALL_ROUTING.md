# Call routing

Owner decision, 25 October 2026. Status: the C1 telephony gateway and the C2 call agent are built and tested offline ([Implementation status (C1)](#implementation-status-c1), [Implementation status (C2)](#implementation-status-c2)); nothing has been verified against a live Twilio number, and C3-C5 are not built. Gate: `sim-call-routing` in [RELEASE_GATES.json](RELEASE_GATES.json).

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
| `owner_briefing` | outbound, owner's number only, no grant | "Hi <owner>, it's INARA, your AI assistant, with a call briefing." | `verify_pin` (only with `calls.briefing_pin`), `record_owner_decision`, `end_call` |
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

Settings added to `calls.*`: `facts` (free text, at most 1,000 characters, default empty), `briefing_pin` (4-8 digits, or empty for none), `max_call_minutes` (2-30, default 10). There is no settings UI for them yet.

### Not verified offline

- Gemini Live's handling of the kickoff text (`send_realtime_input(text=...)`) and whether `gemini-3.8-live` speaks the opening line verbatim, in English, before anything else.
- Voice activity detection and barge-in on 8 kHz phone audio upsampled to 16 kHz, including the line echo of INARA's own voice.
- Twilio playing marks in order and the `clear` behaviour mid-goodbye; end-to-end latency.
- Caption quality for Malaysian English and Malay, and digit-by-digit callback numbers.
- Tray notices on the native host, and Electron (legacy host) shows none for calls.

## Sources

- Twilio Malaysia voice guidelines: https://www.twilio.com/en-us/guidelines/my/voice
- Twilio Malaysia regulatory requirements: https://www.twilio.com/en-us/guidelines/my/regulatory
- Twilio Malaysia voice pricing: https://www.twilio.com/en-us/voice/pricing/my
- Meta WhatsApp Cloud API Calling: https://developers.facebook.com/docs/whatsapp/cloud-api/calling
- Google Gemini Live API: https://ai.google.dev/gemini-api/docs/live
