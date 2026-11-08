// Pure copy and mappings for Preferences > Assistant > Morning briefing (P2): the saved
// briefing.* values with the core's defaults, the help lines, the update_settings patches and
// the "Play today's briefing" result line.

export const HEADING = 'Morning briefing';
export const ENABLED_LABEL = 'Morning briefing';
export const SPEAK_LABEL = 'Speak it aloud';
export const SPEAK_HELP = 'Otherwise just the card.';
export const PHONE_LABEL = 'Also phone me with it';
export const PHONE_HELP = 'At a set time, when you’re away from the PC.';
export const PHONE_TIME_LABEL = 'Phone at';
export const PLAY_LABEL = 'Play today’s briefing';
export const WINDOW_ORDER = 'The morning briefing window must start before it ends.';
export const TIME_FORMAT = 'Enter the time as HH:MM.';
export const DEFAULTS = Object.freeze({ enabled: true, window_start: '06:00', window_end: '11:00', speak: true, phone: false, phone_time: '07:30' });

const TIME = /^([01][0-9]|2[0-3]):[0-5][0-9]$/;
export const validTime = value => typeof value === 'string' && TIME.test(value);
const SWITCHES = new Set(['enabled', 'speak', 'phone']);

/** Saved `settings.briefing` -> every value, with the core's defaults for missing or stale ones. */
export function briefingChoice(briefing) {
  const value = briefing && typeof briefing === 'object' ? briefing : {};
  const choice = {};
  for (const [key, fallback] of Object.entries(DEFAULTS)) {
    choice[key] = typeof fallback === 'boolean'
      ? (typeof value[key] === 'boolean' ? value[key] : fallback)
      : (validTime(value[key]) ? value[key] : fallback);
  }
  if (choice.window_start >= choice.window_end) {
    choice.window_start = DEFAULTS.window_start;
    choice.window_end = DEFAULTS.window_end;
  }
  return choice;
}

/** "The first time you’re at the PC between 06:00 and 11:00." */
export const enabledHelp = choice => `The first time you’re at the PC between ${choice.window_start} and ${choice.window_end}.`;

/** The patch for one switch, or null when nothing changes. */
export function switchPatch(choice, key, value) {
  if (!SWITCHES.has(key) || typeof value !== 'boolean' || choice[key] === value) return null;
  return { briefing: { [key]: value } };
}

/** { patch } for the briefing window, { error } when invalid, or {} when unchanged. */
export function windowPatch(choice, start, end) {
  if (!validTime(start) || !validTime(end)) return { error: TIME_FORMAT };
  if (start >= end) return { error: WINDOW_ORDER };
  const changes = {};
  if (start !== choice.window_start) changes.window_start = start;
  if (end !== choice.window_end) changes.window_end = end;
  return Object.keys(changes).length ? { patch: { briefing: changes } } : {};
}

/** { patch } for the phone time, { error } when invalid, or {} when unchanged. */
export function phoneTimePatch(choice, value) {
  if (!validTime(value)) return { error: TIME_FORMAT };
  return value === choice.phone_time ? {} : { patch: { briefing: { phone_time: value } } };
}

/** The result line after "Play today’s briefing" ({ tone, text }), from the RPC answer or error. */
export function playResult(result) {
  if (result && typeof result === 'object' && result.ok === true) {
    if (result.spoken === true) return { tone: 'ok', text: 'Playing today’s briefing.' };
    switch (result.reason) {
      case 'gaming_mode': return { tone: 'warn', text: 'The card is on the Assistant page. Gaming mode is on, so JARVIS didn’t read it out.' };
      case 'voice_busy': return { tone: 'warn', text: 'The card is on the Assistant page. Voice is already on, so JARVIS didn’t read it out.' };
      case 'provider_not_configured': return { tone: 'warn', text: 'The card is on the Assistant page. Reading it out needs a Gemini API key.' };
      default: return { tone: 'warn', text: 'The card is on the Assistant page. JARVIS couldn’t read it out just now.' };
    }
  }
  const message = result && typeof result === 'object' && typeof result.message === 'string' ? result.message : '';
  return { tone: 'danger', text: message || 'The briefing couldn’t be played. Try again.' };
}
