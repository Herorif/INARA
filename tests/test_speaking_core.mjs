import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import {
  LOCAL_VOICE_CLEARED, localVoicePatch, sanitizeLocalLevel, sanitizeLocalVoice,
} from '../src/features/voice/localVoice.js';
import { registerLocalVoiceEvents } from '../src/services/events/localVoice.js';
import { createSubscriptions } from '../src/services/subscriptions.js';
import {
  ENDED_WORD, SOURCE_LABELS, localCaption, stageView, stageVisible, windowCaption, windowVoiceActive,
} from '../src/app/stageModel.js';
import { createVoiceSlice } from '../src/store/voiceSlice.js';

const require = createRequire(import.meta.url);
const policy = require('../electron/overlay-policy.cjs');
const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8').replace(/\r\n/g, '\n');

const snap = fields => ({
  session: 's1', state: 'listening', user: '', user_final: false, jarvis: '', jarvis_final: false,
  approval: false, end: null, source: 'tray', ...fields,
});
const ended = (kind, fields = {}) => snap({ state: 'ended', end: { kind, message: null }, ...fields });
const offVoice = { state: 'off', mode: null, micOpen: false, playing: false, level: 0, error: '' };
const base = { connected: true, processing: false, voice: offVoice, caption: null, local: null, localEndedAt: null, localLevel: 0, now: 10_000 };
const view = fields => stageView({ ...base, ...fields });

// --- validation -------------------------------------------------------------------------------

test('local_voice validation matches the overlay policy, plus a required source', () => {
  const long = 'x'.repeat(700);
  const corpus = [
    snap(), snap({ state: 'speaking', jarvis: 'Hello' }), snap({ session: null }),
    snap({ user: `a\u0000b\u0007c\td\ne`, jarvis: long, user_final: true }), snap({ user: long }),
    snap({ jarvis: `${'y'.repeat(599)}😀` }), snap({ user: `${'u'.repeat(299)}😀` }),
    ended('quiet'), ended('error', { end: { kind: 'error', message: 'm'.repeat(400) } }), ended('now'),
    snap({ state: 'ended', end: null }), snap({ state: 'listening', end: { kind: 'quiet' } }),
    snap({ state: 'nope' }), snap({ user: 1 }), snap({ jarvis: null }), snap({ approval: 'yes' }),
    snap({ user_final: 1 }), snap({ session: 's'.repeat(129) }), snap({ session: 5 }),
    snap({ end: { kind: 'later', message: null } }), snap({ end: { kind: 'error', message: 5 } }), snap({ end: [] }),
    snap({ extra: 'ignored' }), null, [], 'text', 5,
  ];
  for (const raw of corpus) {
    const expected = policy.sanitizeSnapshot(raw);
    const actual = sanitizeLocalVoice(raw);
    if (expected === null) assert.equal(actual, null, JSON.stringify(raw));
    else assert.deepEqual(actual, { ...expected, source: raw.source }, JSON.stringify(raw));
  }
  assert.equal(sanitizeLocalVoice(snap({ source: 'wake' })).source, 'wake');
  for (const source of [undefined, null, 'window', 'Tray', 1]) assert.equal(sanitizeLocalVoice(snap({ source })), null);
  assert.equal('extra' in sanitizeLocalVoice(snap({ extra: 1 })), false);
});

test('local_voice_level is a finite number clamped to 0..1', () => {
  assert.equal(sanitizeLocalLevel({ level: 0.4 }), 0.4);
  assert.equal(sanitizeLocalLevel({ level: 3 }), 1);
  assert.equal(sanitizeLocalLevel({ level: -1 }), 0);
  for (const raw of [null, [], { level: '0.5' }, { level: NaN }, { level: Infinity }, {}, 0.5]) assert.equal(sanitizeLocalLevel(raw), null);
});

// --- store and subscriptions --------------------------------------------------------------------

function fakeStore() {
  let state = { ...createVoiceSlice() };
  return { getState: () => state, setState: patch => { state = { ...state, ...patch }; } };
}

