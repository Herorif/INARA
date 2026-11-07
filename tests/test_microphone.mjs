import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import {
  AUTOMATIC, LEGACY_KEY, automaticDeviceName, browserDeviceFor, captureDecision, cleanLabel, defaultInputKey,
  labelsMatch, legacyChoice, legacyNeedsLookup, levelFromSamples, normalizeLabel, smoothLevel,
} from '../src/features/voice/microphoneModel.js';
import { adoptLegacyMicrophone, resetLegacyAdoption } from '../src/features/voice/legacyMicrophone.js';
import { BLOCKED_HELP, LEVEL_HELP, meterTarget, usingText } from '../src/features/settings/microphoneSettingsModel.js';
import { PttCapture } from '../src/features/speech/capture.js';

const WASAPI = 'Windows WASAPI';
const HEADSET = 'Headset Microphone (Poly BT700)';
const DESK = 'Microphone (Yeti Orb)';
const entry = (name, extra = {}) => ({ name, host_api: WASAPI, default: false, channels: 1, sample_rate: 48000, ...extra });
const inputs = [entry(HEADSET, { default: true }), entry(DESK)];
const mic = (deviceId, label, groupId = deviceId) => ({ kind: 'audioinput', deviceId, label, groupId });
// Chromium's list on Windows: the default and communications aliases, then each device.
const browser = (defaultLabel = HEADSET, defaultGroup = 'g-headset') => [
  mic('default', `Default - ${defaultLabel}`, defaultGroup),
  mic('communications', `Communications - ${HEADSET}`, 'g-headset'),
  mic('id-headset', HEADSET, 'g-headset'),
  mic('id-yeti', `${DESK} (b58e:0005)`, 'g-yeti'),
  { kind: 'audiooutput', deviceId: 'out', label: 'Speakers (Realtek(R) Audio)', groupId: 'g-out' },
];

test('labels match the Windows name case-insensitively, whitespace-normalised, without Chromium decoration', () => {
  assert.equal(normalizeLabel('  Microphone   (Yeti  Orb) '), 'microphone (yeti orb)');
  assert.equal(cleanLabel('Default - Headset Microphone (Poly BT700)'), HEADSET);
  assert.equal(cleanLabel('Communications - Headset Microphone (Poly BT700)'), HEADSET);
  assert.equal(cleanLabel('Microphone (Yeti Orb) (b58e:0005)'), DESK);
  assert.equal(labelsMatch(DESK, 'microphone  (YETI orb) (b58e:0005)'), true);
  assert.equal(labelsMatch(DESK, 'Microphone (Yeti Orb 2)'), false);
  assert.equal(labelsMatch('', ''), false);
  assert.equal(labelsMatch('Microphone (Realtek(R) Audio)', 'Microphone (Realtek(R) Audio)'), true);
});

test('Automatic and an unmatched name use the browser default; a named device maps to its deviceId', () => {
  const devices = browser();
  assert.equal(browserDeviceFor(AUTOMATIC, devices), '');
  assert.equal(browserDeviceFor(null, devices), '');
  assert.equal(browserDeviceFor({ name: DESK, host_api: WASAPI }, devices), 'id-yeti');
  assert.equal(browserDeviceFor({ name: HEADSET, host_api: WASAPI }, devices), 'id-headset'); // never the 'default' alias
  assert.equal(browserDeviceFor({ name: 'Old USB mic', host_api: WASAPI }, devices), '');
  assert.equal(browserDeviceFor({ name: DESK, host_api: WASAPI }, []), '');
});

test('"Using:" names the device Automatic uses now, by its Windows name', () => {
  assert.equal(automaticDeviceName(inputs, browser()), HEADSET);
  assert.equal(automaticDeviceName(inputs, browser(`${DESK} (b58e:0005)`, 'g-yeti')), DESK); // the core's spelling
  assert.equal(automaticDeviceName([], browser('USB Mic')), 'USB Mic');
  assert.equal(automaticDeviceName(inputs, [mic('default', '')]), HEADSET); // no labels: the core's default
  assert.equal(automaticDeviceName([], []), '');
  assert.equal(usingText(AUTOMATIC, HEADSET), `Using: ${HEADSET}`);
  assert.equal(usingText({ name: DESK, host_api: WASAPI }, HEADSET), '');
  assert.equal(usingText(AUTOMATIC, ''), '');
  assert.equal(LEVEL_HELP, 'Speak to check. The bar moves when JARVIS hears you.');
  assert.equal(BLOCKED_HELP, "JARVIS can't hear this microphone. Choose another or check Windows sound settings.");
});

