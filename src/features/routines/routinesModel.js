/**
 * Routines (S7.4, docs/ROUTINES.md): the page's pure logic. Trigger summaries ("When you say
 * 'movie time'", "Weekdays at 07:30", "When an event starts in 10 minutes"), the last-run
 * line, the editor's fields and their validation (each step's JSON arguments are checked
 * against the tool's own schema from routines_tools), and step reordering. No React, no
 * socket: tested in tests/test_routines_model.mjs. The core checks everything again.
 */

export const PAGE_TITLE = 'Routines';
export const PAGE_DESCRIPTION = 'Steps JARVIS runs for you when you say a phrase, at a time of day, or when something happens. Steps that need your approval still ask.';
export const EMPTY_COPY = "No routines yet. Make one here, or ask JARVIS: 'when I say movie time, dim the lights'.";
export const DELETE_PROMPT = 'Delete this routine?';
export const NEVER_RUN = 'Not run yet';

export const MAX_STEPS = 12;
export const NAME_LIMIT = 60;
export const PHRASE_LIMIT = 80;
export const MAX_PHRASES = 5;
export const SAY_LIMIT = 200;
export const ARGS_CHARS = 4000;
/** The core refuses these as steps: no routine runs or saves routines. */
export const NOT_STEPS = ['routine_run', 'routine_save'];

export const TRIGGER_TYPES = [
  { id: 'phrase', label: 'When I say' },
  { id: 'schedule', label: 'At a time' },
  { id: 'signal', label: 'When something happens' },
];
export const REPEAT_OPTIONS = [
  { id: 'daily', label: 'Every day' },
  { id: 'weekdays', label: 'Weekdays' },
  { id: 'weekly', label: 'Once a week' },
];
export const DAY_OPTIONS = [
  { id: 'mon', label: 'Monday' }, { id: 'tue', label: 'Tuesday' }, { id: 'wed', label: 'Wednesday' },
  { id: 'thu', label: 'Thursday' }, { id: 'fri', label: 'Friday' }, { id: 'sat', label: 'Saturday' },
  { id: 'sun', label: 'Sunday' },
];
/** Signal kinds (backend/services/signals.py KINDS) with the core's "When ..." words. */
export const SIGNAL_OPTIONS = [
  { id: 'calendar.soon', label: 'When an event is coming up' },
  { id: 'weather.rain_soon', label: 'When rain is expected at home' },
  { id: 'call.missed', label: 'When you miss a call' },
  { id: 'call.vip', label: 'When a VIP calls' },
  { id: 'message.received', label: 'When a message arrives' },
  { id: 'job.finished', label: 'When a job finishes' },
  { id: 'home.state', label: 'When a home device changes' },
  { id: 'home.alert', label: 'When a home alert comes in' },
  { id: 'homelab.alert', label: 'When a homelab alert comes in' },
  { id: 'system.battery', label: 'When the battery runs low' },
  { id: 'routine.due', label: 'When a routine is due' },
];
/** calendar.soon fires 30 and 10 minutes before an event (data.minutes). */
export const MINUTE_OPTIONS = [
  { id: '', label: 'Either reminder' },
  { id: '30', label: '30 minutes before' },
  { id: '10', label: '10 minutes before' },
];

const TIME = /^([01]\d|2[0-3]):[0-5]\d$/;
const ID = /^[0-9a-f-]{36}$/i;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const isObject = value => !!value && typeof value === 'object' && !Array.isArray(value);
const quote = text => `‘${text}’`;
const squash = value => String(value ?? '').normalize('NFC').split(/\s+/).filter(Boolean).join(' ');
const fold = value => squash(value).normalize('NFKC').toLocaleLowerCase();

/** A routine as the core sends it (routines_list / routines_save); anything else is dropped. */
export const isRoutine = value => isObject(value)
  && typeof value.id === 'string' && ID.test(value.id)
  && typeof value.name === 'string'
  && isObject(value.trigger) && typeof value.trigger.type === 'string'
  && Array.isArray(value.steps)
  && typeof value.enabled === 'boolean';

/** A step tool as routines_tools sends it. */
export const isTool = value => isObject(value) && typeof value.name === 'string' && value.name.length > 0
  && typeof value.description === 'string' && isObject(value.parameters);

export const sortRoutines = routines => (Array.isArray(routines) ? routines : [])
  .filter(isRoutine)
  .sort((a, b) => fold(a.name).localeCompare(fold(b.name)) || a.id.localeCompare(b.id));

