import test from 'node:test';
import assert from 'node:assert/strict';
import {
  EMPTY_COPY, KIND_GROUPS, PAGE_DESCRIPTION, PAUSED_LINE, currentFacts, editChanges, editFields, factCount, filterFacts,
  groupFacts, isFact, learnedDate, learnedLine, learnedText, memoryFailureMessage, rememberedText, sensitivityChip,
  sourceConversation, validateEdit, withFact, withoutFact,
} from '../src/features/memory/memoryModel.js';

const CONVERSATION = '9b2f4c1e-7a3d-4e5f-8c6b-1d2e3f4a5b6c';
let next = 0;
const fact = (extra = {}) => ({
  id: `00000000-0000-4000-8000-${String(++next).padStart(12, '0')}`, kind: 'preference', subject: 'Tea', text: 'Likes teh tarik.',
  confidence: 1, pinned: false, sensitivity: 'normal', source_conversation_id: null, source_turn: null,
  created_at: '2026-11-08T03:00:00+00:00', updated_at: null, valid_from: null, valid_to: null, superseded_by: null, ...extra,
});

test('the page copy is exactly as designed', () => {
  assert.equal(PAGE_DESCRIPTION, 'Things JARVIS has learned about you. Edit or delete anything; nothing here leaves this PC.');
  assert.equal(PAUSED_LINE, "Paused — JARVIS won't save new facts.");
  assert.equal(EMPTY_COPY, "JARVIS hasn't learned anything yet. Say 'remember that…' or just talk — it picks up lasting facts after a conversation.");
  assert.deepEqual(KIND_GROUPS.map(([, heading]) => heading), ['About you', 'Preferences', 'People', 'Places', 'Routines', 'Moments']);
});

test('facts are grouped by kind in the page order, pinned first, then newest first', () => {
  const old = fact({ subject: 'Old', created_at: '2026-10-01T00:00:00+00:00' });
  const recent = fact({ subject: 'Recent', created_at: '2026-11-10T00:00:00+00:00' });
  const pinned = fact({ subject: 'Pinned', pinned: true, created_at: '2026-09-01T00:00:00+00:00' });
  const episode = fact({ kind: 'episode', subject: 'Langkawi' });
  const profile = fact({ kind: 'profile', subject: 'Name' });
  const person = fact({ kind: 'person', subject: 'Aina' });
  const groups = groupFacts([episode, old, recent, person, pinned, profile]);
  assert.deepEqual(groups.map(group => [group.kind, group.heading]),
    [['profile', 'About you'], ['preference', 'Preferences'], ['person', 'People'], ['episode', 'Moments']]);
  assert.deepEqual(groups[1].facts.map(item => item.subject), ['Pinned', 'Recent', 'Old']);
  assert.deepEqual(groupFacts([]), []);
});

test('superseded and malformed facts are never shown', () => {
  const live = fact();
  const replaced = fact({ superseded_by: live.id });
  assert.deepEqual(currentFacts([live, replaced, null, { id: 'x' }, fact({ kind: 'secret' })]), [live]);
  assert.deepEqual(groupFacts([replaced]), []);
  assert.equal(isFact(fact({ pinned: 1 })), false);
  assert.deepEqual(currentFacts(undefined), []);
});

test('search filters subject and text locally, case-insensitive, every word', () => {
  const tea = fact({ subject: 'Tea', text: 'Likes TEH tarik less sweet.' });
  const office = fact({ kind: 'place', subject: 'Office', text: 'Works in Bangsar.' });
  const facts = [tea, office];
  assert.deepEqual(filterFacts(facts, ''), facts);
  assert.deepEqual(filterFacts(facts, '   '), facts);
  assert.deepEqual(filterFacts(facts, 'teh'), [tea]);
  assert.deepEqual(filterFacts(facts, 'OFFICE'), [office]);
  assert.deepEqual(filterFacts(facts, 'bangsar works'), [office]);
  assert.deepEqual(filterFacts(facts, 'tea bangsar'), []);
});

