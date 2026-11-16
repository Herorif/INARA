// Proactive engine UI (S7.2, docs/PROACTIVE.md): pure logic for the in-app card, the "While
// you were away" digest, the Activity "Told you" tab and Preferences > Assistant's rows.
// The payload shapes are backend/services/proactive.py. Tested in tests/test_proactive_model.mjs.

export const CARD_LIMIT = 5; // cards kept in one group on screen
export const CARD_SHOWN = 3; // entries listed in the group before "+N more"
export const GROUP_MS = 120000; // a card within 2 min of the last one joins its group
export const FOCUS_REPORT_DELAY_MS = 250;

export const MUTE_LABEL = 'Don’t tell me about this again';
export const DISMISS_LABEL = 'Dismiss';
export const DISMISS_ALL_LABEL = 'Dismiss all';
export const DIGEST_TITLE = 'While you were away';
export const TOLD_EMPTY = 'Nothing yet. Whatever JARVIS tells you on its own is listed here.';
export const TOLD_NOTE = 'The last 100, kept in memory until JARVIS restarts.';
export const MUTES_HEADING = 'Muted';
export const MUTES_EMPTY = 'Nothing muted.';
export const LOAD_ERROR = "The list couldn't be loaded. Try again.";
export const MUTE_ERROR = "That couldn't be muted. Try again.";
export const UNMUTE_ERROR = "That couldn't be unmuted. Try again.";

export const CHATTY_LABEL = 'How chatty';
export const CHATTY_OPTIONS = Object.freeze([
  { id: 'quiet', label: 'Quiet' },
  { id: 'balanced', label: 'Balanced' },
  { id: 'chatty', label: 'Chatty' },
]);
const CHATTY_HELP = {
  quiet: 'Only what’s soon or urgent, and anything from a VIP. At most one spoken interruption every 30 minutes.',
  balanced: 'Anything worth a mention while it’s still fresh. At most one spoken interruption every 10 minutes.',
  chatty: 'Everything worth a mention. At most one spoken interruption every 5 minutes.',
};
export const QUIET_LABEL = 'Quiet hours';
export const QUIET_HELP = 'Only urgent things get through; the rest waits until you’re back.';
export const QUIET_OFF_HELP = 'Off: JARVIS may speak up at any hour.';
export const QUIET_DEFAULT = Object.freeze({ start: '22:30', end: '07:00' });
export const TIME_FORMAT = 'Enter the time as HH:MM.';
export const QUIET_SAME = 'Quiet hours must start and end at different times.';

const TIME = /^([01][0-9]|2[0-3]):[0-5][0-9]$/;
const ID = /^[0-9a-f]{32}$/;
export const validTime = value => typeof value === 'string' && TIME.test(value);

const KIND_LABELS = Object.freeze({
  'calendar.soon': 'Calendar',
  'weather.rain_soon': 'Weather',
  'call.missed': 'Calls',
  'call.vip': 'Calls',
  'message.received': 'Messages',
  'job.finished': 'Jobs',
  'home.state': 'Home',
  'home.alert': 'Home',
  'homelab.alert': 'Homelab',
  'system.battery': 'Battery',
  'routine.due': 'Routines',
});
const CHANNEL_LABELS = Object.freeze({
  spoken: 'Said aloud',
  card: 'Card',
  overlay: 'Overlay card',
  balloon: 'Tray notice',
  phone: 'Phone call',
  digest: 'While you were away',
  remote: 'Sent to your phone',
  alert: 'Call alert',
});

export const kindLabel = kind => KIND_LABELS[kind] || 'JARVIS';
export const channelLabel = channel => CHANNEL_LABELS[channel] || 'Told you';

const text = (value, limit) => (typeof value === 'string' ? value.trim().slice(0, limit) : '');
const idOf = value => (typeof value === 'string' && ID.test(value) ? value : null);
const optional = value => (typeof value === 'string' && value ? value : null);

/** One validated card / digest item / delivery, or null. */
export function normalizeItem(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const id = idOf(raw.id);
  const title = text(raw.title, 160);
  if (!id || !title || typeof raw.kind !== 'string' || typeof raw.source !== 'string') return null;
  const at = typeof raw.at === 'string' && !Number.isNaN(Date.parse(raw.at)) ? raw.at : null;
  const urgency = Number.isInteger(raw.urgency) && raw.urgency >= 0 && raw.urgency <= 3 ? raw.urgency : 1;
  const item = { id, kind: raw.kind, source: raw.source, person_id: optional(raw.person_id), title, body: text(raw.body, 500), urgency, at };
  if (typeof raw.channel === 'string') item.channel = raw.channel;
  if (typeof raw.reason === 'string') item.reason = raw.reason;
  return item;
}

/* --- the in-app card group ----------------------------------------------------------------- */

export const emptyCards = Object.freeze({ items: [], lastAt: null });

/**
 * A new `proactive_card` ({ card }) into the group: newest first, at most CARD_LIMIT. A card
 * more than GROUP_MS after the last one starts a fresh group. Returns { state, fresh }.
 */
export function receiveCard(state, payload, now) {
  const card = normalizeItem(payload?.card);
  if (!card) return { state, fresh: false };
  if (state.items.some(item => item.id === card.id)) return { state, fresh: false };
  const grouped = state.lastAt !== null && now - state.lastAt < GROUP_MS ? state.items : [];
  return { state: { items: [card, ...grouped].slice(0, CARD_LIMIT), lastAt: now }, fresh: true };
}