export const withRoutine = (routines, routine) => sortRoutines([...(routines || []).filter(item => item.id !== routine.id), routine]);
export const withoutRoutine = (routines, id) => (routines || []).filter(item => item.id !== id);

const dayName = id => DAY_OPTIONS.find(option => option.id === id)?.label;
const signalWords = kind => SIGNAL_OPTIONS.find(option => option.id === kind)?.label || 'When something happens';

/** The trigger in plain words, exactly as the core says it (services/routines.py). */
export function triggerSummary(trigger) {
  if (!isObject(trigger)) return 'Run by hand';
  if (trigger.type === 'phrase') {
    const phrases = (Array.isArray(trigger.phrases) ? trigger.phrases : []).filter(item => typeof item === 'string');
    return phrases.length ? `When you say ${phrases.map(quote).join(' or ')}` : 'When you say it';
  }
  if (trigger.type === 'schedule') {
    if (trigger.repeat === 'weekdays') return `Weekdays at ${trigger.at}`;
    if (trigger.repeat === 'weekly') return `Every ${dayName(trigger.day) || 'week'} at ${trigger.at}`;
    return `Every day at ${trigger.at}`;
  }
  if (trigger.type === 'signal') {
    let conditions = { ...(isObject(trigger.filter) ? trigger.filter : {}) };
    const minutes = conditions.minutes;
    delete conditions.minutes;
    let words;
    if (trigger.kind === 'calendar.soon' && Number.isInteger(minutes)) words = `When an event starts in ${minutes} minutes`;
    else {
      words = signalWords(trigger.kind);
      if (minutes !== undefined) conditions = { minutes, ...conditions };
    }
    const keys = Object.keys(conditions);
    if (keys.length) words += ` (${keys.map(key => `${key} ${typeof conditions[key] === 'string' ? conditions[key] : JSON.stringify(conditions[key])}`).join(', ')})`;
    return words;
  }
  return 'Run by hand';
}

