import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import {
  FADE_MS, HOLD_MS, RESUME_MIN_MS, initialOverlay, nextDeadline, overlayReducer, overlayView,
  ringState, snapshotView, stripWake,
} from '../src/overlay/overlayModel.js';

const require = createRequire(import.meta.url);
const policy = require('../electron/overlay-policy.cjs');

const snap = fields => ({
  session: 's1', state: 'listening', user: '', user_final: false, jarvis: '', jarvis_final: false,
  approval: false, end: null, ...fields,
});
const ended = (kind, fields = {}) => snap({ state: 'ended', end: { kind, message: null }, ...fields });
const run = (actions, state = initialOverlay) => actions.reduce(overlayReducer, state);
const at = (snapshot, now) => ({ type: 'snapshot', snapshot, now });

// --- snapshot → view

test('the ring follows the session state', () => {
  assert.equal(ringState('connecting'), 'working');
  assert.equal(ringState('thinking'), 'working');
  assert.equal(ringState('working'), 'working');
  assert.equal(ringState('listening'), 'listening');
  assert.equal(ringState('speaking'), 'speaking');
  assert.equal(ringState('ended'), 'offline');
});

test('connecting and listening with no words show their status in text-3', () => {
  assert.deepEqual(snapshotView(snap({ state: 'connecting' })).top, { text: 'Connecting\u2026', tone: 'tertiary' });
  assert.deepEqual(snapshotView(snap({ state: 'connecting', user: 'hello' })).top, { text: 'Connecting\u2026', tone: 'tertiary' });
  const listening = snapshotView(snap());
  assert.deepEqual(listening.top, { text: 'Listening', tone: 'tertiary' });
  assert.equal(listening.main, null);
  assert.equal(listening.showStop, true);
  assert.equal(listening.showOpen, false);
});

test('the owner\'s words are quoted: text-1 while speaking, text-2 when final, text-3 once JARVIS answers', () => {
  assert.deepEqual(snapshotView(snap({ user: 'what is the time' })).top, { text: '\u201cwhat is the time\u201d', tone: 'primary' });
  assert.deepEqual(snapshotView(snap({ state: 'thinking', user: 'what is the time', user_final: true })).top, { text: '\u201cwhat is the time\u201d', tone: 'secondary' });
  assert.deepEqual(snapshotView(snap({ state: 'speaking', user: 'what is the time', user_final: true, jarvis: 'It is ten.' })).top, { text: '\u201cwhat is the time\u201d', tone: 'tertiary' });
  // Not final but JARVIS words showing still dims to text-3.
  assert.equal(snapshotView(snap({ user: 'x', jarvis: 'y' })).top.tone, 'tertiary');
});

test('"Hey Jarvis" is stripped and the next letter capitalised; nothing left reads as Listening', () => {
  assert.equal(stripWake('Hey Jarvis, what\'s the weather'), 'What\'s the weather');
  assert.equal(stripWake('hey jarvis. open the door'), 'Open the door');
  assert.equal(stripWake('HEY JARVIS!  turn it off'), 'Turn it off');
  assert.equal(stripWake('Hey, Jarvis, hi'), 'Hi');
  assert.equal(stripWake('  hey jarvis  '), '');
  assert.equal(stripWake('Hey Jarvis,'), '');
  assert.equal(stripWake('hey jarvisx do it'), 'hey jarvisx do it');
  assert.equal(stripWake('tell hey jarvis'), 'tell hey jarvis');
  assert.equal(stripWake('lowercase stays'), 'lowercase stays');
  assert.deepEqual(snapshotView(snap({ user: 'Hey Jarvis,' })).top, { text: 'Listening', tone: 'tertiary' });
  assert.equal(snapshotView(snap({ user: 'hey jarvis what time is it' })).top.text, '\u201cWhat time is it\u201d');
});

