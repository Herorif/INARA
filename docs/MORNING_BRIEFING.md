# Morning briefing (P2)

Owner-approved design (P2, 8 Nov 2026). Once a day, the first time the owner is at the PC
in the morning, JARVIS says good morning, sums up the day in two to four sentences and
shows a card at the top of the conversation.

## When it plays

- Once a local day (Asia/Kuala_Lumpur), the first time the owner is at the PC between
  `briefing.window_start` and `briefing.window_end` (06:00 to 11:00 by default).
- Presence is any of: a renderer `presence_ping` (input or window focus, at most once a
  minute); an authenticated owner renderer connecting or unlocking (the core's `hydrate`);
  a tray or "Hey Jarvis" voice session starting.
- While a voice session runs, the briefing waits until it ends. With face lock on, it waits
  until JARVIS is unlocked. A briefing held back like this still plays after the window
  closes, but not after 12:00.
- In gaming mode: the card only, with no speech and no phone call.
- The day's state (the date, when the owner was first at the PC, when the card was shown,
  the card, dismissal and the phone outcome) is kept in the protected profile database
  (kind `briefing`), so a restart does not play it twice.

## What it says

`backend/services/briefing.py` is the composer: pure, deterministic templates, no model
call. Inputs are today's calendar events (only while connected and `calendar.read_events`
is on), today's due reminders (and pending ones overdue from an earlier day), incoming calls
"overnight" (since the later of the last briefing and 18:00 the previous day) and finished
CAD and image jobs of the current project. Print jobs are left out: a print is recorded when
it starts, with no finish time.

- Opening by `assistant.address`: "Good morning, sir." / "Good morning, ma'am." /
  "Good morning, <name>." (when a name is set) / "Good morning."
- Calendar: "On the calendar today: <title> at <time>." / "On the calendar today: <a> at
  <t1>, and <b> at <t2>." / "On the calendar today: <a> at <t1>, and <n> more." / "Your
  calendar's clear today." (not connected: left out). Titles are the owner's own words, so
  they're listed rather than fitted into a sentence. Whole hours are words ("at ten"), other
  times digits ("at 9:30"); an all-day event is "<title>, all day".
- Calls: the first VIP, "<Name> called last night: <summary>.", then "<n> other calls came in;
  the details are on screen." With no VIP: "<n> calls came in overnight; the details are on
  screen." Spam is never spoken.
- Reminders: "One reminder: <text>." / "<n> reminders today: <first>, and <second>."
- Jobs: "<job name> finished overnight." / "<n> jobs finished overnight."
- At most four sentences: anything past the third ends with "The rest is on screen."
- Nothing at all: "Good morning, sir. Nothing on the calendar and nothing new overnight."
  (with the calendar connected), or "Good morning, sir. Nothing new overnight." (without it).

The card is `{date_label, sections: [{id: today|reminders|calls|jobs, items: [{time: "HH:MM"
| "—", text, detail?, tone?: accent|muted, action?}]}]}`. VIP calls come first as "<name> ·
VIP" with the summary and `{kind: "call", record_id}`; then known and unknown callers; spam
and blocked calls are summed into one muted line ("2 calls ended as spam"). Jobs read "<name>
built · revision <id>" (images: "rendered") with `{kind: "studio", request_id, studio}`.
Sections with nothing to show are left out; with the calendar connected and clear, Today
shows "Nothing on the calendar today".

## Delivery

`backend/services/briefing_service.py` (`MorningBriefing`, owned by application.py).

- **Card.** `briefing` (`{briefing: {date, card, expires_at} | null}`) to the owner's
  authenticated renderers when it is shown, played again, dismissed or expires, and to a
  renderer that connects or unlocks. It stays until dismissed or 12:00 local; a card first
  shown after noon (from "Play today's briefing") stays until midnight.
- **Speech**, when `briefing.speak` is on and voice is available (a Gemini key, no voice
  session, not gaming, unlocked): a tray voice session with source `briefing`
  (`VoiceService.start_briefing`). Once Live connects it gets one text turn
  (`send_realtime_input(text=...)`, the same call the phone agent uses for its opening line)
  asking it to say the briefing exactly, in its own voice, adding nothing; the briefing is
  quoted as data. The session then listens like any hands-free session and ends on the usual
  silence or Stop talking. The voice stage shows "SPEAKING · MORNING BRIEFING"; the overlay
  and voice stage rules are unchanged. If Live fails before JARVIS speaks, the session ends
  quietly (`briefing_unavailable`) and the card is the briefing. The words JARVIS spoke join
  the conversation as a JARVIS turn.
- **Phone**, when `briefing.phone` is on: from `briefing.phone_time` for 30 minutes, if the
  owner hasn't been at the PC yet today, is away (`Presence.away()`), not gaming, and calls
  are enabled and set up (owner number, public address, call agent ready, no call in
  progress), JARVIS phones the owner (mode `morning_briefing`, no grant, the owner-briefing
  PIN rules) and reads the briefing. A call the owner heard (completed, PIN verified when one
  is set) marks the day as briefed by phone: the PC later shows the card without speaking it.
  An unanswered or refused call is not retried; the PC then speaks it as usual.
- Never logged: event titles, reminder text, call summaries, names or the spoken text.

## Routes

Owner-only (authenticated, unlocked owner renderer), `EmptyRequest`:

| Route | Answer |
| --- | --- |
| `briefing_get` | `{ok, briefing}`: today's card or null |
| `briefing_dismiss` | `{ok}`; `briefing {briefing: null}` to the owner's renderers |
| `briefing_play` | `{ok, briefing, spoken, reason}`: composed now (also outside the window), shown and spoken; `reason` is `gaming_mode`, `voice_busy`, `provider_not_configured` or `voice_unavailable` when not spoken |

## Settings

`briefing.enabled` (true), `briefing.window_start` ("06:00"), `briefing.window_end` ("11:00"),
`briefing.speak` (true), `briefing.phone` (false), `briefing.phone_time` ("07:30"). Times are
HH:MM; the window must start before it ends (checked on the merged value, so one end can
change alone). Preferences > Assistant > Morning briefing has the three switches, the window
times, the phone time (with the phone switch on) and "Play today's briefing".

## Free/busy for callers

With `calendar.share_free_busy` on and the calendar connected, call screening
(`telephony/briefs.py` `screening_brief`) adds an owner-approved availability line for the
rest of today, times only, for example "Owner availability today (times only, never details):
busy 10:00–11:00 and 15:00–16:00; free after 16:00." The instruction lets JARVIS tell a caller
roughly when the owner is likely to be free, never what the events are. Today's busy times
are cached for 10 minutes (`CalendarService.availability`); a failed read adds nothing, and a
blocked caller never gets it.

## Not verified offline

- Gemini Live speaking the briefing verbatim from the text turn, in the configured voice.
- The `morning_briefing` call on a real phone.