/** "16 Nov, 07:30" in this PC's time zone; '' for a missing or bad stamp. */
export function runTime(stamp) {
  if (typeof stamp !== 'string' || !stamp) return '';
  const date = new Date(stamp);
  if (Number.isNaN(date.getTime())) return '';
  const pad = value => String(value).padStart(2, '0');
  return `${date.getDate()} ${MONTHS[date.getMonth()]}, ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

const STEP_WORD = count => (count === 1 ? 'step' : 'steps');

/** { text, tone } for the last run: tone is a StatusChip tone. */
export function outcomeLine(routine) {
  const outcome = isObject(routine?.last_outcome) ? routine.last_outcome : null;
  if (!outcome) return { text: NEVER_RUN, tone: 'idle', state: null };
  const when = runTime(routine.last_run_at);
  const at = when ? ` · ${when}` : '';
  const total = Number.isInteger(outcome.steps) ? outcome.steps : 0;
  const done = Number.isInteger(outcome.done) ? outcome.done : 0;
  const step = Number.isInteger(outcome.step) ? outcome.step : done + 1;
  switch (outcome.state) {
    case 'running': return { text: `Running${at}`, tone: 'accent', state: 'running' };
    case 'ok': return { text: `Done, ${total} ${STEP_WORD(total)}${at}`, tone: 'ok', state: 'ok' };
    case 'declined': return { text: `Stopped at step ${step}: you declined${at}`, tone: 'warn', state: 'declined' };
    case 'skipped': return { text: `${outcome.reason === 'gaming' ? 'Skipped in gaming mode' : 'Skipped'}${at}`, tone: 'idle', state: 'skipped' };
    case 'interrupted': return { text: `Stopped after step ${done} when JARVIS closed${at}`, tone: 'warn', state: 'interrupted' };
    case 'failed': {
      const reason = typeof outcome.message === 'string' && outcome.message ? `: ${outcome.message}` : '';
      return { text: `Stopped at step ${step}${reason}${at}`, tone: 'danger', state: 'failed' };
    }
    default: return { text: NEVER_RUN, tone: 'idle', state: null };
  }
}

/** "3 steps" / "1 step". */
export const stepCount = count => `${count} ${STEP_WORD(count)}`;

/** A tool name in words: "home_control" -> "Home control", "mcp__gev__fly_to" -> "gev: fly to". */
export function toolTitle(name) {
  if (typeof name !== 'string' || !name) return 'Step';
  if (name.startsWith('mcp__')) {
    const parts = name.split('__');
    if (parts.length >= 3) return `${parts[1]}: ${parts.slice(2).join('__').replaceAll('_', ' ')}`;
  }
  const words = name.replaceAll('_', ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Tools a step may use, in name order (routine_run and routine_save left out). */
export const stepTools = tools => (Array.isArray(tools) ? tools : [])
  .filter(tool => isTool(tool) && !NOT_STEPS.includes(tool.name))
  .sort((a, b) => a.name.localeCompare(b.name));

// --- the editor -----------------------------------------------------------------------------
let nextKey = 0;
const stepKey = () => `step-${++nextKey}`;
const pretty = value => (isObject(value) && Object.keys(value).length ? JSON.stringify(value, null, 2) : '');

/** A new empty step (keys keep React rows stable while steps move). */
export const newStep = (tool = '') => ({ key: stepKey(), tool, argsText: '', say: '' });

/** The editor's fields for a routine, or for a new one. */
export function editorFields(routine) {
  const trigger = isObject(routine?.trigger) ? routine.trigger : { type: 'phrase', phrases: [] };
  const filter = { ...(isObject(trigger.filter) ? trigger.filter : {}) };
  const minutes = trigger.kind === 'calendar.soon' && [10, 30].includes(filter.minutes) ? String(filter.minutes) : '';
  if (minutes) delete filter.minutes;
  return {
    name: routine?.name || '',
    type: ['phrase', 'schedule', 'signal'].includes(trigger.type) ? trigger.type : 'phrase',
    phrases: Array.isArray(trigger.phrases) ? trigger.phrases.join(', ') : '',
    at: typeof trigger.at === 'string' ? trigger.at : '07:30',
    repeat: REPEAT_OPTIONS.some(option => option.id === trigger.repeat) ? trigger.repeat : 'daily',
    day: DAY_OPTIONS.some(option => option.id === trigger.day) ? trigger.day : 'mon',
    kind: SIGNAL_OPTIONS.some(option => option.id === trigger.kind) ? trigger.kind : 'calendar.soon',
    minutes,
    filterText: Object.keys(filter).length ? JSON.stringify(filter) : '',
    steps: (Array.isArray(routine?.steps) && routine.steps.length ? routine.steps : [{ tool: '' }]).map(step => ({
      key: stepKey(),
      tool: typeof step.tool === 'string' ? step.tool : '',
      argsText: pretty(step.args),
      say: typeof step.say === 'string' ? step.say : '',
    })),
  };
}

/** Steps with one moved up (delta -1) or down (+1); the same array when it can't move. */
export function moveStep(steps, index, delta) {
  const target = index + delta;
  if (!Array.isArray(steps) || index < 0 || index >= steps.length || target < 0 || target >= steps.length) return steps;
  const next = [...steps];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}
export const removeStep = (steps, index) => (steps.length <= 1 ? steps : steps.filter((_, at) => at !== index));
export const addStep = steps => (steps.length >= MAX_STEPS ? steps : [...steps, newStep()]);
export const updateStep = (steps, index, changes) => steps.map((step, at) => (at === index ? { ...step, ...changes } : step));

/** The phrases typed in the editor (commas separate them), trimmed, without repeats. */
export function splitPhrases(text) {
  const seen = new Set();
  return String(text ?? '').split(',').map(squash).filter(phrase => {
    const key = fold(phrase).replace(/[^\p{L}\p{N}\s]/gu, ' ').split(/\s+/).filter(Boolean).join(' ');
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/** { ok, value?, error? }: JSON text for a step's arguments; empty text is {}. */
export function parseArgs(text) {
  const raw = String(text ?? '').trim();
  if (!raw) return { ok: true, value: {} };
  if (raw.length > ARGS_CHARS) return { ok: false, error: `Keep the arguments under ${ARGS_CHARS} characters.` };
  try {
    const value = JSON.parse(raw);
    if (!isObject(value)) return { ok: false, error: 'Write the arguments as one JSON object, like {"name": "value"}.' };
    return { ok: true, value };
  } catch {
    return { ok: false, error: 'That isn\'t valid JSON. Use double quotes, like {"name": "value"}.' };
  }
}

const typeOf = value => {
  if (value === null) return 'null';
  if (Array.isArray(value)) return 'array';
  if (Number.isInteger(value)) return 'integer';
  return typeof value;
};
const typeMatches = (value, type) => {
  const actual = typeOf(value);
  if (type === 'number') return actual === 'number' || actual === 'integer';
  return actual === type;
};
const where = path => (path ? `${path}: ` : '');

/**
 * The first way ``value`` breaks a tool's JSON schema (the subset pydantic writes: type,
 * enum, const, string lengths and pattern, number bounds, properties, required,
 * additionalProperties, items, array lengths, anyOf / oneOf / allOf), or '' when it fits.
 */
export function schemaError(schema, value, path = '') {
  if (!isObject(schema)) return '';
  for (const part of Array.isArray(schema.allOf) ? schema.allOf : []) {
    const error = schemaError(part, value, path);
    if (error) return error;
  }
  const branches = Array.isArray(schema.anyOf) ? schema.anyOf : Array.isArray(schema.oneOf) ? schema.oneOf : null;
  if (branches) {
    const errors = branches.map(branch => schemaError(branch, value, path));
    if (!errors.some(error => !error)) return errors.find(Boolean) || `${where(path)}not an allowed value`;
  }
  if (schema.type !== undefined) {
    const types = Array.isArray(schema.type) ? schema.type : [schema.type];
    if (!types.some(type => typeMatches(value, type))) return `${where(path)}should be ${types.join(' or ')}`;
  }
  if (Array.isArray(schema.enum) && !schema.enum.some(item => item === value)) {
    return `${where(path)}should be one of ${schema.enum.map(item => JSON.stringify(item)).join(', ')}`;
  }
  if ('const' in schema && schema.const !== value) return `${where(path)}should be ${JSON.stringify(schema.const)}`;
  if (typeof value === 'string') {
    if (Number.isInteger(schema.minLength) && value.length < schema.minLength) return `${where(path)}is too short`;
    if (Number.isInteger(schema.maxLength) && value.length > schema.maxLength) return `${where(path)}is too long (at most ${schema.maxLength} characters)`;
    if (typeof schema.pattern === 'string') {
      let pattern = null;
      try { pattern = new RegExp(schema.pattern, 'u'); } catch { pattern = null; }
      if (pattern && !pattern.test(value)) return `${where(path)}isn't in the expected form`;
    }
  }
  if (typeof value === 'number') {
    if (typeof schema.minimum === 'number' && value < schema.minimum) return `${where(path)}should be at least ${schema.minimum}`;
    if (typeof schema.maximum === 'number' && value > schema.maximum) return `${where(path)}should be at most ${schema.maximum}`;
    if (typeof schema.exclusiveMinimum === 'number' && value <= schema.exclusiveMinimum) return `${where(path)}should be more than ${schema.exclusiveMinimum}`;
    if (typeof schema.exclusiveMaximum === 'number' && value >= schema.exclusiveMaximum) return `${where(path)}should be less than ${schema.exclusiveMaximum}`;
  }
  if (Array.isArray(value)) {
    if (Number.isInteger(schema.minItems) && value.length < schema.minItems) return `${where(path)}needs at least ${schema.minItems} items`;
    if (Number.isInteger(schema.maxItems) && value.length > schema.maxItems) return `${where(path)}takes at most ${schema.maxItems} items`;
    if (isObject(schema.items)) {
      for (let index = 0; index < value.length; index += 1) {
        const error = schemaError(schema.items, value[index], `${path || 'item'}[${index}]`);
        if (error) return error;
      }
    }
  }
  if (isObject(value)) {
    const properties = isObject(schema.properties) ? schema.properties : {};
    for (const name of Array.isArray(schema.required) ? schema.required : []) {
      if (!(name in value)) return `${path ? `${path}.` : ''}${name} is required`;
    }
    for (const [name, item] of Object.entries(value)) {
      const child = path ? `${path}.${name}` : name;
      if (name in properties) {
        const error = schemaError(properties[name], item, child);
        if (error) return error;
      } else if (schema.additionalProperties === false) {
        return `${child} isn't an argument of this tool`;
      } else if (isObject(schema.additionalProperties)) {
        const error = schemaError(schema.additionalProperties, item, child);
        if (error) return error;
      }
    }
  }
  return '';
}