test('the main slot: thinking and working placeholders only until JARVIS has words', () => {
  assert.deepEqual(snapshotView(snap({ state: 'thinking', user: 'a', user_final: true })).main, { text: 'Thinking\u2026', tone: 'tertiary' });
  assert.deepEqual(snapshotView(snap({ state: 'working', user: 'a', user_final: true })).main, { text: 'Working on it\u2026', tone: 'tertiary' });
  assert.deepEqual(snapshotView(snap({ state: 'working', jarvis: 'Checking.' })).main, { text: 'Checking.', tone: 'secondary' });
  assert.deepEqual(snapshotView(snap({ state: 'speaking', jarvis: 'It is ten.' })).main, { text: 'It is ten.', tone: 'primary' });
  // Back to listening after an answer: the answer stays in text-2 until a new exchange clears it.
  assert.deepEqual(snapshotView(snap({ state: 'listening', user: 'a', user_final: true, jarvis: 'It is ten.', jarvis_final: true })).main, { text: 'It is ten.', tone: 'secondary' });
  assert.equal(snapshotView(snap({ state: 'listening', user: 'next', jarvis: '' })).main, null);
  assert.equal(snapshotView(snap({ state: 'speaking' })).main, null);
});

test('approval shows Open JARVIS beside Stop', () => {
  const view = snapshotView(snap({ state: 'speaking', jarvis: 'Needs approval.', approval: true }));
  assert.equal(view.showStop, true);
  assert.equal(view.showOpen, true);
});

test('ended quiet: Voice is off, the last answer in text-2, Open JARVIS, no Stop', () => {
  const view = snapshotView(ended('quiet', { user: 'a', jarvis: 'Done.' }));
  assert.deepEqual(view.top, { text: 'Voice is off', tone: 'tertiary' });
  assert.deepEqual(view.main, { text: 'Done.', tone: 'secondary' });
  assert.equal(view.showStop, false);
  assert.equal(view.showOpen, true);
  assert.equal(view.ring, 'offline');
  assert.equal(snapshotView(ended('quiet')).main, null);
});

test('ended error: no top line, the message in warn', () => {
  const view = snapshotView(snap({ state: 'ended', jarvis: 'old', end: { kind: 'error', message: 'Voice stopped: the microphone is busy.' } }));
  assert.equal(view.top, null);
  assert.deepEqual(view.main, { text: 'Voice stopped: the microphone is busy.', tone: 'warn' });
  assert.equal(view.showStop, false);
  assert.equal(view.showOpen, false);
});

test('ended now clears all text and buttons', () => {
  const view = snapshotView(snap({ state: 'ended', user: 'a', jarvis: 'b', approval: true, end: { kind: 'now', message: 'x' } }));
  assert.deepEqual([view.top, view.main, view.showStop, view.showOpen, view.endKind], [null, null, false, false, 'now']);
});

// --- close timing

test('quiet holds 4 s, then fades for 180 ms, then closes', () => {
  let state = run([at(snap(), 0), at(ended('quiet'), 1000)]);
  assert.equal(state.phase, 'hold');
  assert.equal(nextDeadline(state), 1000 + HOLD_MS.quiet);
  assert.equal(HOLD_MS.quiet, 4000);
  state = overlayReducer(state, { type: 'tick', now: 4999 });
  assert.equal(state.phase, 'hold');
  assert.equal(overlayView(state).visible, true);
  state = overlayReducer(state, { type: 'tick', now: 5000 });
  assert.equal(state.phase, 'fading');
  assert.equal(overlayView(state).visible, false);
  assert.equal(nextDeadline(state), 5000 + FADE_MS);
  state = overlayReducer(state, { type: 'tick', now: 5000 + FADE_MS });
  assert.equal(state.phase, 'closed');
  assert.equal(nextDeadline(state), null);
});

test('error holds 8 s', () => {
  const state = run([at(snap(), 0), at(ended('error'), 0)]);
  assert.equal(HOLD_MS.error, 8000);
  assert.equal(nextDeadline(state), 8000);
  assert.equal(overlayReducer(state, { type: 'tick', now: 7999 }).phase, 'hold');
  assert.equal(overlayReducer(state, { type: 'tick', now: 8000 }).phase, 'fading');
});

