import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { FILTERS, callChip, emptyState, filterCalls, summaryText } from '../src/features/calls/callsModel.js';
import {
  GROUP_COPY, GROUP_OPTIONS, NOTE_LABEL, avatarText, callPeopleActions, cleanName, editorFields, emptyPerson, errorField, firstName,
  formatNumber, groupChip, groupCopy, normalizeNumber, peopleCount, peopleFailureMessage, personChanged, sortPeople, validatePerson, whenHeading,
} from '../src/features/calls/peopleModel.js';
import { createPeopleClient, isPerson } from '../src/features/calls/peopleClient.js';
import { isCallDetail, isCallSummary } from '../src/transport/callsClient.ts';

const MUM = { id: '0b6f3c9e-8a51-4c2e-9d7a-2f1e5b8c4a10', name: 'Mum', numbers: ['+60123456789'], group: 'vip', note: 'My mother. Prefers Malay.' };

test('Calls tabs are Needs you, All, Done, Spam and People', () => {
  assert.deepEqual(FILTERS.map(entry => entry.label), ['Needs you', 'All', 'Done', 'Spam', 'People']);
  assert.deepEqual(FILTERS.map(entry => entry.id), ['needs_you', 'all', 'done', 'spam', 'people']);
});

test('Spam lists triage spam and blocked records, never under Needs you', () => {
  const calls = [{ id: 'a', status: 'spam' }, { id: 'b', status: 'blocked' }, { id: 'c', status: 'needs_you' }, { id: 'd', status: 'done' }];
  assert.deepEqual(filterCalls(calls, 'spam').map(call => call.id), ['a', 'b']);
  assert.deepEqual(filterCalls(calls, 'needs_you').map(call => call.id), ['c']);
  assert.deepEqual(filterCalls(calls, 'done').map(call => call.id), ['d']);
  assert.deepEqual(callChip({ status: 'spam' }), { tone: 'idle', label: 'SPAM' });
  assert.deepEqual(callChip({ status: 'blocked' }), { tone: 'danger', label: 'BLOCKED' });
  assert.equal(emptyState('spam').title, 'No spam');
  assert.match(summaryText({ status: 'blocked', triage_state: 'skipped' }), /^Blocked number\./);
});

test('group options, chips and the "when they call" copy', () => {
  assert.deepEqual(GROUP_OPTIONS.map(option => option.label), ['VIP', 'Known', 'Blocked']);
  assert.deepEqual(groupChip('vip'), { tone: 'accent', label: 'VIP' });
  assert.deepEqual(groupChip('known'), { tone: 'idle', label: 'KNOWN' });
  assert.deepEqual(groupChip('blocked'), { tone: 'danger', label: 'BLOCKED' });
  assert.equal(groupChip('other'), null);
  assert.equal(GROUP_COPY.vip, "JARVIS greets them by name, takes the message, alerts you on the PC at once, and phones you with it, even if it isn't urgent. Quiet hours still hold unless they say it's urgent.");
  assert.equal(GROUP_COPY.known, "JARVIS greets them by name and takes a message. It phones you only if it's urgent, as for anyone else.");
  assert.equal(GROUP_COPY.blocked, 'JARVIS says you aren\'t taking calls and ends the call politely. No message, no alert. The call still shows under Spam.');
  assert.equal(groupCopy('nope'), GROUP_COPY.known);
  assert.equal(NOTE_LABEL, 'Who they are to you (JARVIS may use this)');
  assert.equal(whenHeading('Mum'), "When Mum calls and you don't pick up");
  assert.equal(whenHeading('Aina Rahman'), "When Aina calls and you don't pick up");
  assert.equal(whenHeading('+60 12-345 6789'), "When +60 12-345 6789 calls and you don't pick up");
  assert.equal(whenHeading('  '), "When this person calls and you don't pick up");
  assert.equal(firstName(' Dr\tLim '), 'Dr');
});

