/**
 * "What JARVIS knows" (S6.4, docs/MEMORY.md): the page's pure logic. Grouping and order,
 * the local search filter, the "Learned 8 Nov · from a conversation" line, the sensitivity
 * chip and edit validation. No React, no socket: tested in tests/test_memory_facts_model.mjs.
 */

export const PAGE_TITLE = 'What JARVIS knows';
export const PAGE_DESCRIPTION = 'Things JARVIS has learned about you. Edit or delete anything; nothing here leaves this PC.';
export const PAUSED_LINE = "Paused — JARVIS won't save new facts.";
export const EMPTY_COPY = "JARVIS hasn't learned anything yet. Say 'remember that…' or just talk — it picks up lasting facts after a conversation.";
export const NO_MATCH_COPY = 'No facts match that search.';
export const DELETE_PROMPT = 'Delete this?';
export const EXPORT_FILENAME = 'jarvis-memory.json';

export const SUBJECT_LIMIT = 120;
export const TEXT_LIMIT = 1000;

/** The page's groups, in order: [kind, heading]. The core's Markdown mirror uses the same. */
export const KIND_GROUPS = [
  ['profile', 'About you'],
  ['preference', 'Preferences'],
  ['person', 'People'],
  ['place', 'Places'],
  ['routine', 'Routines'],
  ['episode', 'Moments'],
];
export const KINDS = KIND_GROUPS.map(([kind]) => kind);
/** Options for the kind select in the inline editor. */
export const KIND_OPTIONS = KIND_GROUPS.map(([id, label]) => ({ id, label }));

const ID = /^[0-9a-f-]{36}$/i;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const isObject = value => !!value && typeof value === 'object' && !Array.isArray(value);
const stamp = fact => fact.created_at || '';

/** A fact as the core sends it (facts_list / facts_update); anything else is dropped. */
export const isFact = value => isObject(value)
  && typeof value.id === 'string' && value.id.length > 0
  && KINDS.includes(value.kind)
  && typeof value.subject === 'string' && typeof value.text === 'string'
  && typeof value.pinned === 'boolean';

/** Current facts only: the RPC already leaves superseded ones out; this keeps it so. */
export const currentFacts = facts => (Array.isArray(facts) ? facts : [])
  .filter(fact => isFact(fact) && !fact.superseded_by);

/** Pinned first, then newest first (by when it was learned), then by id for a stable order. */
export const compareFacts = (a, b) => (Number(b.pinned) - Number(a.pinned))
  || stamp(b).localeCompare(stamp(a))
  || a.id.localeCompare(b.id);

/** [{ kind, heading, facts }] in the page's order; empty groups are left out. */
export function groupFacts(facts) {
  const current = currentFacts(facts);
  return KIND_GROUPS
    .map(([kind, heading]) => ({ kind, heading, facts: current.filter(fact => fact.kind === kind).sort(compareFacts) }))
    .filter(group => group.facts.length > 0);
}

const fold = value => String(value ?? '').toLocaleLowerCase().normalize('NFKC');

/** The local search: every word of the query appears in the subject or text (any case). */
export function filterFacts(facts, query) {
  const current = currentFacts(facts);
  const terms = fold(query).split(/\s+/).filter(Boolean);
  if (!terms.length) return current;
  return current.filter(fact => {
    const haystack = `${fold(fact.subject)} ${fold(fact.text)}`;
    return terms.every(term => haystack.includes(term));
  });
}