test('now fades at once with the text already cleared', () => {
  const state = run([at(snap({ user: 'a', jarvis: 'b' }), 0), at(ended('now', { user: 'a', jarvis: 'b' }), 10)]);
  assert.equal(state.phase, 'fading');
  const view = overlayView(state);
  assert.deepEqual([view.top, view.main, view.visible], [null, null, false]);
  assert.equal(overlayReducer(state, { type: 'tick', now: 10 + FADE_MS }).phase, 'closed');
});

test('the pointer pauses the countdown; leaving resumes it with at least 2 s left', () => {
  let state = run([at(snap(), 0), at(ended('quiet'), 0), { type: 'pointer', inside: true, now: 1000 }]);
  assert.equal(nextDeadline(state), null);
  assert.equal(state.remaining, 3000);
  state = overlayReducer(state, { type: 'tick', now: 60000 });
  assert.equal(state.phase, 'hold');
  state = overlayReducer(state, { type: 'pointer', inside: false, now: 60000 });
  assert.equal(nextDeadline(state), 63000);
  // Little time left: leaving still gives 2 s.
  state = run([{ type: 'pointer', inside: true, now: 62500 }, { type: 'pointer', inside: false, now: 70000 }], state);
  assert.equal(nextDeadline(state), 70000 + RESUME_MIN_MS);
});

test('a pointer already over the panel when the session ends starts the hold paused', () => {
  let state = run([at(snap(), 0), { type: 'pointer', inside: true, now: 0 }, at(ended('error'), 100)]);
  assert.equal(state.phase, 'hold');
  assert.equal(nextDeadline(state), null);
  state = overlayReducer(state, { type: 'pointer', inside: false, now: 500 });
  assert.equal(nextDeadline(state), 500 + HOLD_MS.error);
});

test('a new running session cancels the hold or the fade and shows the panel', () => {
  const holding = run([at(snap(), 0), at(ended('quiet'), 0)]);
  const reopened = overlayReducer(holding, at(snap({ session: 's2', state: 'connecting' }), 1000));
  assert.equal(reopened.phase, 'open');
  assert.equal(nextDeadline(reopened), null);
  assert.equal(overlayView(reopened).visible, true);
  assert.equal(overlayView(reopened).top.text, 'Connecting\u2026');
  const fading = overlayReducer(holding, { type: 'tick', now: 4000 });
  assert.equal(fading.phase, 'fading');
  assert.equal(overlayReducer(fading, at(snap({ session: 's3' }), 4050)).phase, 'open');
  // The same session, or another ended one, does not cancel.
  assert.equal(overlayReducer(holding, at(snap({ session: 's1' }), 100)).phase, 'hold');
  assert.equal(overlayReducer(holding, at(ended('quiet', { session: 's9' }), 100)).phase, 'hold');
  assert.equal(overlayReducer(fading, at(snap({ session: 's1', jarvis: 'changed' }), 4100)).snapshot.jarvis, '');
});

test('Open JARVIS after the end fades at once; before the end it changes nothing', () => {
  const holding = run([at(snap(), 0), at(ended('quiet'), 0)]);
  assert.equal(overlayReducer(holding, { type: 'open', now: 200 }).phase, 'fading');
  const running = run([at(snap({ approval: true }), 0)]);
  assert.equal(overlayReducer(running, { type: 'open', now: 200 }), running);
});

test('closed ignores everything and nothing shows before the first snapshot', () => {
  assert.equal(overlayView(initialOverlay).visible, false);
  const closed = run([at(snap(), 0), at(ended('now'), 0), { type: 'tick', now: FADE_MS }]);
  assert.equal(closed.phase, 'closed');
  assert.equal(overlayReducer(closed, at(snap({ session: 'other' }), 500)), closed);
});

// --- bounds