export function dismissCard(state, id) {
  const items = state.items.filter(item => item.id !== id);
  return items.length === state.items.length ? state : { ...state, items };
}

/** Drops every card the mute rule covers (kind + source + person). */
export function dropMuted(state, rule) {
  const items = state.items.filter(item => !covers(rule, item));
  return items.length === state.items.length ? state : { ...state, items };
}

/** The group as shown: the label, the listed entries and how many more. */
export function cardGroupView(state) {
  const count = state.items.length;
  if (!count) return null;
  const shown = state.items.slice(0, CARD_SHOWN);
  return {
    label: count > 1 ? `JARVIS · ${count} NEW` : `JARVIS · ${kindLabel(state.items[0].kind).toUpperCase()}`,
    entries: shown.map(item => ({ ...item, kindText: kindLabel(item.kind) })),
    more: count - shown.length,
  };
}

/* --- the digest ---------------------------------------------------------------------------- */

/** `proactive_digest` ({ digest: {items} | null }) -> { items } (newest first) or null. */
export function receiveDigest(payload) {
  const items = Array.isArray(payload?.digest?.items) ? payload.digest.items.map(normalizeItem).filter(Boolean) : [];
  return items.length ? { items } : null;
}

/** The digest grouped by kind (in order of each group's newest item). */
export function digestGroups(digest) {
  const groups = [];
  const byLabel = new Map();
  for (const item of digest?.items || []) {
    const label = kindLabel(item.kind);
    if (!byLabel.has(label)) {
      const group = { label, items: [] };
      byLabel.set(label, group);
      groups.push(group);
    }
    byLabel.get(label).items.push(item);
  }
  return groups;
}

/** "14:05" in local time, or ''. */
export function clockTime(at) {
  const value = typeof at === 'string' ? new Date(at) : null;
  if (!value || Number.isNaN(value.getTime())) return '';
  return value.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
}

/* --- mutes ----------------------------------------------------------------------------------- */

/** The proactive_mute request for one item. */
export function muteRequest(item) {
  const request = { kind: item.kind, source: item.source };
  if (item.person_id) request.person_id = item.person_id;
  return request;
}

export const covers = (rule, item) => !!rule && !!item && rule.kind === item.kind && rule.source === item.source
  && (rule.person_id || null) === (item.person_id || null);

export function normalizeMute(raw) {
  if (!raw || typeof raw !== 'object') return null;
  const id = idOf(raw.id);
  if (!id || typeof raw.kind !== 'string' || typeof raw.source !== 'string') return null;
  return { id, kind: raw.kind, source: raw.source, person_id: optional(raw.person_id), created_at: optional(raw.created_at) };
}

/** "Calendar · from calendar" (and "· one person" when the rule is for a person). */
export function muteLabel(rule) {
  return `${kindLabel(rule.kind)} · from ${rule.source}${rule.person_id ? ' · one person' : ''}`;
}

/** Rows for "Told you": newest first, with whether a mute already covers each. */
export function toldRows(deliveries, mutes) {
  return deliveries.map(item => ({
    ...item,
    time: clockTime(item.at),
    kindText: kindLabel(item.kind),
    channelText: channelLabel(item.channel),
    muted: mutes.some(rule => covers(rule, item)),
  }));
}

/* --- Preferences > Assistant ------------------------------------------------------------------ */

/** Saved `settings.assistant` -> { chattiness, quiet_hours: {start, end} | null }, with the core's defaults. */
export function proactiveChoice(assistant) {
  const value = assistant && typeof assistant === 'object' ? assistant : {};
  const chattiness = CHATTY_OPTIONS.some(option => option.id === value.chattiness) ? value.chattiness : 'balanced';
  let quiet;
  if ('quiet_hours' in value && value.quiet_hours === null) quiet = null;
  else if (value.quiet_hours && validTime(value.quiet_hours.start) && validTime(value.quiet_hours.end)
    && value.quiet_hours.start !== value.quiet_hours.end) quiet = { start: value.quiet_hours.start, end: value.quiet_hours.end };
  else quiet = { ...QUIET_DEFAULT };
  return { chattiness, quiet_hours: quiet };
}

export const chattyHelp = chattiness => CHATTY_HELP[chattiness] || CHATTY_HELP.balanced;

export function chattinessPatch(choice, next) {
  if (!CHATTY_OPTIONS.some(option => option.id === next) || next === choice.chattiness) return null;
  return { assistant: { chattiness: next } };
}

/** The off switch: off saves null; on restores the default hours. */
export function quietSwitchPatch(choice, on) {
  if (on === (choice.quiet_hours !== null)) return null;
  return { assistant: { quiet_hours: on ? { ...QUIET_DEFAULT } : null } };
}

/** { patch } for new quiet hours, { error } when invalid, or {} when unchanged. */
export function quietHoursPatch(choice, start, end) {
  if (!validTime(start) || !validTime(end)) return { error: TIME_FORMAT };
  if (start === end) return { error: QUIET_SAME };
  const saved = choice.quiet_hours;
  if (saved && saved.start === start && saved.end === end) return {};
  return { patch: { assistant: { quiet_hours: { start, end } } } };
}

/* --- presence ---------------------------------------------------------------------------------- */

/** Whether this window counts as the focused, visible workspace for the engine. */
export const workspaceFocused = ({ connected, documentVisible, focused, locked }) =>
  connected === true && documentVisible === true && focused === true && locked !== true;
