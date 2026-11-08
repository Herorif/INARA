// Pure model for the morning briefing card (P2): the core's `briefing` payload validated into
// what the card shows, its labels, and what an item's link does. No DOM, no store, so node:test
// can check every rule. Event titles, reminders and call summaries are the owner's own data:
// shown, never logged.

export const HEADER_PREFIX = 'GOOD MORNING';
export const SECTION_LABELS = Object.freeze({ today: 'Today', reminders: 'Reminders', calls: 'Overnight calls', jobs: 'Finished jobs' });
export const SECTION_IDS = Object.freeze(Object.keys(SECTION_LABELS));
export const PLAY_LABEL = 'Play again';
export const DISMISS_LABEL = 'Dismiss';
export const CALL_BACK_LABEL = 'Call back';
/** A card with no sections (nothing connected and nothing new). */
export const EMPTY_TEXT = 'Nothing new overnight.';
export const NO_TIME = '—';
export const LIMITS = Object.freeze({ text: 200, detail: 400, label: 60, items: 40 });

const TONES = new Set(['accent', 'muted']);
const STUDIOS = new Set(['cad', 'image']);
const ID = /^[A-Za-z0-9_.:-]{1,128}$/;
const TIME = /^([01][0-9]|2[0-3]):[0-5][0-9]$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
// Control and bidi characters never reach the page.
// eslint-disable-next-line no-control-regex
const CONTROL = /[\u0000-\u001f\u007f-\u009f\u200b-\u200f\u2028-\u202e\u2066-\u2069]+/g;

const line = (value, limit) => {
  if (typeof value !== 'string') return '';
  const text = value.replace(CONTROL, ' ').replace(/\s+/g, ' ').trim();
  return text.length <= limit ? text : `${text.slice(0, limit - 1).trimEnd()}…`;
};

function parseAction(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  if (raw.kind === 'call' && typeof raw.record_id === 'string' && ID.test(raw.record_id)) return { kind: 'call', recordId: raw.record_id };
  if (raw.kind === 'studio' && typeof raw.request_id === 'string' && ID.test(raw.request_id) && STUDIOS.has(raw.studio)) {
    return { kind: 'studio', requestId: raw.request_id, studio: raw.studio };
  }
  return null;
}

function parseItem(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const time = raw.time === NO_TIME || (typeof raw.time === 'string' && TIME.test(raw.time)) ? raw.time : null;
  const text = line(raw.text, LIMITS.text);
  if (!time || !text) return null;
  const item = { time, text, detail: line(raw.detail, LIMITS.detail) || null, tone: TONES.has(raw.tone) ? raw.tone : null, action: parseAction(raw.action) };
  return item;
}

/**
 * The `briefing` payload's inner value ({date, card: {date_label, sections}, expires_at}) as
 * the card shows it: { date, dateLabel, sections: [{ id, label, items }], expiresAt (ms) },
 * or null for none or anything malformed. Unknown sections and malformed items are dropped.
 */
export function parseBriefing(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const { date, card, expires_at: expires } = raw;
  if (typeof date !== 'string' || !DATE.test(date) || !card || typeof card !== 'object') return null;
  const expiresAt = typeof expires === 'string' ? Date.parse(expires) : NaN;
  const dateLabel = line(card.date_label, LIMITS.label);
  if (!Number.isFinite(expiresAt) || !dateLabel || !Array.isArray(card.sections)) return null;
  const seen = new Set();
  const sections = [];
  for (const section of card.sections) {
    if (!section || typeof section !== 'object' || !SECTION_IDS.includes(section.id) || seen.has(section.id)) continue;
    const items = (Array.isArray(section.items) ? section.items : []).slice(0, LIMITS.items).map(parseItem).filter(Boolean);
    if (!items.length) continue;
    seen.add(section.id);
    sections.push({ id: section.id, label: SECTION_LABELS[section.id], items });
  }
  sections.sort((a, b) => SECTION_IDS.indexOf(a.id) - SECTION_IDS.indexOf(b.id));
  return { date, dateLabel, sections, expiresAt };
}

/** A `briefing` event ({ briefing }) -> the store value (null clears the card). */
export const receiveBriefing = payload => (payload && typeof payload === 'object' ? parseBriefing(payload.briefing) : null);

/** "GOOD MORNING · SUNDAY 8 NOVEMBER". */
export const headerText = briefing => `${HEADER_PREFIX} · ${briefing.dateLabel.toUpperCase()}`;

/** The card shows until it expires (12:00 local, or midnight for one shown after noon). */
export const briefingVisible = (briefing, now) => !!briefing && Number.isFinite(now) && now < briefing.expiresAt;

/**
 * What an item's link does: "Call back" opens Calls on that record with its callback approval
 * focused (the VIP alert's path; it never dials); a job opens its revision in the studio.
 */
export function itemLink(item) {
  const action = item?.action;
  if (action?.kind === 'call') return { kind: 'call', label: CALL_BACK_LABEL, focus: { recordId: action.recordId, approve: true } };
  if (action?.kind === 'studio') return { kind: 'studio', feature: action.studio, requestId: action.requestId, title: action.studio === 'cad' ? 'Open in 3D studio' : 'Open in Images' };
  return null;
}

/** The line under the header after "Play again", or '' when JARVIS is speaking it. */
export function playMessage(result) {
  if (result && typeof result === 'object' && result.ok === true) {
    if (result.spoken === true) return '';
    switch (result.reason) {
      case 'gaming_mode': return "Gaming mode is on, so JARVIS didn't read it out.";
      case 'voice_busy': return 'Voice is already on. Stop it to hear the briefing.';
      case 'provider_not_configured': return 'Reading it out needs a Gemini API key.';
      default: return "JARVIS couldn't read it out just now.";
    }
  }
  const message = result && typeof result === 'object' && typeof result.message === 'string' ? result.message : '';
  return message || "The briefing couldn't be played. Try again.";
}
