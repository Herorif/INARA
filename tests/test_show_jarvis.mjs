import test from 'node:test';
import assert from 'node:assert/strict';
import {
  PHOTO_TTL_MS, QUESTION_LIMIT, answerQuestion, askFollowUp, canSend, cancelFollowUp, captureFailure, cleanQuestion,
  discardPhoto, editQuestion, expirePhoto, failQuestion, hasPhoto, initialShow, photoExpiresIn, photoLine, sendQuestion,
  stillSize, streamAnswer, takeStill, validQuestion,
} from '../src/features/vision/showJarvisModel.js';
import { CAPTURE_DEADLINE_MS, createCaptureRequests } from '../src/features/vision/captureRequests.js';
import { askAboutPhoto } from '../src/features/vision/showJarvisClient.js';
import { blobToBase64, captureStill } from '../src/features/vision/still.js';
import { approvalView } from '../src/components/approvalView.js';

const ID = '6f1c2a9e-3b4d-4e5f-8a6b-7c8d9e0f1a2b';
const still = (prefill = '') => takeStill(initialShow, { id: 'photo-1', takenAt: 1000, prefill });

test('camera-on to still: one frozen photo with an empty or prefilled question', () => {
  assert.equal(initialShow.phase, 'camera-on');
  assert.equal(hasPhoto(initialShow), false);
  const state = still();
  assert.deepEqual(state, { phase: 'still', photo: { id: 'photo-1', takenAt: 1000 }, question: '', turns: [], error: '' });
  assert.equal(still('what is this?').question, 'what is this?');
  assert.equal(still('x'.repeat(600)).question.length, QUESTION_LIMIT);
  assert.equal(hasPhoto(state), true);
  assert.equal(takeStill(initialShow, { id: '', takenAt: 1 }), initialShow);
  assert.equal(takeStill(initialShow, { id: 'a', takenAt: Number.NaN }), initialShow);
});

test('questions are cleaned and bounded like the core', () => {
  assert.equal(cleanQuestion('  what\tis\n\nthis\u0000? '), 'what is this ?');
  assert.equal(validQuestion('   '), false);
  assert.equal(validQuestion('x'.repeat(500)), true);
  assert.equal(validQuestion('x'.repeat(501)), false);
  assert.equal(photoLine(' what is this? '), '📷 photo · what is this?');
});

test('send needs a question, a connection and no other reply; then sending, streaming and answered', () => {
  let state = still();
  assert.equal(canSend(state), false);
  state = editQuestion(state, '  what is this?  ');
  assert.equal(canSend(state, { connected: false }), false);
  assert.equal(canSend(state, { busy: true }), false);
  assert.equal(sendQuestion(state, { requestId: 'r1', busy: true }), state);
  state = sendQuestion(state, { requestId: 'r1' });
  assert.equal(state.phase, 'sending');
  assert.equal(state.question, '');
  assert.deepEqual(state.turns, [{ requestId: 'r1', question: 'what is this?', answer: '', status: 'sending' }]);
  assert.equal(editQuestion(state, 'typing'), state); // the field is closed while sending
  state = streamAnswer(state, { requestId: 'r1', text: 'A bra' });
  state = streamAnswer(state, { requestId: 'r1', text: 'A bracket' });
  assert.equal(state.turns[0].answer, 'A bracket');
  assert.equal(streamAnswer(state, { requestId: 'other', text: 'x' }), state);
  state = answerQuestion(state, { requestId: 'r1', text: 'A steel bracket.' });
  assert.equal(state.phase, 'answered');
  assert.deepEqual(state.turns[0], { requestId: 'r1', question: 'what is this?', answer: 'A steel bracket.', status: 'answered' });
  assert.equal(streamAnswer(state, { requestId: 'r1', text: 'late' }), state); // late deltas change nothing
  assert.equal(answerQuestion(state, { requestId: 'r1', text: 'again' }), state);
});