test('the learned line: "Learned 8 Nov · from a conversation" with a link only for a known conversation', () => {
  const now = new Date(2026, 10, 15);
  const local = new Date(2026, 10, 8, 12).toISOString();
  assert.equal(learnedDate(local, now), '8 Nov');
  assert.equal(learnedDate(new Date(2025, 2, 3, 12).toISOString(), now), '3 Mar 2025');
  assert.equal(learnedDate('not a date', now), null);
  assert.equal(learnedDate(null, now), null);
  assert.equal(learnedText(fact({ created_at: local, source_conversation_id: CONVERSATION }), now), 'Learned 8 Nov · from a conversation');
  assert.equal(learnedText(fact({ created_at: local }), now), 'Learned 8 Nov');
  assert.deepEqual(learnedLine(fact({ created_at: local, source_conversation_id: CONVERSATION }), now),
    { learned: 'Learned 8 Nov', source: 'from a conversation', conversationId: CONVERSATION });
  assert.equal(sourceConversation(fact({ source_conversation_id: 'temp' })), null);
  assert.equal(sourceConversation(fact({ source_conversation_id: CONVERSATION })), CONVERSATION);
});

test('sensitivity chips for personal and sensitive facts only', () => {
  assert.equal(sensitivityChip(fact()), null);
  assert.deepEqual(sensitivityChip(fact({ sensitivity: 'personal' })), { label: 'Personal', tone: 'idle' });
  assert.deepEqual(sensitivityChip(fact({ sensitivity: 'sensitive' })), { label: 'Sensitive', tone: 'warn' });
});

test('edit validation follows the core: subject 1–120, text 1–1000, a known kind', () => {
  const ok = validateEdit({ subject: '  Tea  ', text: 'Likes   teh tarik.\n', kind: 'preference' });
  assert.deepEqual(ok, { ok: true, value: { subject: 'Tea', text: 'Likes teh tarik.', kind: 'preference' }, errors: {} });
  const empty = validateEdit({ subject: ' ', text: '', kind: 'preference' });
  assert.equal(empty.ok, false);
  assert.deepEqual(Object.keys(empty.errors).sort(), ['subject', 'text']);
  assert.equal(validateEdit({ subject: 'x'.repeat(121), text: 'ok', kind: 'place' }).errors.subject, 'Keep the subject to 120 characters.');
  assert.equal(validateEdit({ subject: 'x', text: 'y'.repeat(1001), kind: 'place' }).errors.text, 'Keep the fact to 1000 characters.');
  assert.equal(validateEdit({ subject: 'x', text: 'y', kind: 'secret' }).errors.kind, 'Choose a group.');
  assert.deepEqual(editFields(fact()), { subject: 'Tea', text: 'Likes teh tarik.', kind: 'preference' });
});

test('only changed fields are sent; the list updates in place', () => {
  const tea = fact();
  assert.deepEqual(editChanges(tea, { subject: 'Tea', text: 'Likes teh tarik.', kind: 'preference' }), {});
  assert.deepEqual(editChanges(tea, { subject: 'Drinks', text: 'Likes teh tarik.', kind: 'routine' }), { subject: 'Drinks', kind: 'routine' });
  const other = fact({ subject: 'Office' });
  const edited = { ...tea, pinned: true };
  assert.deepEqual(withFact([tea, other], edited), [edited, other]);
  const added = fact({ subject: 'New' });
  assert.deepEqual(withFact([tea], added), [added, tea]);
  assert.deepEqual(withoutFact([tea, other], tea.id), [other]);
});

test('the Remembered notice text, failure messages and counts', () => {
  assert.equal(rememberedText({ text: 'Prefers tea without sugar.' }), 'Remembered: Prefers tea without sugar.');
  for (const bad of [null, {}, { text: '  ' }, { text: 3 }, []]) assert.equal(rememberedText(bad), null);
  assert.equal(memoryFailureMessage({ code: 'memory_secret', message: 'I won’t remember that.' }), 'I won’t remember that.');
  assert.equal(memoryFailureMessage({ code: 'offline' }), 'JARVIS core is offline. Reconnect, then try again.');
  assert.equal(memoryFailureMessage({ code: 'weird', message: 'internal detail' }), 'Memory could not be read or saved. Try again.');
  assert.equal(factCount(1), '1 fact');
  assert.equal(factCount(3), '3 facts');
});
