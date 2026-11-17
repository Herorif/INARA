---
name: plan-my-day
description: "Plan the owner's day from their calendar, reminders and the weather: fixed events first, then tasks in the gaps, with travel and rain in mind. Use when they ask to plan today or tomorrow."
---

# Plan my day

Use this when the owner asks you to plan their day ("plan my day", "what should I do today",
"susun hari saya"), for today or a day they name.

## Gather first

1. Call `calendar_events` for the day. Fixed events are the frame of the plan.
2. Call `list_reminders` and keep the ones due that day or overdue.
3. Call `weather` for the owner's home town for that day. Note rain (in Malaysia, often
   in the afternoon), heat and anything severe.

If a tool isn't connected or fails, say which part is missing in one short line and plan
with what you have. Never invent an event or a reminder.

## Build the plan

- Keep the owner's own times exactly. Don't move or shorten an event.
- Put each reminder into a free gap of a sensible length, earliest due first.
- Leave about 15 minutes before an event in another place, more at rush hour
  (07:00-09:30 and 17:00-19:30 in Kuala Lumpur).
- Put outdoor errands before the rain when rain is likely.
- Keep a lunch break around 12:30-14:00 unless an event covers it.
- If the day is overbooked, say so plainly and name what could move.

## Say it

Lead with a one-line summary ("A busy morning and a clear afternoon."), then the plan in
time order, one short line each: `09:00 Standup (Teams)`. Keep it under about ten lines.
Mention the weather only when it changes the plan.

Finish with one offer, for example "Shall I set reminders for the errands?". Never create
reminders or events unless the owner says yes: those tools ask for approval as usual.

Reply in the language the owner used.
