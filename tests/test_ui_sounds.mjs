import test from 'node:test';
import assert from 'node:assert/strict';
import {
  CUES, CUE_DESIGNS, CUE_MAX_MS, GAP_MS, MASTER_CEILING, SETTLE_MS, SOUND_DEFAULTS, THINKING_EVERY_MS,
  approvalCue, briefingNoticeKey, createCueScheduler, createNoticeTracker, cueLength, cuePeak, localVoiceCue,
  muteReason, panelCue, soundChoice, thinkingActive, vipNoticeKey, voiceCue, volumeGain,
} from '../src/services/sound/uiSoundsModel.js';
import { createUiSoundEngine } from '../src/services/sound/uiSounds.js';
import { registerSoundEvents } from '../src/services/events/sound.js';
import {
  THINKING_HELP, percentVolume, switchPatch, volumePatch, volumePercent,
} from '../src/features/settings/soundSettingsModel.js';

const clock = (start = 10_000) => { let t = start; return { now: () => t, advance: ms => { t += ms; } }; };
const ON = { enabled: true, volume: 0.5, thinking: true };

test('eight cues, one timbre family, all short and well below clipping', () => {
  assert.deepEqual([...CUES].sort(), Object.keys(CUE_DESIGNS).sort());
  assert.equal(CUES.length, 8);
  for (const cue of CUES) {
    assert.ok(cueLength(cue) > 0 && cueLength(cue) <= CUE_MAX_MS, `${cue} is ${cueLength(cue)} ms`);
    assert.ok(cuePeak(cue) < 0.5, `${cue} peak ${cuePeak(cue)}`);
    for (const note of CUE_DESIGNS[cue]) assert.ok(note.attack >= 1 && note.attack < note.ms);
  }
  assert.ok(cuePeak('thinking') < cuePeak('listen'), 'thinking is the quietest');
  const [wake1, wake2] = CUE_DESIGNS.wake; assert.ok(wake2.hz > wake1.hz, 'wake rises');
  const [up1, up2] = CUE_DESIGNS.confirm; assert.ok(up2.hz > up1.hz, 'confirm goes up');
  const [down1, down2] = CUE_DESIGNS.deny; assert.ok(down2.hz < down1.hz && down1.hz < up1.hz, 'deny goes down, lower');
  assert.ok(CUE_DESIGNS.panelOpen[0].to > CUE_DESIGNS.panelOpen[0].hz);
  assert.ok(CUE_DESIGNS.panelClose[0].to < CUE_DESIGNS.panelClose[0].hz);
});

test('settings read with defaults and volume maps to a squared master gain', () => {
  assert.deepEqual(SOUND_DEFAULTS, { enabled: true, volume: 0.5, thinking: false });
  for (const bad of [null, undefined, 'x', [], { volume: 2 }, { volume: -1 }, { volume: '0.5' }, { volume: NaN }, { enabled: 'no' }]) {
    assert.deepEqual(soundChoice(bad), { ...SOUND_DEFAULTS });
  }
  assert.deepEqual(soundChoice({ enabled: false, volume: 0.257, thinking: true }), { enabled: false, volume: 0.26, thinking: true });
  assert.equal(volumeGain(0), 0);
  assert.equal(volumeGain(1), MASTER_CEILING);
  assert.equal(volumeGain(0.5), MASTER_CEILING / 4);
  assert.equal(volumeGain(3), MASTER_CEILING);
  assert.equal(volumeGain('loud'), volumeGain(0.5));
  assert.ok(volumeGain(0.25) < volumeGain(0.5) && volumeGain(0.5) < volumeGain(0.75));
});