test('subscriptions keep the latest valid snapshot and level and clear on disconnect', () => {
  const socket = new EventEmitter();
  const scope = createSubscriptions(socket);
  const store = fakeStore();
  let clock = 1000;
  registerLocalVoiceEvents({ onSocket: scope.on, store, unsubs: [], now: () => clock });
  assert.equal(store.getState().localVoice, null);
  socket.emit('local_voice', snap({ user: 'Hey Jarvis, hello' }));
  assert.equal(store.getState().localVoice.user, 'Hey Jarvis, hello');
  socket.emit('local_voice', { ...snap(), state: 'bogus' }); // dropped
  assert.equal(store.getState().localVoice.user, 'Hey Jarvis, hello');
  socket.emit('local_voice_level', { level: 0.7 });
  socket.emit('local_voice_level', { level: 'loud' });
  assert.equal(store.getState().localVoiceLevel, 0.7);
  socket.emit('local_voice', snap({ state: 'speaking' }));
  assert.equal(store.getState().localVoiceLevel, 0.7); // same session: the level stays
  socket.emit('local_voice', ended('quiet'));
  assert.equal(store.getState().localVoiceEndedAt, 1000);
  assert.equal(store.getState().localVoiceLevel, 0);
  clock = 1500;
  socket.emit('local_voice', ended('quiet', { jarvis: 'Bye.' })); // a refresh keeps the first end time
  assert.equal(store.getState().localVoiceEndedAt, 1000);
  socket.emit('local_voice', snap({ session: 's2' }));
  assert.equal(store.getState().localVoiceEndedAt, null);
  socket.emit('local_voice_level', { level: 0.2 });
  socket.emit('disconnect');
  assert.deepEqual(
    { localVoice: store.getState().localVoice, localVoiceLevel: store.getState().localVoiceLevel, localVoiceEndedAt: store.getState().localVoiceEndedAt },
    { ...LOCAL_VOICE_CLEARED },
  );
  scope.dispose();
});

test('a new session resets the level and an end time is per session', () => {
  const first = localVoicePatch(null, null, snap(), 5);
  assert.deepEqual(first, { localVoice: snap(), localVoiceEndedAt: null, localVoiceLevel: 0 });
  assert.equal(localVoicePatch(snap(), null, ended('error'), 9).localVoiceEndedAt, 9);
  assert.equal(localVoicePatch(ended('quiet', { session: 'old' }), 3, ended('quiet'), 9).localVoiceEndedAt, 9);
});

test('the Conversation view registers the subscriptions and reports the stage', () => {
  assert.match(read('src/services/socketSubscriptions.js'), /registerLocalVoiceEvents\(dependencies\);/);
  const source = read('src/app/Conversation.jsx');
  assert.match(source, /useVoiceStageReport\(\);/);
  assert.match(source, /emitSocket\('local_voice_stop', \{\}\)/);
  assert.match(source, /liveVoice\(\)\.stop\(\)/);
  const hook = read('src/app/useVoiceStage.js');
  assert.match(hook, /STAGE_REPORT_DELAY_MS = 250/);
  assert.match(hook, /emitSocket\('voice_stage', \{ visible: false \}\)/);
});

// --- the stage model ----------------------------------------------------------------------------

test('rest: standing by, typed working, offline', () => {
  assert.deepEqual(view({}), {
    mode: 'rest', presence: 'idle', label: 'STANDING BY', source: null, caption: null, level: 0, stop: null, microphone: false, until: null,
  });
  assert.equal(view({ processing: true }).presence, 'working');
  assert.equal(view({ processing: true }).label, 'WORKING');
  assert.equal(view({ connected: false }).presence, 'offline');
  assert.equal(view({ connected: false, local: snap() }).mode, 'rest');
  assert.equal(view({ connected: false, voice: { ...offVoice, micOpen: true } }).mode, 'rest');
});

test('source labels', () => {
  assert.deepEqual(SOURCE_LABELS, { window: 'Window mic', tray: 'Tray voice', wake: 'Hey Jarvis' });
  assert.equal(view({ local: snap() }).source, 'Tray voice');
  assert.equal(view({ local: snap({ source: 'wake' }) }).source, 'Hey Jarvis');
  assert.equal(view({ voice: { ...offVoice, state: 'listening', micOpen: true } }).source, 'Window mic');
});