test('bounds: centred on a normal work area, bottom edge on the work area bottom', () => {
  assert.deepEqual(policy.overlayBounds({ x: 0, y: 0, width: 1920, height: 1040 }), { x: 656, y: 884, width: 608, height: 156 });
  assert.deepEqual(policy.overlayBounds({ x: 0, y: 0, width: 1365, height: 720 }), { x: 379, y: 564, width: 608, height: 156 });
  assert.deepEqual(policy.overlayBounds({ x: 0, y: 0, width: 640, height: 480 }), { x: 16, y: 324, width: 608, height: 156 });
});

test('bounds: narrow work areas use their width minus 32', () => {
  assert.deepEqual(policy.overlayBounds({ x: 0, y: 0, width: 639, height: 900 }), { x: 16, y: 744, width: 607, height: 156 });
  assert.deepEqual(policy.overlayBounds({ x: 100, y: 50, width: 400, height: 800 }), { x: 116, y: 694, width: 368, height: 156 });
});

test('bounds: offset displays (left, above, taskbar on top)', () => {
  assert.deepEqual(policy.overlayBounds({ x: -1920, y: 0, width: 1920, height: 1040 }), { x: -1264, y: 884, width: 608, height: 156 });
  assert.deepEqual(policy.overlayBounds({ x: 1920, y: -1080, width: 2560, height: 1400 }), { x: 2896, y: 164, width: 608, height: 156 });
  assert.deepEqual(policy.overlayBounds({ x: 0, y: 48, width: 1920, height: 1032 }), { x: 656, y: 924, width: 608, height: 156 });
  assert.throws(() => policy.overlayBounds({ x: 0, y: 0, width: 0, height: 10 }));
  assert.throws(() => policy.overlayBounds(null));
});

// --- bootstrap validation

const TOKEN = 'a'.repeat(64);
const CLIENT = '123e4567-e89b-42d3-a456-426614174000';
const PROFILE = process.platform === 'win32' ? 'C:\\Users\\x\\overlay' : '/home/x/overlay';
const boot = fields => ({ token: TOKEN, clientId: CLIENT, profile: PROFILE, core: 'http://127.0.0.1:8000', dev: false, ...fields });

test('a valid bootstrap keeps only the known fields', () => {
  const result = policy.validateBootstrap(boot({ extra: 'dropped' }));
  assert.equal(result.ok, true);
  assert.deepEqual(result.value, { token: TOKEN, clientId: CLIENT, profile: PROFILE, core: 'http://127.0.0.1:8000', dev: false });
  assert.equal(policy.validateBootstrap(boot({ core: 'http://localhost:51234/' })).value.core, 'http://localhost:51234');
  assert.equal(policy.validateBootstrap(boot({ dev: undefined })).value.dev, false);
});

test('bad bootstraps fail with one line that never contains the token', () => {
  const secret = 'b'.repeat(64);
  const bad = [
    boot({ token: 'A'.repeat(64) }), boot({ token: 'a'.repeat(63) }), boot({ token: 7 }), boot({ token: undefined }),
    boot({ clientId: 'not-a-uuid' }), boot({ clientId: null }),
    boot({ profile: 'relative/dir' }), boot({ profile: 5 }),
    boot({ core: 'https://127.0.0.1:8000' }), boot({ core: 'http://127.0.0.1' }), boot({ core: 'http://192.168.1.2:8000' }),
    boot({ core: 'http://example.com:8000' }), boot({ core: 'ws://127.0.0.1:8000' }), boot({ core: 'http://127.0.0.1:8000/path' }),
    boot({ core: 'http://user@127.0.0.1:8000' }), boot({ core: 'http://127.0.0.1:8000?x=1' }), boot({ core: 'http://127.0.0.1.evil.com:8000' }),
    boot({ core: ' http://127.0.0.1:8000' }), boot({ core: 'http://[::1]:8000' }), boot({ core: 8000 }),
    boot({ dev: 'true' }), null, [], 'string',
  ];
  for (const value of bad) {
    const result = policy.validateBootstrap(value && typeof value === 'object' && !Array.isArray(value) ? { ...value, token: value.token === TOKEN ? secret : value.token } : value);
    assert.equal(result.ok, false, JSON.stringify(value));
    assert.match(result.error, /^Invalid overlay bootstrap: [^\n]+$/);
    assert.equal(result.error.includes(secret), false);
  }
  assert.equal(policy.parseBootstrap('{not json').ok, false);
  assert.equal(policy.parseBootstrap(JSON.stringify(boot({}))).ok, true);
  const leaked = policy.parseBootstrap(JSON.stringify(boot({ token: secret, core: 'http://evil:1' })));
  assert.equal(leaked.ok, false);
  assert.equal(leaked.error.includes(secret), false);
});

