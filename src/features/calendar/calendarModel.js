// The Google Calendar card on Connections (docs/CALENDAR.md). Pure: the card renders what
// cardView returns. The core is the authority (backend/services/calendar.py): it sends
// `calendar_status` {connected, email, calendar, setup_needed, connecting, switches,
// last_error}; tokens and the client secret never reach the renderer.

export const INTRO =
  "Lets JARVIS see your day, tell callers when you're free, and add bookings with your approval. You sign in with Google in your browser; JARVIS keeps the access encrypted on this PC.";
export const WAITING = 'Waiting for Google sign-in in your browser…';
export const CONSOLE_URL = 'https://console.cloud.google.com/apis/credentials';
export const AUTH_ORIGIN = 'https://accounts.google.com';

export const SWITCHES = [
  { id: 'read_events', label: 'Read my events', detail: "For the morning briefing and when you ask what's on." },
  { id: 'share_free_busy', label: "Tell callers when I'm free", detail: 'Times only, never what the event is.' },
  { id: 'add_events', label: 'Add events', detail: 'JARVIS always asks first, including for confirmed bookings.' },
];

// The same six steps as docs/CALENDAR.md.
export const SETUP_STEPS = [
  'Create a Google Cloud project in the Google Cloud Console.',
  'Enable the Google Calendar API for that project.',
  'Set up the OAuth consent screen: External, Testing, and add yourself as a test user.',
  'Create an OAuth client of type "Desktop app".',
  'Paste its Client ID and Client secret here and save them.',
  'Press Connect Google Calendar and sign in with Google.',
];

const DEFAULT_SWITCHES = { read_events: true, share_free_busy: true, add_events: true };
const EMAIL = /^[^\s@<>"']{1,128}@[^\s@<>"']{1,128}$/;

/** A validated status, or null for anything the core would never send. */
export function normalizeStatus(raw) {
  if (!raw || typeof raw !== 'object') return null;
  const bools = ['connected', 'setup_needed', 'connecting'];
  if (!bools.every((key) => typeof raw[key] === 'boolean')) return null;
  const switches = { ...DEFAULT_SWITCHES };
  if (raw.switches && typeof raw.switches === 'object') {
    for (const key of Object.keys(DEFAULT_SWITCHES)) {
      if (typeof raw.switches[key] === 'boolean') switches[key] = raw.switches[key];
    }
  }
  const error = raw.last_error && typeof raw.last_error === 'object'
    && typeof raw.last_error.code === 'string' && typeof raw.last_error.message === 'string'
    ? { code: raw.last_error.code, message: raw.last_error.message.slice(0, 300) }
    : null;
  return {
    connected: raw.connected,
    email: raw.connected && typeof raw.email === 'string' && EMAIL.test(raw.email) ? raw.email : null,
    // JARVIS uses only the primary calendar.
    calendar: 'primary',
    setupNeeded: raw.setup_needed,
    connecting: raw.connecting && !raw.connected,
    switches,
    error,
  };
}

/** Only Google's own sign-in page is ever opened from the card's Connect button. */
export function safeAuthUrl(url) {
  if (typeof url !== 'string') return null;
  try {
    const parsed = new URL(url);
    return parsed.origin === AUTH_ORIGIN && parsed.protocol === 'https:' ? parsed.href : null;
  } catch {
    return null;
  }
}

/**
 * What the card shows. `status` is normalizeStatus output (or null while loading);
 * `ui` is the card's local state: {busy, error, waiting, online}.
 */
export function cardView(status, ui = {}) {
  const online = ui.online !== false;
  const busy = !!ui.busy;
  const localError = typeof ui.error === 'string' && ui.error ? ui.error : '';
  if (!status) {
    return {
      phase: 'loading', chip: { label: 'Not connected', tone: 'idle' }, intro: INTRO, error: localError,
      setup: false, connect: { label: 'Connect Google Calendar', disabled: true }, switches: [], account: null,
      waiting: null, disconnect: null,
    };
  }
  const connected = status.connected;
  const waiting = !connected && (status.connecting || !!ui.waiting);
  const phase = connected ? 'connected' : waiting ? 'waiting' : status.setupNeeded ? 'setup' : 'ready';
  return {
    phase,
    chip: connected ? { label: 'Connected', tone: 'ok' } : { label: 'Not connected', tone: 'idle' },
    intro: connected ? null : INTRO,
    error: localError || status.error?.message || '',
    setup: phase === 'setup',
    connect: connected || waiting ? null : {
      label: 'Connect Google Calendar', disabled: !online || busy || status.setupNeeded,
    },
    waiting: waiting ? { text: WAITING, cancel: 'Cancel', disabled: !online || busy } : null,
    account: connected
      ? `Connected as ${status.email || 'your Google account'} · ${status.calendar} calendar`
      : null,
    switches: connected
      ? SWITCHES.map((row) => ({ ...row, checked: status.switches[row.id], disabled: !online || busy }))
      : [],
    disconnect: connected ? { label: 'Disconnect', disabled: !online || busy } : null,
  };
}

/** Client ID and secret entry: both are required before Save. */
export function setupReady(clientId, clientSecret) {
  return typeof clientId === 'string' && clientId.trim().length > 0
    && typeof clientSecret === 'string' && clientSecret.trim().length > 0;
}