test('a running local session wins over window voice, which wins over rest', () => {
  const windowOn = { ...offVoice, state: 'speaking', micOpen: true, level: 0.3 };
  const both = view({ voice: windowOn, local: snap({ state: 'thinking' }), localLevel: 0.9, processing: true });
  assert.equal(both.mode, 'voice');
  assert.equal(both.stop, 'local');
  assert.equal(both.label, 'THINKING');
  assert.equal(both.level, 0.9);
  const windowOnly = view({ voice: windowOn, processing: true });
  assert.equal(windowOnly.stop, 'window');
  assert.equal(windowOnly.level, 0.3);
  assert.equal(windowOnly.presence, 'speaking');
  for (const state of ['connecting', 'listening', 'thinking', 'working', 'speaking']) {
    assert.equal(windowVoiceActive({ ...offVoice, state }), true, state);
    assert.equal(view({ voice: { ...offVoice, state } }).label, state.toUpperCase());
  }
  assert.equal(windowVoiceActive({ ...offVoice, state: 'idle' }), false); // push-to-talk, not held
  assert.equal(windowVoiceActive({ ...offVoice, state: 'idle', micOpen: true }), true);
  assert.equal(view({ voice: { ...offVoice, state: 'idle', micOpen: true } }).label, 'LISTENING');
  assert.equal(view({ voice: { ...offVoice, state: 'off' } }).mode, 'rest');
});

test('presence follows the voice state', () => {
  const presence = state => view({ local: snap({ state }) }).presence;
  assert.equal(presence('connecting'), 'working');
  assert.equal(presence('listening'), 'listening');
  assert.equal(presence('thinking'), 'working');
  assert.equal(presence('working'), 'working');
  assert.equal(presence('speaking'), 'speaking');
  assert.equal(view({ local: snap({ state: 'connecting' }) }).label, 'CONNECTING');
});

test('local captions: the owner quoted while talking, dimmed after; waiting words; JARVIS while speaking', () => {
  const caption = fields => view({ local: snap(fields) }).caption;
  assert.equal(caption({}), null); // listening, nothing said yet
  assert.equal(caption({ state: 'connecting' }), null);
  assert.deepEqual(caption({ user: 'Hey Jarvis, what is on today?' }), { text: '“What is on today?”', tone: 'primary' });
  assert.equal(caption({ user: 'Hey Jarvis' }), null); // only the wake phrase
  assert.deepEqual(caption({ user: 'What is on today?', user_final: true }), { text: '“What is on today?”', tone: 'secondary' });
  assert.deepEqual(caption({ user: 'What is on?', state: 'thinking' }), { text: 'Thinking…', tone: 'tertiary' });
  assert.deepEqual(caption({ user: 'What is on?', state: 'working' }), { text: 'Working on it…', tone: 'tertiary' });
  assert.deepEqual(caption({ user: 'What is on?', state: 'speaking', jarvis: 'Two meetings.' }), { text: 'Two meetings.', tone: 'primary' });
  assert.deepEqual(caption({ user: 'What is on?', state: 'listening', jarvis: 'Two meetings.' }), { text: 'Two meetings.', tone: 'secondary' });
  assert.deepEqual(localCaption(snap({ user: 'hi' })), { text: '“hi”', tone: 'primary' });
});

test('window captions: the newest caption of the turn, owner while listening, JARVIS while speaking', () => {
  const you = { sender: 'You', text: ' Plan my day ', captionKey: 's:user:0' };
  const jarvis = { sender: 'JARVIS', text: 'Here is the plan.', captionKey: 's:jarvis:0' };
  const listening = { ...offVoice, state: 'listening', micOpen: true };
  const speaking = { ...offVoice, state: 'speaking', micOpen: true };
  assert.deepEqual(view({ voice: listening, caption: you }).caption, { text: '“Plan my day”', tone: 'primary' });
  assert.deepEqual(view({ voice: speaking, caption: jarvis }).caption, { text: 'Here is the plan.', tone: 'primary' });
  assert.equal(view({ voice: speaking, caption: you }).caption, null);
  assert.equal(view({ voice: listening, caption: jarvis }).caption, null);
  assert.equal(view({ voice: listening, caption: { sender: 'You', text: 'typed' } }).caption, null); // not a caption
  assert.equal(windowCaption({ ...you, text: '  ' }, 'listening'), null);
  assert.equal(windowCaption(null, 'listening'), null);
  // While JARVIS prepares its answer: the tray voice placeholders.
  assert.deepEqual(view({ voice: { ...offVoice, state: 'thinking' }, caption: you }).caption, { text: 'Thinking…', tone: 'tertiary' });
  assert.deepEqual(view({ voice: { ...offVoice, state: 'working' } }).caption, { text: 'Working on it…', tone: 'tertiary' });
});