test('follow-ups reuse the same photo; cancel returns to the answer', () => {
  let state = answerQuestion(sendQuestion(editQuestion(still(), 'what is this?'), { requestId: 'r1' }), { requestId: 'r1', text: 'A bracket.' });
  state = askFollowUp(state);
  assert.equal(state.phase, 'follow-up');
  assert.equal(state.photo.id, 'photo-1');
  assert.deepEqual(cancelFollowUp(state).phase, 'answered');
  state = sendQuestion(editQuestion(state, 'what metal?'), { requestId: 'r2' });
  state = answerQuestion(state, { requestId: 'r2', text: 'Steel.' });
  assert.deepEqual(state.turns.map(turn => [turn.question, turn.answer]), [['what is this?', 'A bracket.'], ['what metal?', 'Steel.']]);
  assert.equal(state.photo.id, 'photo-1');
  assert.equal(askFollowUp(still()).phase, 'still'); // only after an answer
});

test('a failed send puts the question back with the reason', () => {
  let state = sendQuestion(editQuestion(still(), 'what is this?'), { requestId: 'r1' });
  state = failQuestion(state, { requestId: 'r1', message: 'Photos can’t be sent in gaming mode.' });
  assert.deepEqual(state, { phase: 'still', photo: { id: 'photo-1', takenAt: 1000 }, question: 'what is this?', turns: [], error: 'Photos can’t be sent in gaming mode.' });
  assert.equal(editQuestion(state, 'what is this??').error, '');
  state = answerQuestion(sendQuestion(state, { requestId: 'r2' }), { requestId: 'r2', text: 'A bracket.' });
  state = sendQuestion(editQuestion(askFollowUp(state), 'more?'), { requestId: 'r3' });
  state = failQuestion(state, { requestId: 'r3', message: '' });
  assert.equal(state.phase, 'follow-up');
  assert.equal(state.question, 'more?');
  assert.equal(state.turns.length, 1);
  assert.match(state.error, /Try again/);
});

test('retake, cancel and take another drop the photo; never mid-send', () => {
  const state = editQuestion(still(), 'q');
  assert.equal(discardPhoto(state), initialShow);
  const sending = sendQuestion(state, { requestId: 'r1' });
  assert.equal(discardPhoto(sending), sending);
  assert.equal(discardPhoto(answerQuestion(sending, { requestId: 'r1', text: 'a' })), initialShow);
  assert.equal(discardPhoto(initialShow), initialShow);
});

test('the photo is dropped after five minutes, but not while a question is on its way', () => {
  const state = still();
  assert.equal(PHOTO_TTL_MS, 300_000);
  assert.equal(photoExpiresIn(state, 1000), PHOTO_TTL_MS);
  assert.equal(photoExpiresIn(initialShow, 1000), null);
  assert.equal(expirePhoto(state, 1000 + PHOTO_TTL_MS - 1), state);
  assert.equal(expirePhoto(state, 1000 + PHOTO_TTL_MS), initialShow);
  const sending = sendQuestion(editQuestion(state, 'q'), { requestId: 'r1' });
  assert.equal(expirePhoto(sending, 1000 + PHOTO_TTL_MS * 2), sending);
  const answered = answerQuestion(sending, { requestId: 'r1', text: 'a' });
  assert.equal(expirePhoto(answered, 1000 + PHOTO_TTL_MS), initialShow);
});

test('stills are at most 1280 px wide and never upscaled', () => {
  assert.deepEqual(stillSize(1920, 1080), { width: 1280, height: 720 });
  assert.deepEqual(stillSize(640, 480), { width: 640, height: 480 });
  assert.equal(stillSize(0, 480), null);
});

test('voice capture failures map to the core’s error codes', () => {
  assert.equal(captureFailure({ phase: 'failed', error: 'NotAllowedError' }), 'denied');
  assert.equal(captureFailure({ phase: 'failed', error: 'NotReadableError' }), 'busy');
  assert.equal(captureFailure({ phase: 'failed', error: 'NotFoundError' }), 'unavailable');
  assert.equal(captureFailure({ phase: 'paused', reason: 'hidden' }), 'hidden');
  assert.equal(captureFailure({ phase: 'paused', reason: 'minimized' }), 'hidden');
  assert.equal(captureFailure({ phase: 'paused', reason: 'locked' }), 'locked');
  assert.equal(captureFailure({ phase: 'lost' }), 'unavailable');
  assert.equal(captureFailure({ phase: 'idle' }), 'failed');
});

