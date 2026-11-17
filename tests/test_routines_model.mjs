import test from 'node:test';
import assert from 'node:assert/strict';
import {
  MAX_STEPS, NEVER_RUN, addStep, argumentHint, editorFields, isRoutine, moveStep, newStep, outcomeLine, parseArgs,
  removeStep, routinesFailureMessage, schemaError, sortRoutines, splitPhrases, stepCount, stepTools, toolTitle,
  triggerSummary, validateEditor, withRoutine, withoutRoutine,
} from '../src/features/routines/routinesModel.js';

let next = 0;
const routine = (extra = {}) => ({
  id: `00000000-0000-4000-8000-${String(++next).padStart(12, '0')}`, name: 'Movie time',
  trigger: { type: 'phrase', phrases: ['movie time'] }, steps: [{ tool: 'lights', args: { value: 'dim' } }],
  enabled: true, created_at: '2026-11-16T01:00:00+00:00', updated_at: null, last_run_at: null, last_outcome: null, ...extra,
});
const LIGHTS = {
  name: 'lights', description: 'Dim or brighten a light.',
  parameters: { type: 'object', additionalProperties: false, required: ['value'],
    properties: { value: { type: 'string', minLength: 1, maxLength: 10 }, level: { anyOf: [{ type: 'integer', minimum: 0, maximum: 100 }, { type: 'null' }] } } },
};
const WEATHER = { name: 'weather', description: 'Weather.', parameters: { type: 'object', properties: { when: { enum: ['now', 'today'] } } } };
const TOOLS = [WEATHER, LIGHTS, { name: 'routine_run', description: 'x', parameters: {} }, { name: 'routine_save', description: 'x', parameters: {} }];

test('trigger summaries say when a routine runs, like the core', () => {
  assert.equal(triggerSummary({ type: 'phrase', phrases: ['movie time'] }), 'When you say ‘movie time’');
  assert.equal(triggerSummary({ type: 'phrase', phrases: ['movie time', 'masa wayang'] }), 'When you say ‘movie time’ or ‘masa wayang’');
  assert.equal(triggerSummary({ type: 'schedule', at: '07:30', repeat: 'weekdays' }), 'Weekdays at 07:30');
  assert.equal(triggerSummary({ type: 'schedule', at: '07:30', repeat: 'daily' }), 'Every day at 07:30');
  assert.equal(triggerSummary({ type: 'schedule', at: '21:00', repeat: 'weekly', day: 'fri' }), 'Every Friday at 21:00');
  assert.equal(triggerSummary({ type: 'signal', kind: 'calendar.soon', filter: { minutes: 10 } }), 'When an event starts in 10 minutes');
  assert.equal(triggerSummary({ type: 'signal', kind: 'calendar.soon' }), 'When an event is coming up');
  assert.equal(triggerSummary({ type: 'signal', kind: 'job.finished', filter: { state: 'failed' } }), 'When a job finishes (state failed)');
  assert.equal(triggerSummary({ type: 'signal', kind: 'job.finished', filter: { minutes: 5, live: true } }), 'When a job finishes (minutes 5, live true)');
  assert.equal(triggerSummary(null), 'Run by hand');
});

test('the last run line names the outcome and its tone', () => {
  assert.deepEqual(outcomeLine(routine()), { text: NEVER_RUN, tone: 'idle', state: null });
  const at = new Date(2026, 10, 16, 7, 30).toISOString();
  assert.deepEqual(outcomeLine(routine({ last_run_at: at, last_outcome: { state: 'ok', steps: 3, done: 3 } })),
    { text: 'Done, 3 steps · 16 Nov, 07:30', tone: 'ok', state: 'ok' });
  assert.equal(outcomeLine(routine({ last_outcome: { state: 'ok', steps: 1, done: 1 } })).text, 'Done, 1 step');
  assert.deepEqual(outcomeLine(routine({ last_outcome: { state: 'failed', steps: 3, done: 1, step: 2, message: 'Plug offline.' } })),
    { text: 'Stopped at step 2: Plug offline.', tone: 'danger', state: 'failed' });
  assert.equal(outcomeLine(routine({ last_outcome: { state: 'declined', steps: 3, done: 1, step: 2 } })).text, 'Stopped at step 2: you declined');
  assert.equal(outcomeLine(routine({ last_outcome: { state: 'skipped', reason: 'gaming' } })).text, 'Skipped in gaming mode');
  assert.equal(outcomeLine(routine({ last_outcome: { state: 'running', steps: 2, done: 0 } })).tone, 'accent');
  assert.equal(outcomeLine(routine({ last_outcome: { state: 'interrupted', steps: 2, done: 1 } })).text, 'Stopped after step 1 when JARVIS closed');
  assert.equal(outcomeLine(routine({ last_run_at: 'nonsense', last_outcome: { state: 'ok', steps: 2 } })).text, 'Done, 2 steps');
});