test('microphone on: tray voice while it runs, window voice while the microphone is open', () => {
  assert.equal(view({ local: snap({ state: 'thinking' }) }).microphone, true);
  assert.equal(view({ voice: { ...offVoice, state: 'thinking' } }).microphone, false);
  assert.equal(view({ voice: { ...offVoice, state: 'listening', micOpen: true } }).microphone, true);
  assert.equal(view({}).microphone, false);
});

test('after a quiet end the last words hold for 4 s in the secondary tone', () => {
  const local = ended('quiet', { user: 'Bye', jarvis: 'Goodbye.' });
  const held = view({ local, localEndedAt: 1000, now: 1000 });
  assert.equal(held.mode, 'voice');
  assert.equal(held.label, ENDED_WORD);
  assert.equal(held.stop, null);
  assert.equal(held.microphone, false);
  assert.equal(held.until, 5000);
  assert.deepEqual(held.caption, { text: 'Goodbye.', tone: 'secondary' });
  assert.equal(view({ local, localEndedAt: 1000, now: 4999 }).mode, 'voice');
  assert.equal(view({ local, localEndedAt: 1000, now: 5000 }).mode, 'rest');
  assert.equal(view({ local, localEndedAt: null, now: 1000 }).mode, 'rest'); // no end time: no hold
});

test('an error end holds its message for 8 s in warn; a now end rests at once', () => {
  const local = ended('error', { user: 'Hello', end: { kind: 'error', message: 'The microphone was disconnected. Voice is off.' } });
  const held = view({ local, localEndedAt: 0, now: 7999 });
  assert.deepEqual(held.caption, { text: 'The microphone was disconnected. Voice is off.', tone: 'warn' });
  assert.equal(held.until, 8000);
  assert.equal(view({ local, localEndedAt: 0, now: 8000 }).mode, 'rest');
  assert.equal(view({ local: ended('now', { user: 'pin' }), localEndedAt: 0, now: 0 }).mode, 'rest');
});

test('a new session during the hold takes over', () => {
  const previous = ended('quiet', { jarvis: 'Goodbye.' });
  const windowOn = { ...offVoice, state: 'listening', micOpen: true };
  assert.equal(view({ local: previous, localEndedAt: 0, now: 100, voice: windowOn }).stop, 'window');
  const next = view({ local: snap({ session: 's2', source: 'wake' }), localEndedAt: null, now: 100 });
  assert.equal(next.stop, 'local');
  assert.equal(next.source, 'Hey Jarvis');
  assert.equal(next.until, null);
});

test('the stage counts as visible only when mounted, visible, focused and unlocked', () => {
  const all = { mounted: true, documentVisible: true, focused: true, locked: false };
  assert.equal(stageVisible(all), true);
  for (const key of ['mounted', 'documentVisible', 'focused']) assert.equal(stageVisible({ ...all, [key]: false }), false, key);
  assert.equal(stageVisible({ ...all, locked: true }), false);
});

test('the empty conversation shows the hero core and the new copy', () => {
  const source = read('src/app/Conversation.jsx');
  assert.match(source, /<PresenceRing className="conversation-hero-core" size=\{CORE_HERO\}/);
  assert.match(source, /const CORE_REST = 64, CORE_VOICE = 112, CORE_HERO = 150;/);
  assert.match(source, /<p>Say “Hey Jarvis”, hold the mic, or type below\.<\/p>/);
  assert.doesNotMatch(source, /Ask a question, plan your day, or hand over a task\./);
  assert.match(source, /<span>Stop talking<\/span>/);
});

test('the inspector keeps its presence panel unless told otherwise', () => {
  const source = read('src/app/WorkspaceInspector.jsx');
  assert.match(source, /showPresence = true \}\) \{/);
  assert.match(source, /\{showPresence && <section className="inspector-panel inspector-presence/);
});