test('the level bar reopens for a new device, a new default, or a plugged-in microphone', () => {
  const named = meterTarget({ name: DESK, host_api: WASAPI }, browser());
  assert.equal(named.deviceId, 'id-yeti');
  assert.equal(meterTarget({ name: DESK, host_api: WASAPI }, browser(DESK, 'g-yeti')).restartKey, named.restartKey);
  const automatic = meterTarget(AUTOMATIC, browser());
  assert.equal(automatic.deviceId, '');
  assert.notEqual(meterTarget(AUTOMATIC, browser(DESK, 'g-yeti')).restartKey, automatic.restartKey);
  assert.notEqual(meterTarget(AUTOMATIC, [...browser(), mic('id-usb', 'USB Mic')]).restartKey, automatic.restartKey);
  assert.equal(meterTarget(AUTOMATIC, browser()).restartKey, automatic.restartKey);
});

test('the old window-only choice is adopted once by name, else Automatic stays', () => {
  const devices = browser();
  const desk = { name: DESK, host_api: WASAPI };
  assert.deepEqual(legacyChoice({ storedId: 'id-yeti', saved: AUTOMATIC, devices, inputs }), { choice: desk, done: true });
  // Nothing to adopt: the browser default, an empty value, an unplugged or unlisted device.
  for (const storedId of ['', 'default', 'communications', 'id-gone']) {
    assert.deepEqual(legacyChoice({ storedId, saved: AUTOMATIC, devices, inputs }), { choice: null, done: true }, storedId);
  }
  assert.deepEqual(legacyChoice({ storedId: 'id-yeti', saved: AUTOMATIC, devices, inputs: [entry(HEADSET)] }), { choice: null, done: true });
  // A microphone already chosen in the core is kept.
  assert.deepEqual(legacyChoice({ storedId: 'id-yeti', saved: { name: HEADSET, host_api: WASAPI }, devices, inputs }), { choice: null, done: true });
  // Labels hidden (no permission yet): try again at the next start.
  assert.deepEqual(legacyChoice({ storedId: 'id-yeti', saved: AUTOMATIC, devices: [mic('id-yeti', '')], inputs }), { choice: null, done: false });
  assert.equal(legacyNeedsLookup('id-yeti', AUTOMATIC), true);
  assert.equal(legacyNeedsLookup('', AUTOMATIC), false);
  assert.equal(legacyNeedsLookup('id-yeti', { name: DESK, host_api: WASAPI }), false);
});

class Socket extends EventEmitter {
  connected = true;
  constructor(report) { super(); this.report = report; this.calls = []; }
  emit(event, data, ack) {
    if (typeof ack !== 'function') return super.emit(event, data);
    this.calls.push(event);
    ack(this.report);
    return true;
  }
}
const storage = (values) => ({
  values: { ...values },
  getItem(key) { return key in this.values ? this.values[key] : null; },
  removeItem(key) { delete this.values[key]; },
});
const media = (devices) => ({ enumerateDevices: async () => devices });
const listed = { ok: true, available: true, code: null, message: null, host_api: WASAPI, inputs, outputs: [] };

test('first load adopts the old localStorage choice into the Microphone setting and removes the key', async () => {
  resetLegacyAdoption();
  const store = storage({ [LEGACY_KEY]: 'id-yeti', selectedSpeakerId: 'spk' }), sent = [];
  const socket = new Socket(listed);
  await adoptLegacyMicrophone({ socket, saved: AUTOMATIC, emit: (...args) => sent.push(args), storage: store, media: media(browser()) });
  assert.deepEqual(sent, [['update_settings', { voice: { local_microphone: { name: DESK, host_api: WASAPI } } }]]);
  assert.deepEqual(store.values, { selectedSpeakerId: 'spk' });
  assert.deepEqual(socket.calls, ['audio_devices']);
  // Once per start, and nothing at all without the old key.
  store.values[LEGACY_KEY] = 'id-yeti';
  await adoptLegacyMicrophone({ socket, saved: AUTOMATIC, emit: (...args) => sent.push(args), storage: store, media: media(browser()) });
  assert.equal(sent.length, 1);
});