test('avatar, count and number display', () => {
  assert.equal(avatarText(MUM), 'M');
  assert.equal(avatarText({ name: 'aina' }), 'A');
  assert.equal(avatarText({ name: '+60 12-345 6789' }), '#');
  assert.equal(avatarText({ name: '' }), '#');
  assert.equal(peopleCount(1), '1 person');
  assert.equal(peopleCount(0), '0 people');
  assert.equal(peopleCount(12), '12 people');
  assert.equal(formatNumber('+60123456789'), '+60 12-345 6789');
  assert.equal(formatNumber('+601123456789'), '+60 11-2345 6789');
  assert.equal(formatNumber('+60322223333'), '+60 3-2222 3333');
  assert.equal(formatNumber('+447700900123'), '+447700900123');
});

test('numbers normalise like the core: separators go, a local 0 becomes +60', () => {
  assert.equal(normalizeNumber('+60 12-345 6789'), '+60123456789');
  assert.equal(normalizeNumber(' (+60) 12.345.6789 '), '+60123456789');
  assert.equal(normalizeNumber('012-345 6789'), '+60123456789'); // Malaysian local trunk format
  assert.equal(normalizeNumber('03-2161 4400'), '+60321614400');
  assert.equal(normalizeNumber('(03) 2161 4400'), '+60321614400');
  assert.equal(normalizeNumber('0060123456789'), null); // "00..." keeps today's handling
  assert.equal(normalizeNumber('0'), null);
  assert.equal(normalizeNumber('60123456789'), null);
  assert.equal(normalizeNumber('+0123'), null);
  assert.equal(normalizeNumber('+266696687'), null); // a withheld caller ID spelling
  assert.equal(normalizeNumber(60123456789), null);
});

test('validation: empty name, bad number, duplicates and the limits', () => {
  const people = [MUM, { id: 'b2', name: 'Aina', numbers: ['+60198765432'], group: 'known', note: '' }];
  const ok = validatePerson({ id: MUM.id, name: ' Mum\t ', numbers: ['+60 12-345 6789', ''], group: 'vip', note: ' My  mother.\r\nPrefers Malay. ' }, people);
  assert.equal(ok.ok, true);
  assert.deepEqual(ok.value, { id: MUM.id, name: 'Mum', numbers: ['+60123456789'], group: 'vip', note: 'My mother.\nPrefers Malay.' });
  assert.equal(personChanged({ ...ok.value, note: MUM.note }, MUM), false);
  assert.equal(personChanged({ ...ok.value, group: 'known' }, MUM), true);
  assert.equal(personChanged(ok.value, null), true);

  const bad = validatePerson({ id: null, name: '  ', numbers: ['12-345 6789', '+60 19-876 5432', '+60123456789', '+60 12 345 6789'], group: 'vip', note: '' }, people);
  assert.equal(bad.ok, false);
  assert.equal(bad.errors.name, 'Enter a name.');
  assert.deepEqual(bad.errors.numbers, [
    'Enter a phone number, like 012-345 6789 or +60 12-345 6789.',
    'This number is already saved for Aina.',
    'This number is already saved for Mum.',
    'This number is already saved for Mum.',
  ]);
  const repeat = validatePerson({ id: null, name: 'X', numbers: ['+60111111111', '011-111 1111'], group: 'known', note: '' }, []);
  assert.deepEqual(repeat.errors.numbers, ['', 'This number is already listed.']);
  assert.equal(validatePerson({ name: 'X', numbers: [''], group: 'known', note: '' }).errors.list, 'Add at least one phone number.');
  assert.match(validatePerson({ name: 'X', numbers: ['+601', '+602', '+603', '+604', '+605', '+606'], group: 'known' }).errors.list, /at most 5/);
  assert.match(validatePerson({ name: 'x'.repeat(61), numbers: ['+60111111111'], group: 'known' }).errors.name, /at most 60/);
  assert.match(validatePerson({ name: 'X', numbers: ['+60111111111'], group: 'known', note: 'y'.repeat(301) }).errors.note, /at most 300/);
  assert.equal(validatePerson({ name: 'X', numbers: ['+60111111111'], group: 'family' }).value.group, 'known');
  assert.equal(cleanName('a\u0007b  c'), 'a b c');
});

