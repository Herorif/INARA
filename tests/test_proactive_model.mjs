// S7.2 proactive engine UI (docs/PROACTIVE.md): the card group, the digest, "Told you", the
// Preferences patches and the talking overlay's card (model and policy).
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import {
  CARD_LIMIT, GROUP_MS, QUIET_SAME, TIME_FORMAT, cardGroupView, channelLabel, chattinessPatch, chattyHelp,
  covers, digestGroups, dismissCard, dropMuted, emptyCards, kindLabel, muteLabel, muteRequest, normalizeItem,
  proactiveChoice, quietHoursPatch, quietSwitchPatch, receiveCard, receiveDigest, toldRows, workspaceFocused,
} from '../src/features/proactive/proactiveModel.js';
import { HOLD_MS, cardLabel, initialOverlay, overlayReducer, overlayView, snapshotView } from '../src/overlay/overlayModel.js';

const require = createRequire(import.meta.url);
const policy = require('../electron/overlay-policy.cjs');

const hex = n => n.toString(16).padStart(32, '0');
const card = (n, fields = {}) => ({
  id: hex(n), kind: 'calendar.soon', source: 'calendar', person_id: null, title: `Event ${n}`,
  body: 'Starts at 15:00', urgency: 1, at: '2026-11-15T06:00:00+00:00', ...fields,
});

// --- items and the card group

test('items are validated: id, title, kind and source are required', () => {
  assert.equal(normalizeItem(card(1)).title, 'Event 1');
  assert.equal(normalizeItem({ ...card(1), id: 'x' }), null);
  assert.equal(normalizeItem({ ...card(1), title: '  ' }), null);
  assert.equal(normalizeItem({ ...card(1), kind: 3 }), null);
  assert.equal(normalizeItem({ ...card(1), urgency: 9 }).urgency, 1);
  assert.equal(normalizeItem({ ...card(1), title: 'x'.repeat(400) }).title.length, 160);
  assert.equal(normalizeItem(null), null);
});

test('cards group within two minutes, newest first, capped, and repeats are ignored', () => {
  let state = emptyCards;
  let result = receiveCard(state, { card: card(1) }, 1000);
  assert.equal(result.fresh, true);
  state = result.state;
  result = receiveCard(state, { card: card(1) }, 2000);
  assert.equal(result.fresh, false);
  state = receiveCard(state, { card: card(2) }, 2000).state;
  assert.deepEqual(state.items.map(item => item.title), ['Event 2', 'Event 1']);
  for (let n = 3; n < 10; n += 1) state = receiveCard(state, { card: card(n) }, 3000).state;
  assert.equal(state.items.length, CARD_LIMIT);
  // Later than GROUP_MS after the last card: a fresh group.
  state = receiveCard(state, { card: card(20) }, 3000 + GROUP_MS).state;
  assert.deepEqual(state.items.map(item => item.title), ['Event 20']);
  assert.equal(receiveCard(state, { card: { id: 'bad' } }, 0).fresh, false);
});

test('the group view: label, three entries and how many more', () => {
  assert.equal(cardGroupView(emptyCards), null);
  let state = receiveCard(emptyCards, { card: card(1) }, 0).state;
  assert.equal(cardGroupView(state).label, 'JARVIS · CALENDAR');
  for (let n = 2; n <= 5; n += 1) state = receiveCard(state, { card: card(n) }, 0).state;
  const view = cardGroupView(state);
  assert.equal(view.label, 'JARVIS · 5 NEW');
  assert.equal(view.entries.length, 3);
  assert.equal(view.more, 2);
  assert.equal(view.entries[0].kindText, 'Calendar');
  assert.equal(dismissCard(state, hex(5)).items.length, 4);
  assert.equal(dismissCard(state, hex(99)), state);
});