test('mute rules: off, gaming, calls, a known system mute and zero volume', () => {
  assert.equal(muteReason(ON), null);
  assert.equal(muteReason({ ...ON, enabled: false }), 'off');
  assert.equal(muteReason({ ...ON, gaming: true }), 'gaming');
  assert.equal(muteReason({ ...ON, onCall: true }), 'call');
  assert.equal(muteReason({ ...ON, systemMuted: true }), 'system');
  assert.equal(muteReason({ ...ON, systemMuted: null }), null, 'an unknown system mute does not silence');
  assert.equal(muteReason({ ...ON, volume: 0 }), 'volume');
  assert.equal(muteReason({ ...ON, enabled: false, gaming: true }), 'off');
  const time = clock();
  const scheduler = createCueScheduler({ now: time.now });
  assert.deepEqual(scheduler.decide('confirm', { ...ON, gaming: true }), { play: false, reason: 'gaming' });
  assert.deepEqual(scheduler.decide('confirm', { ...ON, onCall: true }), { play: false, reason: 'call' });
  assert.deepEqual(scheduler.decide('confirm', { ...ON, onCall: true }, { sample: true }), { play: false, reason: 'call' }, 'the sample keeps mute rules');
  assert.deepEqual(scheduler.decide('nope', ON), { play: false, reason: 'unknown' });
});

test('never two cues inside 80 ms: the newer one cuts the older', () => {
  const time = clock();
  const scheduler = createCueScheduler({ now: time.now });
  assert.deepEqual(scheduler.decide('wake', ON), { play: true, cut: false });
  time.advance(GAP_MS - 1);
  assert.deepEqual(scheduler.decide('listen', ON), { play: true, cut: true });
  time.advance(GAP_MS);
  assert.deepEqual(scheduler.decide('confirm', ON), { play: true, cut: false });
});

test('thinking: only when switched on, at most every 4 s, and it never interrupts', () => {
  const time = clock();
  const scheduler = createCueScheduler({ now: time.now });
  assert.deepEqual(scheduler.decide('thinking', { ...ON, thinking: false }), { play: false, reason: 'thinking_off' });
  assert.deepEqual(scheduler.decide('thinking', ON), { play: true, cut: false });
  time.advance(THINKING_EVERY_MS - 1);
  assert.deepEqual(scheduler.decide('thinking', ON), { play: false, reason: 'rate' });
  time.advance(1);
  scheduler.decide('confirm', ON);
  time.advance(10);
  assert.deepEqual(scheduler.decide('thinking', ON), { play: false, reason: 'busy' });
  time.advance(GAP_MS);
  assert.deepEqual(scheduler.decide('thinking', ON), { play: true, cut: false });
});

test('settling (start-up, reconnect) is silent, except the Preferences sample', () => {
  const time = clock();
  const scheduler = createCueScheduler({ now: time.now });
  scheduler.settle();
  assert.deepEqual(scheduler.decide('notify', ON), { play: false, reason: 'settling' });
  assert.deepEqual(scheduler.decide('confirm', ON, { sample: true }), { play: true, cut: false });
  time.advance(SETTLE_MS);
  assert.equal(scheduler.decide('notify', ON).play, true);
});

