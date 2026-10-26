# Call routing

Owner decision, 25 October 2026. Status: design only; nothing is built or verified. Gate: `sim-call-routing` in [RELEASE_GATES.json](RELEASE_GATES.json).

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
2. Store the Twilio Account SID, API key/secret and number in INARA's encrypted key store.
3. Create a Cloudflare named tunnel and store its token.
4. Dial the carrier forwarding codes on the phone.
5. Make a test call.

## Build plan

- **C1 Telephony gateway:** separate listener for `/telephony/*`, signature validation, TwiML, Media Stream WebSocket, loop guard, tunnel.
- **C2 Call agent:** mu-law/PCM bridge to Gemini Live, disclosure, screening script, tools for structured outcomes.
- **C3 Approvals, orchestration and Calls view:** triage, owner briefings, one-use grants, limits, kill switch, transcript store.
- **C4 Reservation flow:** call briefs, grant binding, bounded task calls, reminders and reports.
- **C5 Setup guide:** Twilio, regulatory bundle, key store, tunnel, forwarding codes, test call.

## Sources

- Twilio Malaysia voice guidelines: https://www.twilio.com/en-us/guidelines/my/voice
- Twilio Malaysia regulatory requirements: https://www.twilio.com/en-us/guidelines/my/regulatory
- Twilio Malaysia voice pricing: https://www.twilio.com/en-us/voice/pricing/my
- Meta WhatsApp Cloud API Calling: https://developers.facebook.com/docs/whatsapp/cloud-api/calling
- Google Gemini Live API: https://ai.google.dev/gemini-api/docs/live
