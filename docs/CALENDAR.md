# Google Calendar

JARVIS can read your Google Calendar, tell callers when you're free, and add events with your
approval. It uses only your **primary** calendar, in Malaysian time (Asia/Kuala_Lumpur).

You sign in with Google in your own browser. Google gives JARVIS access to your calendar
events only (the `calendar.events` permission), plus your email address so the Connections
card can show which account is connected.

## One-time setup

Google needs an OAuth client from your own Google Cloud project. This takes about ten
minutes, once. Everything here is free for personal use.

1. **Create a Google Cloud project.** Open the [Google Cloud Console](https://console.cloud.google.com/),
   choose the project picker at the top, then **New project**. Any name works, for example
   "JARVIS".
2. **Enable the Google Calendar API.** With the new project selected, go to
   **APIs & Services > Library**, search for "Google Calendar API", and press **Enable**.
3. **Set up the OAuth consent screen.** Go to **APIs & Services > OAuth consent screen**
   (newer consoles call this **Google Auth Platform**). Choose:
   - User type (Audience): **External**.
   - App name: "JARVIS", with your own email as the support and developer contact.
   - Publishing status: leave it in **Testing**.
   - Test users: **add your own Google account**. Only test users can sign in while the
     app is in Testing.
4. **Create an OAuth client of type "Desktop app".** Go to **APIs & Services > Credentials**
   (or **Google Auth Platform > Clients**), press **Create credentials > OAuth client ID**,
   and choose the application type **Desktop app**. Google then shows a **Client ID**
   (ending in `.apps.googleusercontent.com`) and a **Client secret** (starting with
   `GOCSPX-`).
5. **Paste the Client ID and Client secret into JARVIS.** Open **Connections** in JARVIS.
   On the Google Calendar card, under **One-time setup**, paste both values and press
   **Save**. They are stored encrypted on this PC.
6. **Connect.** Press **Connect Google Calendar**. Your browser opens Google's sign-in page.
   Choose your account and allow calendar access. When the page says "You can close this
   tab and return to JARVIS.", you're done: the card shows **Connected as** your email.

The card has the same six steps under **How to get these**, and a button that opens the
Google Cloud Console's Credentials page.

### If something goes wrong

- **"Google sign-in was cancelled"**: you pressed Cancel or Deny on Google's page. Press
  Connect again.
- **"Google sign-in timed out"**: JARVIS waits five minutes for the sign-in to finish.
  Press Connect again.
- **"Google didn't accept the Client ID and Client secret"**: check that both came from the
  same OAuth client and that its type is **Desktop app**.
- **"The Google Calendar API isn't enabled"**: repeat step 2, wait a minute, and connect
  again.
- **"Google didn't grant access to your calendar"**: on Google's page, make sure the
  calendar permission is ticked.
- **"Access blocked" or "has not completed the Google verification process"** on Google's
  page: your account isn't a test user yet. Repeat the test-user part of step 3.
- **"Couldn't make a secure connection to Google"**: an antivirus or proxy is inspecting
  HTTPS. JARVIS trusts the Windows certificate store, so this usually means the antivirus
  certificate isn't installed there.

While the app stays in Testing, Google may ask you to sign in again about once a week. If
the card says "Google Calendar access has expired or was removed", press Connect again.

## The switches

All three are on by default and only act while the calendar is connected.

- **Read my events**: JARVIS reads your events for the morning briefing and when you ask
  what's on ("What's on tomorrow?").
- **Tell callers when I'm free**: when JARVIS answers a call for you, it may say when you're
  busy or free. Callers hear **busy times only**: never an event's title, place, guests or
  any other detail. Events marked as free in Google Calendar, and cancelled events, don't
  count as busy.
- **Add events**: JARVIS can add an event when you ask ("Book lunch with Aisyah at one"), or
  for a booking it confirmed for you. It **always asks first**: an approval card shows
  exactly what will be added, for example "Add “Lunch with Aisyah” to your calendar,
  Monday 9 November 13:00 to 14:00?", and nothing is added until you press **Add**.

## Privacy

What JARVIS stores, all on this PC:

- **Client ID and Client secret**: in JARVIS's encrypted key store (Windows DPAPI, bound to
  your Windows account), like your other API keys.
- **Google's refresh token** (the long-lived access Google grants after sign-in): in the
  same encrypted store. It is internal: it is never shown in Preferences, never listed by
  `scripts/jarvis-secrets.py`, and can't be read or changed from the app.
- **Your email address**: in JARVIS's encrypted profile database, to show "Connected as".
- **The short-lived access token**: in memory only, never written to disk.

JARVIS never logs tokens, sign-in codes, the client secret, your email or event text.
Events are read from Google when needed and aren't saved by the calendar service.

**Disconnect** asks Google to revoke JARVIS's access and deletes the refresh token and the
email from this PC. If Google can't be reached, JARVIS still deletes them and tells you to
remove access yourself at [myaccount.google.com/permissions](https://myaccount.google.com/permissions).

Sign-in runs only on this PC: JARVIS listens for Google's reply on a random local port of
`127.0.0.1` for one sign-in, for up to five minutes, then stops listening. The sign-in uses
PKCE and a random state value, so a stray or forged reply is ignored.

## For developers

- Service: `backend/services/calendar.py` (status, tokens, `events`, `busy`, `add_event`,
  and `today_events()` / `free_busy()` for the morning briefing and call screening).
- Sign-in: `backend/services/calendar_oauth.py`. Routes: `backend/services/calendar_transport.py`
  (`calendar_status`, `calendar_connect`, `calendar_cancel`, `calendar_disconnect`,
  `calendar_settings`; the core pushes `calendar_status` to the owner's renderers).
- Brain tools: `backend/services/calendar_tools.py` (`calendar_events`, permission
  `calendar_read`, never asks by default; `calendar_add_event`, permission `calendar_write`,
  always asks).
- Settings: `calendar.read_events`, `calendar.share_free_busy`, `calendar.add_events`.
- Secrets: `google_oauth_client_id`, `google_oauth_client_secret` (owner-entered; env
  overrides `JARVIS_GOOGLE_OAUTH_CLIENT_ID`, `JARVIS_GOOGLE_OAUTH_CLIENT_SECRET`) and the
  internal `google_calendar_refresh_token`.
- Busy times come from `events.list` (start and end times only), not `freeBusy.query`:
  `freeBusy.query` needs a broader permission than `calendar.events`.
