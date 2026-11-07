// Pure mappings for the Calls view's People tab (P1): groups and their copy, number
// normalisation (the core's telephony.numbers.normalize rule), display and validation.
// Names, notes and numbers stay in the renderer and the core; nothing here logs them.

export const PEOPLE_LIMIT = 500;
export const NUMBERS_LIMIT = 5;
export const NAME_LIMIT = 60;
export const NOTE_LIMIT = 300;
export const NOTE_LABEL = 'Who they are to you (JARVIS may use this)';

export const GROUP_OPTIONS = [
  { id: 'vip', label: 'VIP' },
  { id: 'known', label: 'Known' },
  { id: 'blocked', label: 'Blocked' },
];

/** What happens when someone in this group calls and the owner doesn't pick up. */
export const GROUP_COPY = {
  vip: "JARVIS greets them by name, takes the message, alerts you on the PC at once, and phones you with it, even if it isn't urgent. Quiet hours still hold unless they say it's urgent.",
  known: "JARVIS greets them by name and takes a message. It phones you only if it's urgent, as for anyone else.",
  blocked: "JARVIS says you aren't taking calls and ends the call politely. No message, no alert. The call still shows under Spam.",
};

/** Group chip: VIP in accent, Known in text-2 (idle), Blocked in danger. */
export function groupChip(group) {
  if (group === 'vip') return { tone: 'accent', label: 'VIP' };
  if (group === 'known') return { tone: 'idle', label: 'KNOWN' };
  if (group === 'blocked') return { tone: 'danger', label: 'BLOCKED' };
  return null;
}

export const groupCopy = group => GROUP_COPY[group] || GROUP_COPY.known;

const E164 = /^\+[1-9][0-9]{6,14}$/;
const SEPARATORS = /[\s\-().]/g;
// Twilio's withheld caller IDs (keypad spellings), as telephony/numbers.py.
const WITHHELD = new Set(['+266696687', '+7378742833', '+2562533', '+8656696', '+86282452253']);

/**
 * E.164 for a number the owner typed, or null (the core's telephony/contacts.py owner_number).
 * Malaysian local trunk format, one leading "0" (not "00"), becomes +60 without the 0:
 * "012-345 6789" -> "+60123456789". Spaces, dashes, dots and brackets are ignored.
 */
export function normalizeNumber(raw) {
  if (typeof raw !== 'string') return null;
  let value = raw.trim().replace(SEPARATORS, '');
  if (value.startsWith('0') && !value.startsWith('00')) value = `+60${value.slice(1)}`;
  return E164.test(value) && !WITHHELD.has(value) ? value : null;
}

/** `+60 12-345 6789` for a Malaysian number, other numbers as E.164 (the core's display form). */
export function formatNumber(number) {
  if (typeof number !== 'string' || !E164.test(number)) return typeof number === 'string' ? number : '';
  const digits = number.slice(1);
  if (digits.startsWith('60') && digits.length >= 9) {
    const national = digits.slice(2);
    const prefix = '18'.includes(national[0]) ? national.slice(0, 2) : national.slice(0, 1);
    const rest = national.slice(prefix.length);
    return `+60 ${prefix}-${rest.slice(0, -4)} ${rest.slice(-4)}`;
  }
  return number;
}

// eslint-disable-next-line no-control-regex
const LINE_CONTROL = /[\u0000-\u001f\u007f]/g;
// eslint-disable-next-line no-control-regex
const NOTE_CONTROL = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g;

/** One printable line: control characters and runs of spaces become one space, trimmed. */
export const cleanName = raw => String(raw ?? '').replace(LINE_CONTROL, ' ').split(/\s+/).filter(Boolean).join(' ');

/** The note keeps line breaks; other control characters are removed. */
export const cleanNote = raw => String(raw ?? '').replace(NOTE_CONTROL, '').replace(/\r\n?/g, '\n');

/** A name that is only a phone number (a blocked caller added from a call, for example). */
export const isBareNumber = name => typeof name === 'string' && /^[+\d][\d\s\-().]*$/.test(name.trim()) && /\d/.test(name);

/** 28 px avatar text: the name's initial, or "#" for a bare number. */
export function avatarText(person) {
  const name = cleanName(person?.name);
  if (!name || isBareNumber(name)) return '#';
  return Array.from(name)[0].toLocaleUpperCase();
}

/** The first name for the "When … calls" box: a bare number stays whole. */
export function firstName(name) {
  const clean = cleanName(name);
  if (!clean) return '';
  return isBareNumber(clean) ? clean : clean.split(' ')[0];
}

export const whenHeading = name => `When ${firstName(name) || 'this person'} calls and you don't pick up`;

export const peopleCount = count => `${count} ${count === 1 ? 'person' : 'people'}`;

export const NUMBER_ERROR = 'Enter a phone number, like 012-345 6789 or +60 12-345 6789.';