// --- payload validation

test('a valid snapshot passes with unknown fields dropped', () => {
  const clean = policy.sanitizeSnapshot({ ...snap({ user: 'hi' }), extra: '<b>x</b>', token: TOKEN });
  assert.deepEqual(clean, snap({ user: 'hi' }));
  assert.deepEqual(policy.sanitizeSnapshot(snap({ session: null })).session, null);
  const end = policy.sanitizeSnapshot(ended('error', { end: { kind: 'error', message: 'Busy', extra: 1 } }));
  assert.deepEqual(end.end, { kind: 'error', message: 'Busy' });
});

test('wrong types and unknown enums drop the snapshot', () => {
  const bad = [
    null, [], 'x', snap({ state: 'sleeping' }), snap({ state: 3 }), snap({ session: 5 }), snap({ session: 'x'.repeat(129) }),
    snap({ user: null }), snap({ jarvis: 4 }), snap({ user_final: 'no' }), snap({ jarvis_final: 1 }), snap({ approval: null }),
    snap({ end: { kind: 'later', message: null } }), snap({ end: 'quiet' }), snap({ end: { kind: 'error', message: 5 } }),
    snap({ end: [] }),
  ];
  for (const value of bad) assert.equal(policy.sanitizeSnapshot(value), null, JSON.stringify(value));
  const { approval: _drop, ...missing } = snap();
  assert.equal(policy.sanitizeSnapshot(missing), null);
});

test('over-long text is truncated: owner words keep the start, JARVIS keeps the newest end', () => {
  const clean = policy.sanitizeSnapshot(snap({ user: 'u'.repeat(400) + 'END', jarvis: 'START' + 'j'.repeat(700) + 'tail', end: null }));
  assert.equal(clean.user.length, 300);
  assert.equal(clean.user, 'u'.repeat(300));
  assert.equal(clean.jarvis.length, 600);
  assert.ok(clean.jarvis.endsWith('tail'));
  const message = policy.sanitizeSnapshot(ended('error', { end: { kind: 'error', message: 'm'.repeat(1000) } }));
  assert.equal(message.end.message.length, 300);
  // Never split a surrogate pair; control characters are removed.
  const emoji = policy.sanitizeSnapshot(snap({ user: 'a'.repeat(299) + '\u{1F600}' }));
  assert.equal(emoji.user, 'a'.repeat(299));
  assert.equal(policy.sanitizeSnapshot(snap({ user: 'a\u0000b\u001bc\nd' })).user, 'abc\nd');
});

test('state and end agree after validation', () => {
  assert.deepEqual(policy.sanitizeSnapshot(snap({ state: 'ended', end: null })).end, { kind: 'quiet', message: null });
  assert.equal(policy.sanitizeSnapshot(snap({ state: 'speaking', end: { kind: 'now', message: null } })).state, 'ended');
});

test('levels are clamped to 0..1 and anything else is dropped', () => {
  assert.deepEqual(policy.sanitizeLevel({ level: 0.4, extra: 1 }), { level: 0.4 });
  assert.deepEqual(policy.sanitizeLevel({ level: 3 }), { level: 1 });
  assert.deepEqual(policy.sanitizeLevel({ level: -2 }), { level: 0 });
  for (const value of [null, 0.5, { level: '0.5' }, { level: NaN }, { level: Infinity }, {}, []]) assert.equal(policy.sanitizeLevel(value), null);
});