function fakeStore(initial = {}) {
  let state = { isLockScreenVisible: false, ...initial };
  return { getState: () => state, setState: patch => { state = { ...state, ...(typeof patch === 'function' ? patch(state) : patch) }; } };
}
function fakeTimers() {
  const pending = new Map();
  let next = 0;
  return { set: (fn, ms) => { pending.set(++next, { fn, ms }); return next; }, clear: id => pending.delete(id), fire: () => { for (const [id, item] of [...pending]) { pending.delete(id); item.fn(); } }, pending };
}

test('a capture request opens the studio and is answered exactly once', () => {
  const replies = [], store = fakeStore(), timers = fakeTimers();
  const requests = createCaptureRequests({ store, timers, reply: (id, result) => replies.push([id, result]) });
  const job = requests.request({ request_id: ID, question: 'what is this?' });
  assert.equal(store.getState().visionCapture, job);
  assert.equal(store.getState().visionFocus, ID);
  assert.equal(job.question, 'what is this?');
  assert.equal(job.settle({ image: 'AAAA' }), true);
  assert.equal(job.settle({ image: 'BBBB' }), false);
  assert.deepEqual(replies, [[ID, { image: 'AAAA' }]]);
  assert.equal(store.getState().visionCapture, null);
  assert.equal(timers.pending.size, 0);
});

test('capture requests: busy, locked, hidden, invalid, deadline and disconnect', () => {
  const replies = [], store = fakeStore(), timers = fakeTimers();
  let hidden = false;
  const requests = createCaptureRequests({ store, timers, hidden: () => hidden, reply: (id, result) => replies.push([id, result]) });
  assert.equal(requests.request({ request_id: 'nope' }), null);
  assert.equal(requests.request(null), null);
  const job = requests.request({ request_id: ID, question: 'q' });
  const other = '0f1c2a9e-3b4d-4e5f-8a6b-7c8d9e0f1a2b';
  requests.request({ request_id: other });
  assert.deepEqual(replies.at(-1), [other, { error: 'busy' }]);
  assert.equal(timers.pending.get(1).ms, CAPTURE_DEADLINE_MS);
  assert.ok(CAPTURE_DEADLINE_MS < 20_000);
  timers.fire();
  assert.deepEqual(replies.at(-1), [ID, { error: 'failed' }]);
  assert.equal(job.settle({ image: 'late' }), false);
  job.settle({ error: 'anything' });
  store.setState({ isLockScreenVisible: true });
  requests.request({ request_id: other });
  assert.deepEqual(replies.at(-1), [other, { error: 'locked' }]);
  store.setState({ isLockScreenVisible: false });
  hidden = true;
  requests.request({ request_id: other });
  assert.deepEqual(replies.at(-1), [other, { error: 'hidden' }]);
  hidden = false;
  const unknown = requests.request({ request_id: other });
  unknown.settle({ error: 'weird' });
  assert.deepEqual(replies.at(-1), [other, { error: 'failed' }]);
  const dropped = requests.request({ request_id: ID });
  const count = replies.length;
  requests.drop();
  assert.equal(replies.length, count);
  assert.equal(store.getState().visionCapture, null);
  assert.equal(dropped.settle({ image: 'x' }), false);
  assert.equal(timers.pending.size, 0);
});

test('asking about a photo adds the text line to the chat and returns the answer', async () => {
  const messages = [];
  const store = fakeStore({ backendConnected: true, textProcessing: false, conversationRestoring: false, conversationId: 'c1', addMessage: (sender, text) => messages.push([sender, text]) });
  const sent = [];
  const socket = { connected: true, emit: (event, data, ack) => { sent.push([event, data]); setTimeout(() => ack({ ok: true, text: 'A bracket.' }), 1); } };
  const result = await askAboutPhoto({ socket, store, question: 'what is this?', image: 'BASE64', requestId: 'r1' });
  assert.deepEqual(result, { ok: true, text: 'A bracket.' });
  assert.deepEqual(messages, [['You', '📷 photo · what is this?']]);
  assert.deepEqual(sent, [['vision_ask', { conversation_id: 'c1', request_id: 'r1', question: 'what is this?', image: 'BASE64' }]]);
  assert.equal(store.getState().pendingTextRequest, 'r1');
  assert.equal(store.getState().textProcessing, true);
});

