# Proactive engine (S7.2)

What JARVIS tells the owner without being asked. Every signal the hub accepts
(`docs/SIGNALS.md`, bus topic `signal`) is scored, checked against the owner's settings and
delivered by presence. Nothing else speaks to the owner on its own except the active
conversation.

Code: `backend/services/proactive.py` (`ProactiveEngine`, `app.proactive`),
`backend/transport/proactive.py` (routes), `src/features/proactive/` (card, digest,
"Told you"), `src/features/settings/ProactiveSettings.jsx`. Tests: `tests/test_proactive.py`,
`tests/test_proactive_model.mjs`.

## Score

`score = urgency (0-3) × person weight × time relevance`

| Part | Value |
| --- | --- |
| Person weight | VIP 2.0 (a `call.vip` signal, or the person's group in the people list), known 1.2, anyone else 1.0 |
| Time relevance | 1.0 for the first 5 minutes (`FRESH_SECONDS`), then falling linearly to 0 at `expires_at` |

Urgency 0 is never pushed by the engine alone (it stays in the hub's pending list for the
heartbeat, below).

## Thresholds (`assistant.chattiness`)

| Chattiness | Delivered | Score floor | Spoken interruptions |
| --- | --- | --- | --- |
| `quiet` | urgency ≥ 2, or a VIP's urgency ≥ 1 | ≥ 1.0 | at most one per 30 min |
| `balanced` (default) | urgency ≥ 1 | ≥ 0.6 | at most one per 10 min |
| `chatty` | urgency ≥ 1 | > 0 (still live) | at most one per 5 min |

Urgency 3 always passes and is spoken past the rate limit. Examples: on Balanced a fresh
urgency-1 calendar notice (score 1.0) is told; held 40 minutes into a 65-minute life it falls
to 0.42 and is not. On Quiet a missed call from a VIP (1 × 2.0 = 2.0) is told; from anyone
else it is not.

## Quiet hours and gaming mode

- `assistant.quiet_hours`: `{start, end}` local Malaysian `HH:MM` (may cross midnight), or
  `null` for off. Default 22:30–07:00. Only urgency 3 breaks through; everything else waits
  for the digest.
- Gaming mode (`resources.state == "gaming"` or the resident's gaming switch): nothing is
  spoken or shown. Urgency 3 goes to the phone path; everything else waits for the digest.

## Delivery by presence

Presence is one of:

- **focused**: an owner renderer reports the workspace focused and visible
  (`proactive_focus`, sent 250 ms after a change and on reconnect; the quick assistant and
  the lock screen report false).
- **in use**: keyboard or mouse input in the last 10 minutes (`GetLastInputInfo`) and Windows
  not locked. Without an input clock (not Windows) the workspace's `presence_ping` decides.
- **away**: no input for 10 minutes, the Windows lock screen, or JARVIS face-locked.

| Presence | Delivery |
| --- | --- |
| An owner voice session runs (tray or workspace), not rate-limited | A spoken line: one Live text turn with the notice as quoted data (`notice_turn`). |
| focused | The in-app card (`proactive_card {card}`) with the `notify` cue. |
| in use | The talking overlay shows a card (8 s hold, Open JARVIS) with the `notify` cue; if the overlay is off, a voice session holds it, or it can't start, a tray balloon. |
| away | `remote_hooks` (Telegram in S8), else held for the digest. |
| urgency 3, away or gaming | The owner call (below); if it can't be placed, the digest. |
| urgency 3, at the PC | Spoken or shown at once, past the rate limit and quiet hours. |

A spoken line that the rate limit stops becomes a card. Cards and balloons are grouped:
one within 2 minutes (`GROUP_SECONDS`) of the last joins its group (the overlay shows
"2 new from JARVIS"; a balloon reads "2 updates from JARVIS"; the in-app card lists up to
three, newest first, with "+N more"). `call.vip` is not carded or ballooned a second time:
the P1 VIP call alert already shows it (recorded with channel `alert`).

### The digest

Held signals (quiet hours, gaming, away, or nothing could show them) wait, at most 50 for at
most 24 hours. Once the owner is back (not away, not gaming, outside quiet hours, a workspace
open), the engine sends `proactive_digest {digest: {items}}` and the workspace shows the
"While you were away" card, grouped by kind, with "Dismiss all"
(`proactive_digest_dismiss`). A renderer that connects or unlocks receives it again.

### The urgent owner call

Urgency 3 while away or gaming phones the owner (as VIP call briefings do today): a new owner
mode `owner_alert` (`telephony/briefs.py`, `owner_alert_brief`) that reads the one notice.
The same rules as the morning briefing call: calls enabled and set up, no live call, the
saved owner number only (CallAgent refuses any other number for an owner mode, so never a
third party), the briefing PIN when one is set, no triage. At most one per 10 minutes. Its
opening line: "Hi <name>, it's JARVIS, your AI assistant, with something urgent."

## Mutes

"Don't tell me about this again" (the in-app card, "Told you") writes a rule
`{kind, source, person_id}` to the protected profile database (kind `proactive`, at most 200).
A signal with the same kind, source and person (no person matches only no person) is dropped
silently; held digest items it covers go too. Rules are listed and removable under Activity >
Told you.

## The record

The last 100 deliveries stay in memory (`proactive_recent`), each `{id, at, channel, kind,
source, person_id, title, body, urgency, score}`, channel one of `spoken`, `card`, `overlay`,
`balloon`, `phone`, `digest`, `remote`, `alert`. Each is announced as
`proactive_delivered {id, channel}` and listed under Activity > Told you. No trace span: the
flight recorder is per brain turn.

Logs carry the kind, the urgency and the channel (`Proactive calendar.soon (urgency 1)
delivered: card`), never a title, body, name or `data` value.

## Routes

Owner-only, authenticated and unlocked renderer (`docs/ROUTE_POLICY_MATRIX.json`):
`proactive_recent {}`, `proactive_mute {kind, source, person_id?}`, `proactive_unmute {id}`,
`proactive_mutes {}`, `proactive_digest_dismiss {}`; `proactive_focus {focused}` (also while
locked, like `voice_stage`).

## Settings

Preferences > Assistant: "How chatty" (Quiet / Balanced / Chatty) and "Quiet hours" (an off
switch and two times). `assistant.chattiness` rejects null; `assistant.quiet_hours` takes
`{start, end}` with different times, or null for off.

## Heartbeat (S7.3)

A second look, every 30 minutes while the core runs, at what came in but was not told.
Code: `backend/services/heartbeat.py` (`Heartbeat`, `app.heartbeat`),
`backend/transport/heartbeat.py`, `src/features/settings/HeartbeatSettings.jsx`,
`src/features/proactive/heartbeatModel.js`. Tests: `tests/test_heartbeat.py`,
`tests/test_heartbeat_model.mjs`.

**What needs judgment.** A signal still pending in the hub (live, not acknowledged) that the
engine neither delivered nor held for the digest (the engine marks every signal it records or
holds: `engine.delivered(dedupe_key)`), that no mute covers, and that the heartbeat has not put
to its model before (each signal is judged once). Nothing needs judgment: no model call.

**When.** Skipped in gaming mode, and in quiet hours unless a waiting signal is urgency 3.
Needs an owner. One check at a time.

**The call.** One fast-route call (Claude Haiku 5.5, effort low, at most 1,024 output tokens,
20 s deadline), metered as `heartbeat`, with structured output (`output_config.format`, a JSON
schema). The system prompt is byte-stable and cached. The user message is JSON:

```json
{"now": "Sunday 2026-11-15 14:08",
 "standing_instructions": "<HEARTBEAT.md, or the default when empty>",
 "routines": ["<enabled routine names, at most 30>"],
 "signals": [{"signal": "<dedupe_key>", "kind": "calendar.soon", "title": "...",
              "body": "<at most 200 characters>", "urgency": 1, "age_minutes": 7}]}
```

At most 20 signals (newest first). The answer:
`{"actions": [{"action": "notify|speak|run_routine|none", "signal": "<dedupe_key>",
"routine"?: "<name>", "text"?: "<one sentence>"}]}`, at most 5, one per signal, only keys
from the request. With Gemini alone there is no structured output and the check is skipped.

**Applying.** Always through the engine, never around it:

| Action | Effect |
| --- | --- |
| `notify` | `consider(item, judged=True, speak=False)`: a card, overlay card or balloon; held for the digest while away, gaming or in quiet hours. |
| `speak` | `consider(item, judged=True)` with the model's sentence as the line: spoken if a voice session runs and the spoken rate limit allows, else a card like any other. |
| `run_routine` | `app.routines.fire(id, "heartbeat", item)` (the routine's approvals apply). No routines service or no such enabled routine: `notify`, with a note. |
| `none` | The signal is acknowledged (`SignalHub.ack`). |

`judged=True` skips only the score threshold; mutes, quiet hours, gaming mode, presence and
rate limits apply as for any signal. A failed call is tried once more at the next check, then
that batch is left alone.

**HEARTBEAT.md.** `<data>\HEARTBEAT.md`, beside the database (the folder the memory mirror
uses), created on first read with:

```
# Standing instructions
- Tell me about VIP calls right away.
- Batch job notices unless one failed.
- Rain alerts only on weekdays before 9 am.
```

Plain text, at most 4,000 characters (`\n` line ends; control characters rejected); empty
means the default is used. Edited in Preferences > Assistant > "Standing instructions"
(below Quiet hours), which also shows "Last check: 14:30 · told you 1 thing".

**Routes** (owner-only, authenticated and unlocked renderer): `heartbeat_get {}` →
`{ok, text, last_run, last_actions: [{action, signal, kind, outcome, note?}]}`;
`heartbeat_save {text}` → `{ok, text}`. The last check is kept in memory only.

**Logs** carry counts, kinds and codes (`heartbeat done signals=2 actions=1 invalid=0
told=1`), never a title, a body or the instructions.

## Not built yet

- Telegram (S8): `remote_hooks` is the delivery hook for away.
