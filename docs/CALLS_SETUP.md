# Setting up JARVIS's phone answering (Malaysia)

This guide is for the owner. It walks you through letting JARVIS answer the calls you miss on your own SIM, take messages, and phone you with a briefing when something is urgent. Each step says what you are doing and why. Words that may be new get a one-line explanation the first time they appear.

For how it works inside, see [Call routing](CALL_ROUTING.md).

## 1. What you'll set up and what it costs

You will set up three things:

- **A Twilio number.** Twilio is a phone company for software. You rent a Malaysian local number from it, and JARVIS answers the calls that reach that number.
- **A Cloudflare tunnel.** This is a secure link from the internet to your PC. Twilio uses it to reach JARVIS's phone gateway (the small part of JARVIS that talks to Twilio, on port 8790 of your PC) and nothing else.
- **Call forwarding on your SIM.** When you miss a call, your carrier passes it on to the Twilio number.

Rough costs. These are Twilio's prices for Malaysia, listed as current in August 2026. Check [Twilio's pricing page](https://www.twilio.com/en-us/voice/pricing/my) before you buy.

| Item | Approximate cost |
|---|---|
| Malaysian local number | US$4.00 a month |
| Calls reaching JARVIS's number (inbound) | about US$0.0318 a minute |
| JARVIS calling a Malaysian landline | about US$0.0555 a minute |
| JARVIS calling a Malaysian mobile (your briefings, approved callbacks) | about US$0.08 a minute |
| Your carrier forwarding a missed call to the Twilio number | billed by your carrier, normally as a local call |
| Gemini Live (the voice that speaks on calls) | charged per minute of audio by Google; see your Google AI pricing |
| Claude triage (sorting each call after it ends) | a few US cents a call |
| Cloudflare tunnel | free |

JARVIS's Usage view shows estimates for these. **Calls stay off until you turn them on**, so nothing is charged by JARVIS until then (Twilio still charges the monthly number fee).

## 2. Twilio

1. Create an account at [twilio.com](https://www.twilio.com/try-twilio). Add some credit; trial accounts can only call verified numbers and play a trial message.
2. Buy a number: Console → **Phone Numbers → Manage → Buy a number**. Choose country **Malaysia**, type **Local**, with **Voice** capability.
3. Twilio requires a **regulatory bundle** for Malaysian numbers. That is a small set of documents proving who you are: your ID (MyKad or passport) and proof of a local Malaysian address, such as a utility bill. A PO box is not accepted. Twilio reviews it, and activation can take several days. Verify the current list of documents on [Twilio's regulatory guidelines for Malaysia](https://www.twilio.com/en-us/guidelines/regulatory) when you start.
4. Note the number in +60 format. This is your **JARVIS number**.
5. Caller ID: Twilio does not allow Malaysian verified caller IDs on calls to Malaysia. So when JARVIS phones you or someone else, the call shows the JARVIS number, not your SIM's number.
6. Find your **Account SID** and **Auth Token**: Console home → **Account info**. The Account SID starts with `AC`.

The Auth Token is like a password for your Twilio account. JARVIS uses it to place calls and to check that every request reaching it really came from Twilio (Twilio signs each request with it). Keep it secret. If it ever leaks, create a new one in the Twilio Console and enter it again in JARVIS.

## 3. Cloudflare tunnel

The tunnel gives Twilio a secure public `https://` address that reaches only JARVIS's phone gateway on your PC. Your PC does not open any port to the internet; the tunnel connects outwards.

1. Create a free account at [cloudflare.com](https://dash.cloudflare.com/sign-up).
2. Add a domain you own (Cloudflare dashboard → **Add a site**) and switch its nameservers to Cloudflare as instructed. Cloudflare's docs say you must add a website to Cloudflare before publishing an application through a tunnel. Cloudflare's free "quick tunnels" (`trycloudflare.com`) give a random address that changes every time it starts, so Twilio's settings would break; they are not suitable here. Verify this in [Cloudflare's tunnel docs](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/).
3. Open **Networking → Tunnels → Create a tunnel** (older dashboards: **Zero Trust → Networks → Tunnels**). Give it a name such as `jarvis-calls` and select **Create Tunnel**.
4. On the install screen, copy the installation command shown for Windows and keep only the **tunnel token**: the long string after `--token`. You will paste it into JARVIS. You do not need to run the command yourself.
5. Add the public address: open the tunnel → **Routes** tab → **Add route → Published application** (older dashboards call this **Public hostname**). Subdomain `calls`, choose your domain, service URL `http://localhost:8790`. Your public address is then `https://calls.<yourdomain>`.
6. Install cloudflared on Windows, either from [Cloudflare's downloads page](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/) or in a terminal:

   ```
   winget install --id Cloudflare.cloudflared
   ```

   JARVIS starts and stops cloudflared for you while calls are on, using the token stored in JARVIS.

**Never point a tunnel at port 8000.** That is JARVIS's main backend and must stay private to your PC. Only port 8790 belongs in the tunnel.

## 4. In JARVIS

First make sure a Gemini key is saved: **Preferences → AI and assistant**. The phone voice needs it.

Then open the **Calls view → setup checklist** and enter, one at a time:

| Field | What to enter |
|---|---|
| Twilio Account SID | from step 2 |
| Twilio Auth Token | from step 2 |
| JARVIS number | your Twilio number, `+60...` |
| Your mobile number | your own SIM, `+60...` (JARVIS phones you here for briefings) |
| Tunnel token | from step 3 |

Each item is tested when you enter it and stored encrypted on your PC.

Then open **Call settings**:

- **Public address**: `https://calls.<yourdomain>`. It must match the Twilio webhook addresses in step 5 exactly, including `https://` and with no trailing slash.
- **Briefing PIN** (optional): JARVIS asks for it before telling anyone on a call about your messages.
- **Facts JARVIS may share**: what JARVIS may tell callers, for example "Hiro is usually free after 6 pm." Leave out anything private.
- **Quiet hours**: times JARVIS will not phone you.
- **Daily limit**: the most calls JARVIS may place in a day.
- **Phone briefings**: whether JARVIS phones you about urgent messages.

## 5. Point the Twilio number at JARVIS

Twilio Console → **Phone Numbers → Manage → Active numbers** → your number → **Voice configuration**:

1. **A call comes in**: **Webhook**, `https://calls.<yourdomain>/telephony/voice/inbound`, **HTTP POST**. (A webhook is an address Twilio calls to ask what to do.)
2. **Primary handler fails**: a voicemail for when your PC or the tunnel is off. Create a TwiML Bin first (Console → **TwiML Bins → Create**; TwiML is Twilio's instruction format) with:

   ```xml
   <Response><Say>JARVIS is offline right now. Please leave a message after the tone.</Say><Record maxLength="120" playBeep="true" transcribe="true"/></Response>
   ```

   Then choose that TwiML Bin here. These recordings stay in your Twilio account (Console → Monitor → Call recordings), not in JARVIS; delete them there when you no longer need them.
3. **Call status changes**: `https://calls.<yourdomain>/telephony/status`.
4. **Save configuration**.

You do not enter `/telephony/voice/outbound` or `/telephony/media` anywhere; JARVIS gives those to Twilio itself when it places a call.

## 6. Forward your SIM's missed calls to JARVIS

Dial these on your phone as if calling a number. Replace `<JARVIS number>` with your Twilio number, in `+60...` or local `0...` form, whichever your carrier accepts.

| Purpose | Dial |
|---|---|
| Forward when you are busy | `**67*<JARVIS number>#` |
| Forward when you don't answer after 20 seconds | `**61*<JARVIS number>**20#` (any of 5, 10, 15, 20, 25 or 30 seconds) |
| Forward when your phone is off or unreachable | `**62*<JARVIS number>#` |
| Cancel all forwarding | `##002#` |

Notes:

- Maxis, CelcomDigi, U Mobile and other Malaysian carriers support these standard GSM codes, but may bill forwarded calls. Ask your carrier.
- Some carriers block forwarding to international numbers. Your Twilio number is a Malaysian local number, so this should not apply.
- If a code is rejected, check with your carrier, or set forwarding in your phone instead (usually **Phone → Settings → Calls → Call forwarding**).
- Keep the no-answer time longer than JARVIS's own outgoing ring time (15 seconds). 20 to 30 seconds works well.

## 7. Turn calls on and test

Open the **Calls view** and switch **Answering on**. Then tick through:

- [ ] Call your SIM from another phone and don't answer. JARVIS answers, says it is an AI, and says the call is transcribed.
- [ ] Leave a message.
- [ ] The Calls view shows the call with a summary and the message.
- [ ] Leave an urgent message while the PC is idle. JARVIS phones your mobile with a briefing (and asks for your PIN if you set one).
- [ ] Approve a callback, by voice during the briefing or in the Calls view. JARVIS calls the other phone.
- [ ] During quiet hours, JARVIS takes the message but does not phone you.
- [ ] Stop the tunnel (or turn calls off) and call again. The fallback voicemail from step 5 answers.
- [ ] Reject JARVIS's briefing call. It does not call you again in a loop.

## 8. Troubleshooting

| Problem | What to check |
|---|---|
| `403` errors in JARVIS's log | Twilio's signature didn't match. The Public address in Call settings must exactly match the start of the webhook addresses in Twilio, with `https://`, same spelling, no trailing slash. Also re-check the Auth Token. |
| Nobody answers, or Twilio's fallback plays | Calls are off; the tunnel isn't running (Cloudflare Zero Trust → Tunnels shows its status); cloudflared isn't installed; the PC is asleep. |
| Forwarding code rejected | Try the other number format (`+60` or `0`), set forwarding in phone settings, or ask your carrier. |
| Can't buy or use the number | The regulatory bundle is still pending. Check its status in the Twilio Console. |
| Calls go straight to voicemail | No Gemini key. Add it in Preferences → AI and assistant. |
| Costs higher than expected | Open the Usage view; lower the daily limit or turn off phone briefings. Also check Twilio's own usage page. |

## 9. Privacy and law

- JARVIS tells every caller that it is an AI and that the call is transcribed.
- JARVIS keeps transcripts, not audio. They are encrypted on your PC and deleted after 7 days.
- Malaysia's Personal Data Protection Act 2010 applies to callers' details you keep. Keep what you need and delete the rest: **Calls view → Delete record**.
- The fallback voicemail recordings live in your Twilio account; manage them there.

## Sources

- Twilio Malaysia voice guidelines (caller ID restriction confirmed): https://www.twilio.com/en-us/guidelines/my/voice
- Twilio Malaysia voice pricing (prices confirmed, "current as of August 2026"): https://www.twilio.com/en-us/voice/pricing/my
- Twilio regulatory requirements (verify the Malaysia document list): https://www.twilio.com/en-us/guidelines/regulatory
- Twilio webhook security (request signatures): https://www.twilio.com/docs/usage/webhooks/webhooks-security
- Twilio TwiML `<Record>`: https://www.twilio.com/docs/voice/twiml/record
- Cloudflare Tunnel overview: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/
- Cloudflare: create a remote tunnel (menu path, Published application route and domain requirement confirmed): https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/
- cloudflared downloads: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/
- GSM call forwarding codes (3GPP TS 22.030 MMI codes; verify with your carrier): https://en.wikipedia.org/wiki/Call_forwarding#Keypad_codes