/**
 * Validate an editor draft against the saved people.
 * Returns { ok, errors: { name, numbers: [per-number message | ''], list }, value } where `value`
 * is what contacts_save takes ({ id, name, numbers (E.164), group, note }).
 */
export function validatePerson(draft, people = []) {
  const errors = { name: '', numbers: [], list: '', note: '' };
  const name = cleanName(draft?.name);
  if (!name) errors.name = 'Enter a name.';
  else if (name.length > NAME_LIMIT) errors.name = `Use at most ${NAME_LIMIT} characters for the name.`;
  const raw = Array.isArray(draft?.numbers) ? draft.numbers : [];
  const typed = raw.map(value => String(value ?? '')).filter(value => value.trim());
  const owners = new Map();
  for (const person of Array.isArray(people) ? people : []) {
    if (person?.id === draft?.id) continue;
    for (const number of person?.numbers || []) owners.set(number, person);
  }
  const seen = new Set();
  const numbers = [];
  for (const value of raw) {
    const text = String(value ?? '');
    if (!text.trim()) { errors.numbers.push(''); continue; }
    const number = normalizeNumber(text);
    if (!number) { errors.numbers.push(NUMBER_ERROR); continue; }
    if (seen.has(number)) { errors.numbers.push('This number is already listed.'); continue; }
    const other = owners.get(number);
    if (other) { errors.numbers.push(`This number is already saved for ${cleanName(other.name) || 'someone else'}.`); continue; }
    seen.add(number);
    numbers.push(number);
    errors.numbers.push('');
  }
  if (!typed.length) errors.list = 'Add at least one phone number.';
  else if (typed.length > NUMBERS_LIMIT) errors.list = `A person can have at most ${NUMBERS_LIMIT} numbers.`;
  // As the core stores it: each line's spaces collapsed, the whole note trimmed.
  const note = cleanNote(draft?.note).split('\n').map(line => line.split(/\s+/).filter(Boolean).join(' ')).join('\n').trim();
  if (note.length > NOTE_LIMIT) errors.note = `Use at most ${NOTE_LIMIT} characters.`;
  const group = GROUP_OPTIONS.some(option => option.id === draft?.group) ? draft.group : 'known';
  const ok = !errors.name && !errors.list && !errors.note && errors.numbers.every(message => !message);
  return { ok, errors, value: { id: draft?.id ?? null, name, numbers, group, note } };
}

/** True when a validated value differs from what is saved (null: nothing saved yet). */
export function personChanged(value, saved) {
  if (!saved) return true;
  return value.name !== saved.name || value.group !== saved.group || value.note !== (saved.note || '')
    || value.numbers.length !== saved.numbers.length || value.numbers.some((number, index) => number !== saved.numbers[index]);
}

/** contacts_* failure code -> the editor field its message belongs to. */
export function errorField(code) {
  if (code === 'invalid_name') return 'name';
  if (code === 'invalid_number' || code === 'duplicate_number' || code === 'too_many_numbers') return 'list';
  if (code === 'invalid_note') return 'note';
  return 'form';
}

/** A fresh editor draft for "Add person". */
export const emptyPerson = () => ({ id: null, name: '', numbers: [''], group: 'known', note: '' });

/** Editor fields for a saved person or a draft from a call (numbers shown in display form). */
export const editorFields = person => ({
  id: person?.id ?? null,
  name: person?.name ?? '',
  numbers: person?.numbers?.length ? person.numbers.map(formatNumber) : [''],
  group: GROUP_OPTIONS.some(option => option.id === person?.group) ? person.group : 'known',
  note: person?.note ?? '',
});

/** People sorted by name, as the core lists them. */
export const sortPeople = people => [...(Array.isArray(people) ? people : [])]
  .sort((a, b) => cleanName(a.name).localeCompare(cleanName(b.name), undefined, { sensitivity: 'base' }) || String(a.id).localeCompare(String(b.id)));

/** Which call-detail people actions apply: only incoming calls with a usable number. */
export function callPeopleActions(call) {
  if (!call || call.direction !== 'inbound' || !call.can_add_person) return null;
  const group = call.contact?.group || null;
  return { vip: group !== 'vip', block: group !== 'blocked' };
}

/** contacts_* failure -> a plain sentence. */
export function peopleFailureMessage(error) {
  const code = error && typeof error === 'object' ? error.code : undefined;
  if (code === 'offline' || code === 'disconnected') return 'JARVIS core is offline. Reconnect and try again.';
  if (code === 'timeout') return 'The core did not answer in time. Try again.';
  if (code === 'invalid_response' || code === 'send_failed' || code === 'scope_closed') return 'The request did not finish. Try again.';
  if (code === 'no_number') return 'There is no number for this caller.';
  if (code === 'people_limit') return `You can save at most ${PEOPLE_LIMIT} people.`;
  const message = error && typeof error === 'object' && typeof error.message === 'string' ? error.message : '';
  return message || 'The request did not finish. Try again.';
}