test('a mute drops every card it covers (kind + source + person)', () => {
  let state = receiveCard(emptyCards, { card: card(1) }, 0).state;
  state = receiveCard(state, { card: card(2, { kind: 'call.missed', source: 'calls', person_id: 'p1' }) }, 0).state;
  state = receiveCard(state, { card: card(3, { kind: 'call.missed', source: 'calls' }) }, 0).state;
  const rule = { id: hex(7), kind: 'call.missed', source: 'calls', person_id: 'p1' };
  assert.deepEqual(dropMuted(state, rule).items.map(item => item.title), ['Event 3', 'Event 1']);
  assert.deepEqual(muteRequest(normalizeItem(card(2, { person_id: 'p1' }))), { kind: 'calendar.soon', source: 'calendar', person_id: 'p1' });
  assert.deepEqual(muteRequest(normalizeItem(card(1))), { kind: 'calendar.soon', source: 'calendar' });
  assert.equal(covers({ kind: 'calendar.soon', source: 'calendar', person_id: null }, normalizeItem(card(1))), true);
});

// --- the digest

test('the digest is validated and grouped by kind in order of the newest item', () => {
  assert.equal(receiveDigest({ digest: null }), null);
  assert.equal(receiveDigest({ digest: { items: [] } }), null);
  const digest = receiveDigest({ digest: { items: [
    card(3, { kind: 'weather.rain_soon', source: 'weather', title: 'Rain soon', reason: 'away' }),
    card(2), card(1), { id: 'junk' },
  ] } });
  assert.equal(digest.items.length, 3);
  assert.equal(digest.items[0].reason, 'away');
  assert.deepEqual(digestGroups(digest).map(group => [group.label, group.items.length]), [['Weather', 1], ['Calendar', 2]]);
});

// --- Told you

test('"Told you" rows carry labels and whether a mute covers them', () => {
  const rows = toldRows([normalizeItem({ ...card(1), channel: 'spoken' }), normalizeItem({ ...card(2, { source: 'other' }), channel: 'phone' })],
    [{ id: hex(9), kind: 'calendar.soon', source: 'calendar', person_id: null }]);
  assert.deepEqual(rows.map(row => [row.channelText, row.muted]), [['Said aloud', true], ['Phone call', false]]);
  assert.equal(kindLabel('homelab.alert'), 'Homelab');
  assert.equal(kindLabel('nope'), 'JARVIS');
  assert.equal(channelLabel('digest'), 'While you were away');
  assert.equal(muteLabel({ kind: 'call.missed', source: 'calls', person_id: 'p1' }), 'Calls · from calls · one person');
});

// --- Preferences

test('the saved chattiness and quiet hours with the core’s defaults', () => {
  assert.deepEqual(proactiveChoice(undefined), { chattiness: 'balanced', quiet_hours: { start: '22:30', end: '07:00' } });
  assert.deepEqual(proactiveChoice({ chattiness: 'loud', quiet_hours: { start: '7:00', end: 'x' } }), proactiveChoice({}));
  assert.equal(proactiveChoice({ quiet_hours: null }).quiet_hours, null);
  assert.deepEqual(proactiveChoice({ chattiness: 'quiet', quiet_hours: { start: '23:00', end: '06:00' } }),
    { chattiness: 'quiet', quiet_hours: { start: '23:00', end: '06:00' } });
  assert.match(chattyHelp('quiet'), /30 minutes/);
  assert.match(chattyHelp('chatty'), /5 minutes/);
});

test('the Preferences patches', () => {
  const choice = proactiveChoice({});
  assert.deepEqual(chattinessPatch(choice, 'chatty'), { assistant: { chattiness: 'chatty' } });
  assert.equal(chattinessPatch(choice, 'balanced'), null);
  assert.equal(chattinessPatch(choice, 'loud'), null);
  assert.deepEqual(quietSwitchPatch(choice, false), { assistant: { quiet_hours: null } });
  assert.equal(quietSwitchPatch(choice, true), null);
  assert.deepEqual(quietSwitchPatch(proactiveChoice({ quiet_hours: null }), true), { assistant: { quiet_hours: { start: '22:30', end: '07:00' } } });
  assert.deepEqual(quietHoursPatch(choice, '23:00', '07:00'), { patch: { assistant: { quiet_hours: { start: '23:00', end: '07:00' } } } });
  assert.deepEqual(quietHoursPatch(choice, '22:30', '07:00'), {});
  assert.deepEqual(quietHoursPatch(choice, '25:00', '07:00'), { error: TIME_FORMAT });
  assert.deepEqual(quietHoursPatch(choice, '07:00', '07:00'), { error: QUIET_SAME });
});