test('first load with the browser default or a missing device keeps Automatic and removes the key', async () => {
  for (const stored of ['', 'id-gone']) {
    resetLegacyAdoption();
    const store = storage({ [LEGACY_KEY]: stored }), sent = [];
    await adoptLegacyMicrophone({ socket: new Socket(listed), saved: AUTOMATIC, emit: (...args) => sent.push(args), storage: store, media: media(browser()) });
    assert.deepEqual(sent, [], stored);
    assert.deepEqual(store.values, {}, stored);
  }
  resetLegacyAdoption();
  const quiet = storage({}), sent = [];
  const socket = new Socket(listed);
  await adoptLegacyMicrophone({ socket, saved: AUTOMATIC, emit: (...args) => sent.push(args), storage: quiet, media: media(browser()) });
  assert.deepEqual(socket.calls, []); // no old key: no device list is read
});

test('an unreachable core keeps the old key for the next start', async () => {
  resetLegacyAdoption();
  const store = storage({ [LEGACY_KEY]: 'id-yeti' }), sent = [];
  const socket = new Socket({ ok: false, code: 'forbidden', message: 'Owner only.' });
  await adoptLegacyMicrophone({ socket, saved: AUTOMATIC, emit: (...args) => sent.push(args), storage: store, media: media(browser()) });
  assert.deepEqual(sent, []);
  assert.deepEqual(store.values, { [LEGACY_KEY]: 'id-yeti' });
  resetLegacyAdoption();
});

test('devicechange: Automatic restarts on a new default, a named device only ends when it is gone', () => {
  const before = defaultInputKey(browser());
  assert.equal(captureDecision({ deviceId: '', trackDeviceId: 'default', defaultKey: before, devices: browser() }), 'keep');
  assert.equal(captureDecision({ deviceId: '', trackDeviceId: 'default', defaultKey: before, devices: browser(DESK, 'g-yeti') }), 'restart');
  assert.equal(captureDecision({ deviceId: '', trackDeviceId: 'default', defaultKey: before, devices: [...browser(), mic('id-usb', 'USB Mic')] }), 'keep');
  assert.equal(captureDecision({ deviceId: '', trackDeviceId: 'default', defaultKey: before, devices: [] }), 'lost');
  assert.equal(captureDecision({ deviceId: 'id-yeti', trackDeviceId: 'id-yeti', defaultKey: '', devices: browser(DESK, 'g-yeti') }), 'keep');
  assert.equal(captureDecision({ deviceId: 'id-yeti', trackDeviceId: 'id-yeti', defaultKey: '', devices: browser().filter(item => item.deviceId !== 'id-yeti') }), 'lost');
  // Without Chromium's 'default' alias the first device stands for the default.
  assert.equal(defaultInputKey([mic('a', 'First'), mic('b', 'Second')]), 'a|first');
  assert.equal(defaultInputKey([]), '');
});

test('level smoothing: fast attack, slower release, raw with reduced motion', () => {
  assert.equal(levelFromSamples(new Float32Array(0)), 0);
  assert.equal(levelFromSamples(new Float32Array(64)), 0);
  assert.ok(Math.abs(levelFromSamples(new Float32Array(64).fill(0.1)) - 0.4) < 1e-6);
  assert.equal(levelFromSamples(new Float32Array(64).fill(0.9)), 1);
  const up = smoothLevel(0, 1, 50);
  const down = 1 - smoothLevel(1, 0, 50);
  assert.ok(Math.abs(up - (1 - Math.exp(-1))) < 1e-9, 'attack time constant is 50 ms');
  assert.ok(Math.abs(down - (1 - Math.exp(-0.25))) < 1e-9, 'release time constant is 200 ms');
  assert.ok(up > down * 2);
  assert.ok(smoothLevel(0, 1, 200) > 0.98);
  assert.ok(smoothLevel(1, 0, 800) < 0.02);
  assert.equal(smoothLevel(0.2, 0.7, 16, true), 0.7);
  assert.equal(smoothLevel(0.2, 5, 16, true), 1);
  assert.equal(smoothLevel(0.5, 0.5, 16), 0.5);
  assert.equal(smoothLevel(0.5, 0.1, 0), 0.5);
});

// A fake browser: getUserMedia hands out tracks; the default device can move.
function fakeBrowser() {
  const media = new EventTarget();
  const state = { list: browser(), opened: [], stopped: 0, closed: 0 };
  media.enumerateDevices = async () => state.list;
  media.getUserMedia = async (constraints) => {
    const track = new EventTarget();
    const id = constraints.audio.deviceId?.exact || 'default';
    track.getSettings = () => ({ deviceId: id });
    track.stop = () => state.stopped++;
    const stream = { getAudioTracks: () => [track], getTracks: () => [track] };
    state.opened.push({ id, track, constraints });
    return stream;
  };
  class Node { port = { close() {} }; connect() {} disconnect() {} }
  class Context {
    sampleRate = 16000; state = 'running'; audioWorklet = { addModule: async () => {} }; destination = {};
    constructor() { state.contexts = (state.contexts || 0) + 1; }
    createMediaStreamSource() { return new Node(); }
    createGain() { const node = new Node(); node.gain = { value: 1 }; return node; }
    async resume() {}
    async close() { state.closed++; }
  }
  return { media, state, capture: () => new PttCapture({ media, AudioContext: Context, WorkletNode: Node }) };
}
const settle = () => new Promise(resolve => setTimeout(resolve, 10));