test('cue selection per event', () => {
  // Renderer voice: a session starting, then listening inside it.
  assert.equal(voiceCue({ state: 'off' }, { state: 'connecting' }), null);
  assert.equal(voiceCue({ state: 'connecting' }, { state: 'idle' }), 'wake');
  assert.equal(voiceCue({ state: 'connecting' }, { state: 'listening' }), 'wake');
  assert.equal(voiceCue({ state: 'idle' }, { state: 'listening' }), 'listen');
  assert.equal(voiceCue({ state: 'speaking' }, { state: 'listening' }), 'listen');
  assert.equal(voiceCue({ state: 'listening' }, { state: 'listening', level: 0.3 }), null);
  assert.equal(voiceCue({ state: 'listening' }, { state: 'thinking' }), null);
  assert.equal(voiceCue({ state: 'thinking' }, { state: 'off' }), null);
  // Tray voice and "Hey Jarvis".
  const snap = (session, state, source = 'wake') => ({ session, state, source });
  assert.equal(localVoiceCue(null, snap('a', 'connecting')), 'wake');
  assert.equal(localVoiceCue(null, snap('a', 'listening', 'tray')), 'wake');
  assert.equal(localVoiceCue(null, snap('a', 'speaking')), null, 'a session already speaking is a restore');
  assert.equal(localVoiceCue(null, snap('a', 'connecting', 'briefing')), null, 'the briefing card announces itself');
  assert.equal(localVoiceCue(snap('a', 'connecting'), snap('a', 'listening')), null, 'wake already covers it');
  assert.equal(localVoiceCue(snap('a', 'speaking'), snap('a', 'listening')), 'listen');
  assert.equal(localVoiceCue(snap('a', 'listening'), snap('a', 'thinking')), null);
  assert.equal(localVoiceCue(snap('a', 'speaking'), snap('b', 'connecting')), 'wake');
  assert.equal(localVoiceCue(snap('a', 'speaking'), snap('a', 'ended')), null);
  assert.equal(localVoiceCue(snap('a', 'speaking'), null), null);
  // Thinking.
  assert.equal(thinkingActive({ state: 'thinking' }, null), true);
  assert.equal(thinkingActive({ state: 'idle' }, { state: 'working' }), true);
  assert.equal(thinkingActive({ state: 'speaking' }, { state: 'listening' }), false);
  // Approvals and panels.
  assert.equal(approvalCue(true), 'confirm');
  assert.equal(approvalCue(false), 'deny');
  assert.equal(panelCue(undefined, true), 'panelOpen');
  assert.equal(panelCue(false, true), 'panelOpen');
  assert.equal(panelCue(true, true), null);
  assert.equal(panelCue(true, false), 'panelClose');
  assert.equal(panelCue(undefined, false), null);
  // Notifications sound once per card.
  const notices = createNoticeTracker(2);
  assert.equal(notices.fresh(vipNoticeKey({ recordId: 'r1' })), true);
  assert.equal(notices.fresh(vipNoticeKey({ recordId: 'r1' })), false);
  assert.equal(notices.fresh(vipNoticeKey(null)), false);
  assert.equal(notices.fresh(briefingNoticeKey({ date: '2026-11-15' })), true);
  assert.equal(briefingNoticeKey({}), null);
});

// --- The thin WebAudio engine against a fake context (never a real audio device) ---------

function fakeAudio() {
  const created = [];
  const param = () => ({ value: 1, setValueAtTime() {}, linearRampToValueAtTime() {}, exponentialRampToValueAtTime() {}, cancelScheduledValues() {} });
  const node = extra => ({ connect() {}, disconnect() {}, gain: param(), ...extra });
  class FakeContext {
    constructor() { this.state = 'suspended'; this.currentTime = 0; this.sampleRate = 8000; this.resumed = 0; this.closed = false; this.oscillators = []; created.push(this); }
    resume() { this.resumed += 1; this.state = 'running'; return Promise.resolve(); }
    close() { this.closed = true; return Promise.resolve(); }
    createGain() { return node(); }
    createConvolver() { return node({ buffer: null }); }
    createBuffer(channels, length) { const data = Array.from({ length: channels }, () => new Float32Array(length)); return { getChannelData: i => data[i] }; }
    createOscillator() { const osc = node({ type: '', frequency: param(), start() {}, stop() {}, onended: null }); this.oscillators.push(osc); return osc; }
    get destination() { return node(); }
  }
  const listeners = {};
  const target = () => ({
    addEventListener(name, fn) { (listeners[name] ||= []).push(fn); },
    removeEventListener(name, fn) { listeners[name] = (listeners[name] || []).filter(item => item !== fn); },
  });
  const win = target();
  const doc = { ...target(), hidden: false };
  const fire = name => (listeners[name] || []).slice().forEach(fn => fn());
  return { FakeContext, created, win, doc, fire };
}