test('the workspace counts as focused only when connected, visible, focused and unlocked', () => {
  assert.equal(workspaceFocused({ connected: true, documentVisible: true, focused: true, locked: false }), true);
  assert.equal(workspaceFocused({ connected: true, documentVisible: true, focused: false, locked: false }), false);
  assert.equal(workspaceFocused({ connected: true, documentVisible: false, focused: true, locked: false }), false);
  assert.equal(workspaceFocused({ connected: true, documentVisible: true, focused: true, locked: true }), false);
  assert.equal(workspaceFocused({ connected: false, documentVisible: true, focused: true, locked: false }), false);
});

// --- the talking overlay's card

const overlayCard = (n, fields = {}) => ({
  session: `card:${hex(n)}`, state: 'ended', user: '', user_final: true, jarvis: '', jarvis_final: true,
  approval: false, design: false, end: { kind: 'quiet', message: null },
  card: { id: hex(n), kind: 'calendar.soon', title: `Event ${n}`, body: 'Starts at 15:00', count: 1, sound: { enabled: true, volume: 0.5 }, ...fields },
});

test('the overlay policy passes a valid card on an ended snapshot only', () => {
  const clean = policy.sanitizeSnapshot(overlayCard(1));
  assert.deepEqual(clean.card, { id: hex(1), kind: 'calendar.soon', title: 'Event 1', body: 'Starts at 15:00', count: 1, sound: { enabled: true, volume: 0.5 } });
  assert.equal(policy.sanitizeSnapshot(overlayCard(1, { id: 'x' })), null);
  assert.equal(policy.sanitizeSnapshot(overlayCard(1, { title: '   ' })), null);
  assert.equal(policy.sanitizeSnapshot(overlayCard(1, { count: 0 })), null);
  assert.equal(policy.sanitizeSnapshot({ ...overlayCard(1), state: 'listening', end: null }), null);
  assert.equal(policy.sanitizeSnapshot(overlayCard(1, { count: 500 })).card.count, 99);
  assert.equal(policy.sanitizeSnapshot(overlayCard(1, { sound: 'loud' })).card.sound.enabled, false);
  const plain = policy.sanitizeSnapshot({ ...overlayCard(1), card: undefined });
  assert.equal('card' in plain, false);
});

test('the overlay shows a card with Open JARVIS, holds it 8 s, and a newer card replaces it', () => {
  const view = snapshotView(overlayCard(1));
  assert.deepEqual(view.top, { text: 'New from JARVIS', tone: 'tertiary' });
  assert.deepEqual(view.main, { text: 'Event 1 — Starts at 15:00', tone: 'primary' });
  assert.equal(view.showOpen, true);
  assert.equal(view.showStop, false);
  assert.equal(view.endKind, 'card');
  assert.equal(cardLabel(3), '3 new from JARVIS');
  assert.equal(snapshotView(overlayCard(1, { body: '' })).main.text, 'Event 1');
  let state = overlayReducer(initialOverlay, { type: 'snapshot', snapshot: overlayCard(1), now: 0 });
  assert.equal(state.phase, 'hold');
  assert.equal(state.deadline, HOLD_MS.card);
  state = overlayReducer(state, { type: 'snapshot', snapshot: overlayCard(2, { count: 2 }), now: 5000 });
  assert.equal(state.session, `card:${hex(2)}`);
  assert.equal(state.deadline, 5000 + HOLD_MS.card);
  assert.equal(overlayView(state).top.text, '2 new from JARVIS');
  // A voice session that starts takes the panel over.
  state = overlayReducer(state, { type: 'snapshot', snapshot: { ...overlayCard(3), session: 's9', state: 'listening', end: null, card: undefined }, now: 6000 });
  assert.equal(state.phase, 'open');
  assert.equal(overlayView(state).endKind, null);
});