test('an open Automatic capture restarts on a new Windows default and keeps its frames', async () => {
  const { media, state, capture: make } = fakeBrowser();
  const capture = make();
  let failed = 0;
  const frames = [];
  assert.equal(await capture.start({ deviceId: async () => '', onFrame: frame => frames.push(frame), onFailure: () => failed++ }), true);
  assert.equal(state.opened.length, 1);
  assert.equal(state.opened[0].constraints.audio.deviceId, undefined); // the browser's default
  media.dispatchEvent(new Event('devicechange'));
  await settle();
  assert.equal(state.opened.length, 1, 'same default: no restart');
  state.list = browser(DESK, 'g-yeti');
  media.dispatchEvent(new Event('devicechange'));
  await settle();
  assert.equal(state.opened.length, 2, 'reopened on the new default');
  assert.equal(state.stopped, 1);
  assert.equal(state.closed, 1);
  assert.equal(failed, 0);
  capture.node.port.onmessage({ data: new ArrayBuffer(640) });
  assert.equal(frames.length, 1);
  // A second capture still cannot take the microphone while this one owns it.
  await assert.rejects(make().start({ onFrame() {}, onFailure() {} }), /Another microphone/);
  await capture.stop();
  assert.equal(state.stopped, 2);
  const next = make();
  assert.equal(await next.start({ deviceId: '', onFrame() {}, onFailure() {} }), true);
  await next.stop();
});

test('an Automatic capture whose track ends reopens; repeated losses without audio end it', async () => {
  const { state, capture: make } = fakeBrowser();
  const capture = make();
  let failed = 0;
  assert.equal(await capture.start({ deviceId: '', onFrame() {}, onFailure: () => failed++ }), true);
  state.opened.at(-1).track.dispatchEvent(new Event('ended'));
  await settle();
  assert.equal(state.opened.length, 2);
  assert.equal(failed, 0);
  state.opened.at(-1).track.dispatchEvent(new Event('ended'));
  await settle();
  state.opened.at(-1).track.dispatchEvent(new Event('ended'));
  await settle();
  assert.equal(failed, 1, 'gives up after the second reopen in a row');
  assert.equal(capture.stream, null);
  await capture.stop();
});

test('a named capture resolves its deviceId when it opens and is never moved to the default', async () => {
  const { media, state, capture: make } = fakeBrowser();
  const capture = make();
  let failed = 0;
  assert.equal(await capture.start({ deviceId: async () => 'id-yeti', onFrame() {}, onFailure: () => failed++ }), true);
  assert.deepEqual(state.opened[0].constraints.audio.deviceId, { exact: 'id-yeti' });
  state.list = browser(DESK, 'g-yeti');
  media.dispatchEvent(new Event('devicechange'));
  await settle();
  assert.equal(state.opened.length, 1);
  state.list = browser().filter(item => item.deviceId !== 'id-yeti');
  media.dispatchEvent(new Event('devicechange'));
  await settle();
  assert.equal(failed, 1);
  await capture.stop();
});

test('stopping during a restart releases the microphone', async () => {
  const { media, state, capture: make } = fakeBrowser();
  const capture = make();
  assert.equal(await capture.start({ deviceId: '', onFrame() {}, onFailure() {} }), true);
  let grant;
  media.getUserMedia = () => new Promise(resolve => { grant = resolve; });
  state.list = browser(DESK, 'g-yeti');
  media.dispatchEvent(new Event('devicechange'));
  await settle();
  await capture.stop();
  let stopped = 0;
  const track = new EventTarget();
  track.getSettings = () => ({ deviceId: 'default' });
  track.stop = () => stopped++;
  grant({ getAudioTracks: () => [track], getTracks: () => [track] });
  await settle();
  assert.equal(stopped, 1, 'the late stream is released');
  media.getUserMedia = async () => ({ getAudioTracks: () => [track], getTracks: () => [track] });
  const next = make();
  assert.equal(await next.start({ deviceId: '', onFrame() {}, onFailure() {} }), true);
  await next.stop();
});