test('routines from the core are checked, sorted by name and replaced by id', () => {
  const b = routine({ name: 'b night' }), a = routine({ name: 'Alarm' });
  assert.deepEqual(sortRoutines([b, { id: 'x' }, a, null]).map(item => item.name), ['Alarm', 'b night']);
  assert.equal(isRoutine({ ...a, enabled: 'yes' }), false);
  const renamed = { ...b, name: 'Aardvark' };
  assert.deepEqual(withRoutine([a, b], renamed).map(item => item.name), ['Aardvark', 'Alarm']);
  assert.deepEqual(withoutRoutine([a, b], a.id), [b]);
  assert.equal(stepCount(1), '1 step');
  assert.equal(stepCount(4), '4 steps');
});

test('the step picker lists tools by name without routine_run or routine_save', () => {
  assert.deepEqual(stepTools(TOOLS).map(tool => tool.name), ['lights', 'weather']);
  assert.equal(toolTitle('home_control'), 'Home control');
  assert.equal(toolTitle('mcp__gev__fly_to'), 'gev: fly to');
  assert.equal(argumentHint(LIGHTS), 'Arguments: value (required), level');
  assert.equal(argumentHint({ parameters: { type: 'object', properties: {} } }), 'This tool takes no arguments.');
});

test('editor fields round-trip a routine and default a new one', () => {
  const fresh = editorFields(null);
  assert.equal(fresh.type, 'phrase');
  assert.equal(fresh.steps.length, 1);
  assert.equal(fresh.at, '07:30');
  const fields = editorFields(routine({ trigger: { type: 'signal', kind: 'calendar.soon', filter: { minutes: 10, urgency: 2 } },
    steps: [{ tool: 'lights', args: { value: 'dim' }, say: 'Lights down.' }] }));
  assert.equal(fields.type, 'signal');
  assert.equal(fields.minutes, '10');
  assert.equal(fields.filterText, '{"urgency":2}');
  assert.equal(fields.steps[0].argsText, '{\n  "value": "dim"\n}');
  assert.equal(fields.steps[0].say, 'Lights down.');
  const checked = validateEditor(fields, TOOLS);
  assert.equal(checked.ok, true);
  assert.deepEqual(checked.value, { name: 'Movie time', trigger: { type: 'signal', kind: 'calendar.soon', filter: { urgency: 2, minutes: 10 } },
    steps: [{ tool: 'lights', args: { value: 'dim' }, say: 'Lights down.' }] });
});

test('validation covers the name, each trigger type and each step', () => {
  const base = { ...editorFields(null), name: ' Movie   time ', phrases: 'Movie time, movie-time!, masa wayang',
    steps: [{ ...newStep('lights'), argsText: '{"value": "dim"}' }] };
  const ok = validateEditor(base, TOOLS);
  assert.equal(ok.ok, true);
  assert.deepEqual(ok.value.trigger, { type: 'phrase', phrases: ['Movie time', 'masa wayang'] });
  assert.equal(ok.value.name, 'Movie time');

  assert.equal(validateEditor({ ...base, name: '  ' }, TOOLS).errors.name, 'Give the routine a name.');
  assert.equal(validateEditor({ ...base, phrases: ' , ' }, TOOLS).errors.phrases, 'Type at least one phrase.');
  assert.equal(validateEditor({ ...base, phrases: 'a, b, c, d, e, f' }, TOOLS).errors.phrases, 'Use at most 5 phrases.');

  const schedule = validateEditor({ ...base, type: 'schedule', at: '7:30', repeat: 'weekly', day: 'wed' }, TOOLS);
  assert.equal(schedule.errors.at, 'Use a time like 07:30.');
  assert.deepEqual(validateEditor({ ...base, type: 'schedule', at: '07:30', repeat: 'weekly', day: 'wed' }, TOOLS).value.trigger,
    { type: 'schedule', at: '07:30', repeat: 'weekly', day: 'wed' });
  assert.deepEqual(validateEditor({ ...base, type: 'schedule', at: '07:30', repeat: 'weekdays', day: 'wed' }, TOOLS).value.trigger,
    { type: 'schedule', at: '07:30', repeat: 'weekdays' });

  assert.deepEqual(validateEditor({ ...base, type: 'signal', kind: 'job.finished', filterText: '' }, TOOLS).value.trigger,
    { type: 'signal', kind: 'job.finished' });
  assert.match(validateEditor({ ...base, type: 'signal', kind: 'job.finished', filterText: '{"a": [1]}' }, TOOLS).errors.filter, /whole numbers/);
  assert.match(validateEditor({ ...base, type: 'signal', kind: 'job.finished', filterText: 'state=failed' }, TOOLS).errors.filter, /JSON/);

  const [row] = base.steps;
  const step = (changes, tools = TOOLS) => validateEditor({ ...base, steps: [{ ...row, ...changes }] }, tools).errors;
  assert.equal(step({ tool: '' })[`step-${row.key}-tool`], 'Choose a tool.');
  assert.equal(step({ tool: 'routine_run' })[`step-${row.key}-tool`], "A routine can't run or save routines.");
  assert.equal(step({ tool: 'gone' })[`step-${row.key}-tool`], "JARVIS doesn't have this tool right now.");
  assert.match(step({ argsText: '{value: dim}' })[`step-${row.key}-args`], /valid JSON/);
  assert.match(step({ argsText: '[1]' })[`step-${row.key}-args`], /one JSON object/);
  assert.equal(step({ argsText: '{}' })[`step-${row.key}-args`], "Doesn't fit lights: value is required.");
  assert.equal(step({ argsText: '{"value": "dim", "colour": "red"}' })[`step-${row.key}-args`], "Doesn't fit lights: colour isn't an argument of this tool.");
  assert.equal(step({ argsText: '{"value": 3}' })[`step-${row.key}-args`], "Doesn't fit lights: value: should be string.");
  assert.equal(step({ say: 'x'.repeat(201) })[`step-${row.key}-say`], 'Keep the line under 200 characters.');
  const tooMany = validateEditor({ ...base, steps: Array.from({ length: MAX_STEPS + 1 }, () => ({ ...newStep('lights'), argsText: '{"value": "a"}' })) }, TOOLS);
  assert.equal(tooMany.errors.steps, 'A routine has at most 12 steps.');
  assert.equal(validateEditor({ ...base, steps: [] }, TOOLS).errors.steps, 'Add at least one step.');
});

