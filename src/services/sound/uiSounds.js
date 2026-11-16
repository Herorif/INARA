/*
 * JARVIS interface sounds: the thin WebAudio part (docs/SOUND.md). All decisions and the cue
 * designs live in ./uiSoundsModel.js. Nothing touches audio at module load: the one
 * AudioContext is created after the first user gesture (autoplay rules), resumed when a cue
 * needs it, and closed when the page has been hidden and idle for IDLE_CLOSE_MS.
 */
import {
  CUE_DESIGNS, REVERB_SECONDS, REVERB_SEND, SETTLE_MS, SOUND_DEFAULTS, TRIANGLE_MIX,
  createCueScheduler, cueLength, volumeGain,
} from './uiSoundsModel.js';

export const IDLE_CLOSE_MS = 60000;
const CUT_MS = 15;
const SILENT = 0.0001;
const GESTURES = ['pointerdown', 'keydown'];

/** A short stereo impulse response: decaying noise, generated once per context. */
function impulse(context, seconds = REVERB_SECONDS) {
  const length = Math.max(1, Math.round(context.sampleRate * seconds));
  const buffer = context.createBuffer(2, length, context.sampleRate);
  for (let channel = 0; channel < 2; channel += 1) {
    const data = buffer.getChannelData(channel);
    for (let i = 0; i < length; i += 1) data[i] = (Math.random() * 2 - 1) * (1 - i / length) ** 3 * 0.5;
  }
  return buffer;
}