function parseFilter(text) {
  const raw = String(text ?? '').trim();
  if (!raw) return { ok: true, value: {} };
  let value;
  try { value = JSON.parse(raw); } catch { return { ok: false, error: 'Write the filter as JSON, like {"state": "failed"}.' }; }
  if (!isObject(value)) return { ok: false, error: 'Write the filter as one JSON object.' };
  const keys = Object.keys(value);
  if (keys.length > 5) return { ok: false, error: 'A filter has at most 5 fields.' };
  if (!Object.values(value).every(item => ['string', 'boolean'].includes(typeof item) || Number.isInteger(item))) {
    return { ok: false, error: 'Filter values are text, whole numbers or true/false.' };
  }
  return { ok: true, value };
}

/**
 * { ok, errors, value }: errors is keyed by field ("name", "phrases", "at", "filter") and by
 * step ("step-<key>-tool", "step-<key>-args", "step-<key>-say"); value is the routines_save
 * payload { name, trigger, steps } when ok. ``tools`` comes from routines_tools.
 */
export function validateEditor(fields, tools = []) {
  const errors = {};
  const name = squash(fields?.name);
  if (!name) errors.name = 'Give the routine a name.';
  else if (name.length > NAME_LIMIT) errors.name = `Keep the name under ${NAME_LIMIT} characters.`;

  let trigger = null;
  if (fields?.type === 'phrase') {
    const phrases = splitPhrases(fields.phrases);
    if (!phrases.length) errors.phrases = 'Type at least one phrase.';
    else if (phrases.length > MAX_PHRASES) errors.phrases = `Use at most ${MAX_PHRASES} phrases.`;
    else if (phrases.some(phrase => phrase.length > PHRASE_LIMIT)) errors.phrases = `Keep each phrase under ${PHRASE_LIMIT} characters.`;
    trigger = { type: 'phrase', phrases };
  } else if (fields?.type === 'schedule') {
    if (!TIME.test(String(fields.at ?? ''))) errors.at = 'Use a time like 07:30.';
    trigger = { type: 'schedule', at: fields.at, repeat: fields.repeat };
    if (fields.repeat === 'weekly') trigger.day = fields.day;
  } else if (fields?.type === 'signal') {
    const filter = parseFilter(fields.filterText);
    if (!filter.ok) errors.filter = filter.error;
    const value = { ...(filter.value || {}) };
    if (fields.kind === 'calendar.soon' && fields.minutes) value.minutes = Number(fields.minutes);
    trigger = { type: 'signal', kind: fields.kind };
    if (Object.keys(value).length) trigger.filter = value;
  } else {
    errors.type = 'Choose when the routine runs.';
  }

  const byName = new Map(stepTools(tools).map(tool => [tool.name, tool]));
  const rows = Array.isArray(fields?.steps) ? fields.steps : [];
  if (!rows.length) errors.steps = 'Add at least one step.';
  if (rows.length > MAX_STEPS) errors.steps = `A routine has at most ${MAX_STEPS} steps.`;
  const steps = rows.map(row => {
    const prefix = `step-${row.key}`;
    const tool = byName.get(row.tool);
    if (!row.tool) errors[`${prefix}-tool`] = 'Choose a tool.';
    else if (NOT_STEPS.includes(row.tool)) errors[`${prefix}-tool`] = "A routine can't run or save routines.";
    else if (!tool) errors[`${prefix}-tool`] = "JARVIS doesn't have this tool right now.";
    const args = parseArgs(row.argsText);
    if (!args.ok) errors[`${prefix}-args`] = args.error;
    else if (tool) {
      const problem = schemaError(tool.parameters, args.value);
      if (problem) errors[`${prefix}-args`] = `Doesn't fit ${row.tool}: ${problem}.`;
    }
    const say = squash(row.say);
    if (say.length > SAY_LIMIT) errors[`${prefix}-say`] = `Keep the line under ${SAY_LIMIT} characters.`;
    return { tool: row.tool, args: args.ok ? args.value : {}, ...(say ? { say } : {}) };
  });
  const ok = Object.keys(errors).length === 0;
  return { ok, errors, value: ok ? { name, trigger, steps } : null };
}

/** The argument fields a tool takes, for the hint under the JSON box: "query (required), limit". */
export function argumentHint(tool) {
  const properties = isObject(tool?.parameters?.properties) ? Object.keys(tool.parameters.properties) : [];
  if (!properties.length) return 'This tool takes no arguments.';
  const required = new Set(Array.isArray(tool.parameters.required) ? tool.parameters.required : []);
  return `Arguments: ${properties.map(name => (required.has(name) ? `${name} (required)` : name)).join(', ')}`;
}

export function routinesFailureMessage(error) {
  const code = error?.code;
  if (code === 'offline' || code === 'disconnected') return 'JARVIS core is offline. Reconnect, then try again.';
  if (code === 'timeout') return 'The core did not answer. Try again.';
  if (['invalid_arguments', 'routine_conflict', 'routine_not_found', 'routine_running', 'routines_full', 'routines_unavailable'].includes(code)
    && typeof error?.message === 'string' && error.message) return error.message;
  return 'Routines could not be read or saved. Try again.';
}