test('asking refuses offline or busy, and reports core failures and timeouts', async () => {
  const base = { backendConnected: true, textProcessing: false, conversationRestoring: false, conversationId: 'c1', addMessage() {} };
  const quiet = { connected: true, emit() {} };
  assert.equal((await askAboutPhoto({ socket: quiet, store: fakeStore({ ...base, backendConnected: false }), question: 'q', image: 'x', requestId: 'r' })).code, 'offline');
  assert.equal((await askAboutPhoto({ socket: quiet, store: fakeStore({ ...base, textProcessing: true }), question: 'q', image: 'x', requestId: 'r' })).code, 'busy');
  const failing = { connected: true, emit: (_e, _d, ack) => ack({ ok: false, code: 'gaming_mode', message: 'Photos can’t be sent in gaming mode.' }) };
  assert.deepEqual(await askAboutPhoto({ socket: failing, store: fakeStore(base), question: 'q', image: 'x', requestId: 'r' }),
    { ok: false, code: 'gaming_mode', message: 'Photos can’t be sent in gaming mode.' });
  assert.equal((await askAboutPhoto({ socket: quiet, store: fakeStore(base), question: 'q', image: 'x', requestId: 'r', timeout: 5 })).code, 'timeout');
});

test('a still is one JPEG at most 1280 px wide at quality 0.85, and the canvas is released', async () => {
  const calls = [];
  const canvas = { width: 0, height: 0, getContext: () => ({ drawImage: (...args) => calls.push(['draw', args.slice(1)]) }), toBlob: (done, type, quality) => { calls.push(['blob', type, quality, canvas.width]); done(new Blob([new Uint8Array([0xff, 0xd8, 0xff, 1])], { type })); } };
  const doc = { createElement: name => (name === 'canvas' ? canvas : null) };
  const video = { readyState: 4, videoWidth: 1920, videoHeight: 1080 };
  const blob = await captureStill(video, { doc });
  assert.deepEqual(calls, [['draw', [0, 0, 1280, 720]], ['blob', 'image/jpeg', 0.85, 1280]]);
  assert.equal(canvas.width, 0);
  assert.equal(await blobToBase64(blob), Buffer.from([0xff, 0xd8, 0xff, 1]).toString('base64'));
  await assert.rejects(captureStill({ readyState: 1, videoWidth: 640, videoHeight: 480 }, { doc }));
});

test('the voice approval card reads as approved in the design', () => {
  assert.deepEqual(approvalView({ id: 'a', tool: 'look_through_camera', args: { question: 'what is this?' } }), {
    kind: 'camera_look', title: 'Look through your camera?',
    summary: 'JARVIS wants to look through your camera. It takes one still photo to answer you, then the camera turns off again.',
    approveLabel: 'Allow once', denyLabel: 'Not now', details: null,
  });
});

test('the default deadline timer calls setTimeout unbound, as browsers require', () => {
  const original = { set: globalThis.setTimeout, clear: globalThis.clearTimeout };
  const calls = [];
  globalThis.setTimeout = function (run, ms) { if (this !== undefined && this !== globalThis) throw new TypeError('Illegal invocation'); calls.push(ms); return 7; };
  globalThis.clearTimeout = function (id) { if (this !== undefined && this !== globalThis) throw new TypeError('Illegal invocation'); calls.push(`clear ${id}`); };
  try {
    const replies = [];
    const requests = createCaptureRequests({ store: fakeStore(), reply: (id, result) => replies.push([id, result]) });
    const job = requests.request({ request_id: ID, question: 'q' });
    job.settle({ image: 'AAAA' });
    assert.deepEqual(calls, [CAPTURE_DEADLINE_MS, 'clear 7']);
    assert.deepEqual(replies, [[ID, { image: 'AAAA' }]]);
  } finally {
    globalThis.setTimeout = original.set;
    globalThis.clearTimeout = original.clear;
  }
});