export function createUiSoundEngine({
  AudioContext = globalThis.AudioContext,
  win = globalThis.window,
  doc = globalThis.document,
  now = () => Date.now(),
  idleCloseMs = IDLE_CLOSE_MS,
  // The talking overlay (never focused, so never a gesture) runs with autoplay allowed.
  unlocked: startUnlocked = false,
} = {}) {
  const scheduler = createCueScheduler({ now });
  let settings = { ...SOUND_DEFAULTS };
  let context = { gaming: false, onCall: false, systemMuted: null };
  let audio = null; // { ctx, master, reverb }
  let current = null; // the sounding cue's bus
  let unlocked = startUnlocked === true;
  let lastPlay = 0;
  let idleTimer = 0;
  let listening = false;

  const state = () => ({ ...settings, ...context });

  const unlock = () => {
    unlocked = true;
    removeGestures();
  };
  const removeGestures = () => {
    if (!listening) return;
    GESTURES.forEach(name => win?.removeEventListener?.(name, unlock, true));
    listening = false;
  };

  function ensureAudio() {
    if (audio) return audio;
    if (typeof AudioContext !== 'function') return null;
    const ctx = new AudioContext({ latencyHint: 'interactive' });
    const master = ctx.createGain();
    master.connect(ctx.destination);
    const reverb = ctx.createConvolver();
    reverb.buffer = impulse(ctx);
    reverb.connect(master);
    audio = { ctx, master, reverb };
    return audio;
  }

  function closeAudio() {
    clearTimeout(idleTimer);
    idleTimer = 0;
    const closing = audio;
    audio = null;
    current = null;
    closing?.ctx.close?.().catch?.(() => {});
  }

  function cut(bus, ctx) {
    if (!bus) return;
    const t = ctx.currentTime;
    try {
      bus.gain.cancelScheduledValues(t);
      bus.gain.setValueAtTime(bus.gain.value, t);
      bus.gain.linearRampToValueAtTime(0, t + CUT_MS / 1000);
    } catch { /* already gone */ }
  }

  function voice(ctx, bus, item, start, type, hz, level) {
    const osc = ctx.createOscillator();
    const env = ctx.createGain();
    osc.type = type;
    const begin = start + item.at / 1000;
    const end = begin + item.ms / 1000;
    osc.frequency.setValueAtTime(hz, begin);
    if (item.to) osc.frequency.exponentialRampToValueAtTime(item.to * (hz / item.hz), end);
    env.gain.setValueAtTime(0, begin);
    env.gain.linearRampToValueAtTime(level, begin + item.attack / 1000);
    env.gain.exponentialRampToValueAtTime(SILENT, end);
    osc.connect(env);
    env.connect(bus);
    osc.start(begin);
    osc.stop(end + 0.02);
    return osc;
  }

  function render(cue, cutPrevious, volume) {
    const sound = ensureAudio();
    if (!sound) return false;
    const { ctx, master, reverb } = sound;
    if (ctx.state === 'suspended') ctx.resume?.().catch?.(() => {});
    if (cutPrevious) cut(current, ctx);
    const start = ctx.currentTime + 0.005;
    master.gain.setValueAtTime(volumeGain(volume), start);
    const bus = ctx.createGain();
    bus.gain.setValueAtTime(1, start);
    bus.connect(master);
    const send = ctx.createGain();
    send.gain.setValueAtTime(REVERB_SEND, start);
    bus.connect(send);
    send.connect(reverb);
    let last = null;
    for (const item of CUE_DESIGNS[cue]) {
      voice(ctx, bus, item, start, 'sine', item.hz, item.gain);
      last = voice(ctx, bus, item, start, 'triangle', item.hz * 2, item.gain * (item.triangle ?? TRIANGLE_MIX));
    }
    current = bus;
    const release = () => setTimeout(() => {
      try { bus.disconnect(); send.disconnect(); } catch { /* closed */ }
      if (current === bus) current = null;
    }, REVERB_SECONDS * 1000 + 50);
    if (last) last.onended = release;
    else release();
    return true;
  }

  function scheduleIdleClose() {
    clearTimeout(idleTimer);
    idleTimer = 0;
    if (!audio || !doc?.hidden) return;
    const wait = Math.max(0, lastPlay + idleCloseMs - now());
    idleTimer = setTimeout(() => {
      if (doc?.hidden && now() - lastPlay >= idleCloseMs) closeAudio();
      else scheduleIdleClose();
    }, wait);
  }

  const visibility = () => (doc?.hidden ? scheduleIdleClose() : clearTimeout(idleTimer));

  return {
    /** Wait for the first gesture before any audio, and settle so restored state is silent. */
    start() {
      scheduler.settle(SETTLE_MS);
      if (!unlocked && !listening && win?.addEventListener) {
        GESTURES.forEach(name => win.addEventListener(name, unlock, true));
        listening = true;
      }
      doc?.addEventListener?.('visibilitychange', visibility);
    },
    /** Reconnect or unlock: state the core re-sends now is a restore. */
    settle(ms = SETTLE_MS) { scheduler.settle(ms); },
    setSettings(next) { settings = { ...SOUND_DEFAULTS, ...next }; },
    setContext(next) { context = { ...context, ...next }; },
    /** Plays one cue if the rules allow; `sample` (Preferences) skips settling, `volume` overrides. */
    play(cue, { sample = false, volume } = {}) {
      if (!unlocked || !CUE_DESIGNS[cue]) return false;
      const level = typeof volume === 'number' ? volume : settings.volume;
      const decision = scheduler.decide(cue, { ...state(), volume: level }, { sample });
      if (!decision.play) return false;
      let played = false;
      try { played = render(cue, decision.cut, level); } catch { played = false; }
      if (played) { lastPlay = now(); scheduleIdleClose(); }
      return played;
    },
    cueLength,
    dispose() {
      removeGestures();
      doc?.removeEventListener?.('visibilitychange', visibility);
      closeAudio();
    },
  };
}

let engine = null;
/** The app's one engine (created on first use; no audio until a gesture). */
export function uiSounds() {
  if (!engine) engine = createUiSoundEngine();
  return engine;
}

/** Plays one interface cue (see uiSoundsModel CUES); silent when the rules say so. */
export const playCue = (cue, options) => uiSounds().play(cue, options);