/** "8 Nov" (this year) or "8 Nov 2025", in local time; null for a missing or bad date. */
export function learnedDate(value, now = new Date()) {
  if (typeof value !== 'string' || !value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const base = `${date.getDate()} ${MONTHS[date.getMonth()]}`;
  return date.getFullYear() === now.getFullYear() ? base : `${base} ${date.getFullYear()}`;
}

/** The conversation a fact came from, when it is one the renderer can open; else null. */
export const sourceConversation = fact => (typeof fact?.source_conversation_id === 'string' && ID.test(fact.source_conversation_id)
  ? fact.source_conversation_id : null);

/**
 * The muted line under a fact: { learned: 'Learned 8 Nov', source: 'from a conversation' | null,
 * conversationId }. `source` is shown as a link to that conversation.
 */
export function learnedLine(fact, now = new Date()) {
  const date = learnedDate(fact?.created_at, now);
  const conversationId = sourceConversation(fact);
  return { learned: date ? `Learned ${date}` : 'Learned', source: conversationId ? 'from a conversation' : null, conversationId };
}

/** The same line as plain text (for labels and tests). */
export const learnedText = (fact, now = new Date()) => {
  const line = learnedLine(fact, now);
  return line.source ? `${line.learned} · ${line.source}` : line.learned;
};

/** Personal and sensitive facts carry a chip; normal ones none. */
export function sensitivityChip(fact) {
  if (fact?.sensitivity === 'sensitive') return { label: 'Sensitive', tone: 'warn' };
  if (fact?.sensitivity === 'personal') return { label: 'Personal', tone: 'idle' };
  return null;
}

/** The inline editor's starting fields. */
export const editFields = fact => ({ subject: fact?.subject ?? '', text: fact?.text ?? '', kind: KINDS.includes(fact?.kind) ? fact.kind : 'preference' });

const tidy = value => String(value ?? '').normalize('NFC').split(/\s+/).filter(Boolean).join(' ');

/**
 * Validates the inline editor (the core's rules: subject 1–120 and text 1–1000 characters
 * after collapsing spaces, a known kind). { ok, value, errors: { subject, text, kind } }.
 */
export function validateEdit(fields) {
  const subject = tidy(fields?.subject), text = tidy(fields?.text), kind = fields?.kind;
  const errors = {};
  if (!subject) errors.subject = 'Give it a short subject.';
  else if (subject.length > SUBJECT_LIMIT) errors.subject = `Keep the subject to ${SUBJECT_LIMIT} characters.`;
  if (!text) errors.text = "The fact can't be empty.";
  else if (text.length > TEXT_LIMIT) errors.text = `Keep the fact to ${TEXT_LIMIT} characters.`;
  if (!KINDS.includes(kind)) errors.kind = 'Choose a group.';
  return { ok: Object.keys(errors).length === 0, value: { subject, text, kind }, errors };
}

/** Only the fields that changed, for facts_update; {} when nothing did. */
export function editChanges(fact, value) {
  const changes = {};
  for (const key of ['subject', 'text', 'kind']) if (value[key] !== fact[key]) changes[key] = value[key];
  return changes;
}

/** The list after one fact was saved (replaced in place, or added when new). */
export const withFact = (facts, fact) => (facts.some(item => item.id === fact.id)
  ? facts.map(item => (item.id === fact.id ? fact : item)) : [fact, ...facts]);

/** The list after one fact was deleted. */
export const withoutFact = (facts, id) => facts.filter(item => item.id !== id);

/** "Remembered: <text>" for a memory_remembered event; null for a bad payload. */
export function rememberedText(payload) {
  const text = isObject(payload) && typeof payload.text === 'string' ? payload.text.trim() : '';
  return text ? `Remembered: ${text}` : null;
}

/** How long the "Remembered" notice stays (ms). */
export const REMEMBERED_MS = 5000;

/** Owner-facing failure text: the core's own message for its memory codes, else a plain retry line. */
export function memoryFailureMessage(error) {
  const code = error?.code;
  if (code === 'offline' || code === 'disconnected') return 'JARVIS core is offline. Reconnect, then try again.';
  if (code === 'timeout') return 'The core did not answer. Try again.';
  if (['memory_secret', 'memory_not_found', 'memory_unavailable', 'memory_paused', 'memory_full'].includes(code)
    && typeof error?.message === 'string' && error.message) return error.message;
  if (code === 'invalid_arguments') return "That change isn't valid. Check the subject and the fact.";
  return 'Memory could not be read or saved. Try again.';
}

/** Group sizes for the screen reader summary: "12 facts" / "1 fact". */
export const factCount = count => `${count} ${count === 1 ? 'fact' : 'facts'}`;