test('editor fields, drafts, ordering and failures', () => {
  assert.deepEqual(emptyPerson(), { id: null, name: '', numbers: [''], group: 'known', note: '' });
  assert.deepEqual(editorFields(MUM), { id: MUM.id, name: 'Mum', numbers: ['+60 12-345 6789'], group: 'vip', note: MUM.note });
  assert.deepEqual(sortPeople([{ id: '2', name: 'zed' }, { id: '1', name: 'Aina' }, { id: '3', name: 'mum' }]).map(person => person.id), ['1', '3', '2']);
  assert.equal(errorField('invalid_name'), 'name');
  assert.equal(errorField('duplicate_number'), 'list');
  assert.equal(errorField('invalid_note'), 'note');
  assert.equal(errorField('storage_error'), 'form');
  assert.equal(peopleFailureMessage({ code: 'no_number' }), 'There is no number for this caller.');
  assert.equal(peopleFailureMessage({ code: 'offline' }), 'JARVIS core is offline. Reconnect and try again.');
});

test('call detail actions apply only to incoming calls with a number', () => {
  assert.equal(callPeopleActions({ direction: 'outbound', can_add_person: true }), null);
  assert.equal(callPeopleActions({ direction: 'inbound', can_add_person: false }), null);
  assert.deepEqual(callPeopleActions({ direction: 'inbound', can_add_person: true, contact: null }), { vip: true, block: true });
  assert.deepEqual(callPeopleActions({ direction: 'inbound', can_add_person: true, contact: { group: 'vip' } }), { vip: false, block: true });
  assert.deepEqual(callPeopleActions({ direction: 'inbound', can_add_person: true, contact: { group: 'blocked' } }), { vip: true, block: false });
});

test('call summaries and details accept the people fields', () => {
  const summary = { id: 'rec-1', direction: 'inbound', mode: 'screening', counterpart_masked: '+60 12-•••• 6789', name: 'Mum', started_at: 1793000000,
    duration_seconds: 30, urgency: 'normal', needs_owner: false, summary: null, status: 'spam', outcome_status: null, caller_group: 'vip' };
  assert.equal(isCallSummary(summary), true);
  assert.equal(isCallSummary({ ...summary, status: 'blocked', caller_group: null }), true);
  assert.equal(isCallSummary({ ...summary, caller_group: 'family' }), false);
  const detail = { ...summary, fields: null, triage: null, triage_state: 'skipped', transcript: [], outcome: null, related_ids: [],
    contact: { id: MUM.id, name: 'Mum', group: 'vip' }, can_add_person: true };
  assert.equal(isCallDetail(detail), true);
  assert.equal(isCallDetail({ ...detail, contact: { id: MUM.id, name: 'Mum', group: 'x' } }), false);
});

class FakeSocket extends EventEmitter {
  constructor(answers) { super(); this.connected = true; this.answers = answers; this.sent = []; }
  emit(event, data, ack) {
    if (typeof ack !== 'function') return super.emit(event, data);
    this.sent.push([event, data]);
    setTimeout(() => ack(this.answers[event]), 0);
    return true;
  }
}

test('the people client checks every answer', async () => {
  assert.equal(isPerson(MUM), true);
  assert.equal(isPerson({ ...MUM, numbers: ['0123'] }), false);
  assert.equal(isPerson({ ...MUM, id: null, name: '' }, true), true);
  const socket = new FakeSocket({
    contacts_list: { ok: true, people: [MUM], limit: 500 },
    contacts_save: { ok: true, person: MUM },
    contacts_delete: { ok: true },
    contacts_call_draft: { ok: true, existing: false, person: { ...MUM, id: null, name: '' } },
    contacts_call_mark: { ok: false, code: 'no_number', message: 'There is no number for this caller.' },
  });
  const client = createPeopleClient(socket);
  assert.deepEqual(await client.list(), [MUM]);
  assert.deepEqual(await client.save({ id: null, name: 'Mum', numbers: ['+60123456789'], group: 'vip', note: '' }), MUM);
  assert.deepEqual(socket.sent.at(-1), ['contacts_save', { name: 'Mum', numbers: ['+60123456789'], group: 'vip', note: '' }]);
  await client.remove(MUM.id);
  assert.equal((await client.callDraft('rec-1')).existing, false);
  await assert.rejects(client.callMark('rec-1', 'vip'), error => error.code === 'no_number');
  await assert.rejects(client.callMark('rec-1', 'friends'), error => error.code === 'invalid_arguments');
  client.dispose();
});