test('the engine makes no AudioContext before a user gesture, then one, and closes it when hidden and idle', async () => {
  const fake = fakeAudio();
  const time = clock();
  const engine = createUiSoundEngine({ AudioContext: fake.FakeContext, win: fake.win, doc: fake.doc, now: time.now, idleCloseMs: 5 });
  engine.start();
  time.advance(SETTLE_MS);
  assert.equal(engine.play('confirm'), false);
  assert.equal(fake.created.length, 0, 'no context before a gesture');
  fake.fire('pointerdown');
  assert.equal(engine.play('confirm'), true);
  assert.equal(fake.created.length, 1);
  assert.equal(fake.created[0].resumed, 1);
  assert.equal(fake.created[0].oscillators.length, CUE_DESIGNS.confirm.length * 2, 'a sine and a triangle per note');
  time.advance(GAP_MS);
  assert.equal(engine.play('deny'), true);
  assert.equal(fake.created.length, 1, 'one context is reused');
  engine.setContext({ gaming: true });
  time.advance(GAP_MS);
  assert.equal(engine.play('confirm'), false, 'gaming mode is silent');
  engine.setContext({ gaming: false });
  engine.setSettings({ enabled: false });
  assert.equal(engine.play('confirm'), false, 'the switch is off');
  engine.setSettings({ enabled: true });
  fake.doc.hidden = true;
  fake.fire('visibilitychange');
  time.advance(10);
  await new Promise(resolve => setTimeout(resolve, 30));
  assert.equal(fake.created[0].closed, true, 'closed after the idle time while hidden');
  engine.dispose();
});

test('the store bridge sounds each event once and settles on reconnect and unlock', () => {
  const played = [];
  let settled = 0;
  const engine = { start() {}, settle() { settled += 1; }, setSettings(value) { this.settings = value; }, play(cue) { played.push(cue); return true; } };
  let state = { voice: { state: 'off' }, localVoice: null, callAlerts: { alert: { recordId: 'old' } }, briefing: null };
  const subscribers = [];
  const store = { getState: () => state, subscribe(fn) { subscribers.push(fn); return () => subscribers.splice(subscribers.indexOf(fn), 1); } };
  const set = patch => { const previous = state; state = { ...state, ...patch }; subscribers.forEach(fn => fn(state, previous)); };
  const handlers = {};
  const onSocket = (name, fn) => { handlers[name] = fn; return () => {}; };
  const stop = registerSoundEvents({ onSocket, store, unsubs: [], engine, every: 100000 });
  handlers.settings({ sound: { enabled: false, volume: 0.3 } });
  assert.deepEqual(engine.settings, { enabled: false, volume: 0.3, thinking: false });
  handlers.connect();
  handlers.auth_status({ authenticated: true });
  assert.equal(settled, 2);
  set({ voice: { state: 'connecting' } });
  set({ voice: { state: 'idle' } });
  set({ voice: { state: 'listening' } });
  set({ voice: { state: 'thinking' } });
  set({ callAlerts: { alert: { recordId: 'old' } } });
  set({ callAlerts: { alert: { recordId: 'new' } } });
  set({ callAlerts: { alert: null } });
  set({ callAlerts: { alert: { recordId: 'new' } } });
  set({ briefing: { date: '2026-11-15' } });
  set({ briefing: null });
  set({ briefing: { date: '2026-11-15' } });
  assert.deepEqual(played, ['wake', 'listen', 'thinking', 'notify', 'notify']);
  stop();
  set({ voice: { state: 'off' } });
  set({ voice: { state: 'idle' } });
  assert.equal(played.length, 5, 'stopped');
});

test('Preferences: slider percent and patches', () => {
  assert.equal(THINKING_HELP, 'A very quiet pulse while JARVIS works.');
  assert.equal(volumePercent(0.5), 50);
  assert.equal(volumePercent(0.257), 26);
  assert.equal(volumePercent(7), 100);
  assert.equal(percentVolume(29), 0.29);
  assert.equal(percentVolume('abc'), null);
  assert.equal(percentVolume(140), 1);
  const choice = soundChoice({});
  assert.deepEqual(switchPatch(choice, 'enabled', false), { sound: { enabled: false } });
  assert.equal(switchPatch(choice, 'enabled', true), null);
  assert.deepEqual(switchPatch(choice, 'thinking', true), { sound: { thinking: true } });
  assert.equal(switchPatch(choice, 'volume', 1), null);
  assert.deepEqual(volumePatch(choice, 80), { sound: { volume: 0.8 } });
  assert.equal(volumePatch(choice, 50), null);
});