test('arguments are checked against the JSON schema subset pydantic writes', () => {
  assert.equal(schemaError(LIGHTS.parameters, { value: 'dim', level: null }), '');
  assert.equal(schemaError(LIGHTS.parameters, { value: 'dim', level: 50 }), '');
  assert.equal(schemaError(LIGHTS.parameters, { value: 'dim', level: 150 }), 'level: should be at most 100');
  assert.equal(schemaError(LIGHTS.parameters, { value: 'x'.repeat(11) }), 'value: is too long (at most 10 characters)');
  assert.equal(schemaError(WEATHER.parameters, { when: 'later' }), 'when: should be one of "now", "today"');
  assert.equal(schemaError({ type: 'object', properties: { tags: { type: 'array', maxItems: 1, items: { type: 'string' } } } }, { tags: ['a', 2] }), 'tags: takes at most 1 items');
  assert.equal(schemaError({ type: 'object', properties: { tags: { type: 'array', items: { type: 'string' } } } }, { tags: ['a', 2] }), 'tags[1]: should be string');
  assert.equal(schemaError({ type: 'object', properties: { code: { type: 'string', pattern: '^[A-Z]{3}$' } } }, { code: 'kul' }), "code: isn't in the expected form");
  assert.equal(schemaError({ type: 'number' }, 2), '');
  assert.equal(schemaError({ type: 'integer' }, 2.5), 'should be integer');
  assert.deepEqual(parseArgs(''), { ok: true, value: {} });
  assert.equal(parseArgs('x'.repeat(4001)).ok, false);
});

test('steps add, move and remove within the limits', () => {
  const one = [newStep('a')];
  assert.equal(removeStep(one, 0), one);
  const three = addStep(addStep(one));
  assert.equal(three.length, 3);
  const keys = three.map(step => step.key);
  assert.deepEqual(moveStep(three, 0, 1).map(step => step.key), [keys[1], keys[0], keys[2]]);
  assert.deepEqual(moveStep(three, 2, -1).map(step => step.key), [keys[0], keys[2], keys[1]]);
  assert.equal(moveStep(three, 0, -1), three);
  assert.equal(moveStep(three, 2, 1), three);
  assert.deepEqual(removeStep(three, 1).map(step => step.key), [keys[0], keys[2]]);
  let full = one;
  for (let index = 0; index < 20; index += 1) full = addStep(full);
  assert.equal(full.length, MAX_STEPS);
  assert.deepEqual(splitPhrases('Movie time,  movie TIME , , wayang'), ['Movie time', 'wayang']);
});

test('failure messages are plain', () => {
  assert.equal(routinesFailureMessage({ code: 'offline' }), 'JARVIS core is offline. Reconnect, then try again.');
  assert.equal(routinesFailureMessage({ code: 'routine_conflict', message: 'There\'s already a routine called X.' }), "There's already a routine called X.");
  assert.equal(routinesFailureMessage({ code: 'weird', message: 'stack trace' }), 'Routines could not be read or saved. Try again.');
});
