/*
 * JARVIS interface sounds (9NovWork specs S13a "Sound", docs/SOUND.md): pure logic, tested
 * without WebAudio. uiSounds.js turns these decisions and cue designs into oscillators.
 *
 * - Cue designs: one timbre family. Every note is a sine plus a soft triangle an octave up,
 *   with a short linear attack and an exponential decay; a little of each cue goes to a
 *   short generated reverb. Every cue's notes end within CUE_MAX_MS.
 * - Mute rules: off switch, gaming mode, a call in progress, a muted system output (when it
 *   is known), and a zero volume.
 * - Scheduling: never more than one cue inside GAP_MS (the newer cue cuts the older one);
 *   `thinking` never interrupts and never repeats sooner than THINKING_EVERY_MS; nothing
 *   plays while the page is settling (start-up, reconnect, unlock), so restored state is
 *   silent.
 */

export const CUES = Object.freeze(['wake', 'listen', 'thinking', 'confirm', 'deny', 'panelOpen', 'panelClose', 'notify']);
export const GAP_MS = 80;
export const THINKING_EVERY_MS = 4000;
export const SETTLE_MS = 1500;
export const CUE_MAX_MS = 350;
/** Master gain at 100 % volume; cue peaks stay well below 1 (clipping). */
export const MASTER_CEILING = 0.6;
/** The octave-up triangle's level relative to the note's sine. */
export const TRIANGLE_MIX = 0.3;
/** Share of every cue sent to the short reverb. */
export const REVERB_SEND = 0.18;
export const REVERB_SECONDS = 0.3;

export const SOUND_DEFAULTS = Object.freeze({ enabled: true, volume: 0.5, thinking: false });

/**
 * One note: `at` and `ms` (start and length in ms), `hz` (sine; the triangle plays 2 x hz),
 * `to` (optional glide target in Hz), `gain` (sine peak), `attack` (ms), `triangle`
 * (optional override of TRIANGLE_MIX).
 */
const note = (at, ms, hz, gain, attack = 6, extra = {}) => Object.freeze({ at, ms, hz, gain, attack, ...extra });

export const CUE_DESIGNS = Object.freeze({
  // Rising two-tone: A5 then E6.
  wake: Object.freeze([note(0, 120, 880, 0.2), note(90, 200, 1318.51, 0.18)]),
  // Single soft up-tick: C6 gliding a tone up.
  listen: Object.freeze([note(0, 90, 1046.5, 0.12, 5, { to: 1174.66 })]),
  // Very quiet low pulse: A3 with a slow swell.
  thinking: Object.freeze([note(0, 320, 220, 0.045, 90, { triangle: 0.15 })]),
  // Two notes up: G5 then C6.
  confirm: Object.freeze([note(0, 110, 783.99, 0.18), note(80, 180, 1046.5, 0.17)]),
  // Two notes down, a little lower: E5 then B4.
  deny: Object.freeze([note(0, 110, 659.26, 0.18), note(80, 200, 493.88, 0.18)]),
  // Short airy up-sweep (more triangle, slower attack).
  panelOpen: Object.freeze([note(0, 220, 600, 0.08, 40, { to: 1200, triangle: 0.6 })]),
  // Short down-sweep.
  panelClose: Object.freeze([note(0, 180, 1000, 0.075, 25, { to: 520, triangle: 0.6 })]),
  // Bell-like single: E6, instant attack, long decay.
  notify: Object.freeze([note(0, 340, 1318.51, 0.18, 3)]),
});

/** A cue's length in ms (its last note's end). */
export function cueLength(cue) {
  const notes = CUE_DESIGNS[cue] || [];
  return notes.reduce((end, item) => Math.max(end, item.at + item.ms), 0);
}

/**
 * A safe upper bound on a cue's peak amplitude at 100 % volume: every note that sounds at
 * the same time at its full level, sine plus triangle, plus the reverb send.
 */
export function cuePeak(cue) {
  const notes = CUE_DESIGNS[cue] || [];
  let peak = 0;
  for (const item of notes) {
    const overlapping = notes.filter(other => other.at < item.at + item.ms && item.at < other.at + other.ms);
    const sum = overlapping.reduce((total, other) => total + other.gain * (1 + (other.triangle ?? TRIANGLE_MIX)), 0);
    peak = Math.max(peak, sum);
  }
  return peak * (1 + REVERB_SEND) * MASTER_CEILING;
}

const clamp01 = value => Math.min(1, Math.max(0, value));

/** Saved `settings.sound` -> { enabled, volume (0..1, two decimals), thinking }. */
export function soundChoice(sound) {
  const value = sound && typeof sound === 'object' && !Array.isArray(sound) ? sound : {};
  const volume = typeof value.volume === 'number' && Number.isFinite(value.volume) && value.volume >= 0 && value.volume <= 1
    ? Math.round(value.volume * 100) / 100 : SOUND_DEFAULTS.volume;
  return {
    enabled: typeof value.enabled === 'boolean' ? value.enabled : SOUND_DEFAULTS.enabled,
    volume,
    thinking: typeof value.thinking === 'boolean' ? value.thinking : SOUND_DEFAULTS.thinking,
  };
}

/** Volume 0..1 -> master gain. Squared, so the slider feels even to the ear. */
export function volumeGain(volume) {
  const value = typeof volume === 'number' && Number.isFinite(volume) ? clamp01(volume) : SOUND_DEFAULTS.volume;
  return Math.round(MASTER_CEILING * value * value * 10000) / 10000;
}

/**
 * Why sounds are silent right now, or null when they may play. `systemMuted` is true only
 * when the system output is known to be muted (the renderer cannot read it on Windows, so it
 * stays null there).
 */
export function muteReason({ enabled = SOUND_DEFAULTS.enabled, volume = SOUND_DEFAULTS.volume, gaming = false, onCall = false, systemMuted = null } = {}) {
  if (enabled !== true) return 'off';
  if (gaming) return 'gaming';
  if (onCall) return 'call';
  if (systemMuted === true) return 'system';
  if (volumeGain(volume) <= 0) return 'volume';
  return null;
}

/**
 * The cue scheduler. `decide(cue, state)` -> { play: false, reason } or { play: true, cut },
 * where `cut` means the previous cue started less than GAP_MS ago and must be cut off.
 * `state` is { enabled, volume, thinking, gaming, onCall, systemMuted }. A `sample` decision
 * (Preferences' "Play a sample") ignores settling but keeps every mute rule.
 */
export function createCueScheduler({ now = () => Date.now(), gapMs = GAP_MS, thinkingEveryMs = THINKING_EVERY_MS } = {}) {
  let last = null;
  let lastThinking = -Infinity;
  let quietUntil = -Infinity;
  return {
    settle(ms = SETTLE_MS) { quietUntil = Math.max(quietUntil, now() + ms); },
    decide(cue, state = {}, { sample = false } = {}) {
      if (!CUES.includes(cue)) return { play: false, reason: 'unknown' };
      const reason = muteReason(state);
      if (reason) return { play: false, reason };
      const at = now();
      if (!sample && at < quietUntil) return { play: false, reason: 'settling' };
      const recent = !!last && at - last.at < gapMs;
      if (cue === 'thinking') {
        if (state.thinking !== true) return { play: false, reason: 'thinking_off' };
        if (at - lastThinking < thinkingEveryMs) return { play: false, reason: 'rate' };
        if (recent) return { play: false, reason: 'busy' };
        lastThinking = at;
      }
      last = { cue, at };
      return { play: true, cut: recent };
    },
  };
}

const ACTIVE_VOICE = new Set(['idle', 'listening', 'thinking', 'speaking']);

/**
 * The live voice controller's status moved (store `voice`): a session starting -> 'wake',
 * listening starting inside a running session -> 'listen', otherwise null.
 */
export function voiceCue(previous, next) {
  const before = previous?.state || 'off';
  const after = next?.state || 'off';
  if (!ACTIVE_VOICE.has(before) && ACTIVE_VOICE.has(after)) return 'wake';
  if (ACTIVE_VOICE.has(before) && before !== 'listening' && after === 'listening') return 'listen';
  return null;
}

const STARTING = new Set(['connecting', 'listening']);

/**
 * A tray voice / "Hey Jarvis" snapshot arrived (store `localVoice`): a new session that is
 * just starting -> 'wake' (a snapshot of a session already speaking is a restore, and the
 * morning briefing is announced by its card instead); listening again inside the session ->
 * 'listen'.
 */
export function localVoiceCue(previous, next) {
  if (!next || next.state === 'ended') return null;
  const fresh = !previous || previous.session !== next.session;
  if (fresh) return STARTING.has(next.state) && next.source !== 'briefing' ? 'wake' : null;
  if (next.state === 'listening' && previous.state !== 'listening' && previous.state !== 'connecting') return 'listen';
  return null;
}

/** True while JARVIS works on a reply (either voice path). */
export function thinkingActive(voice, localVoice) {
  if (voice?.state === 'thinking') return true;
  return !!localVoice && (localVoice.state === 'thinking' || localVoice.state === 'working');
}

/** An approval was answered. */
export const approvalCue = confirmed => (confirmed === true ? 'confirm' : 'deny');

/** A Materialise frame's `show` changed (or it mounted shown: previous undefined). */
export function panelCue(previous, show) {
  if (show && previous !== true) return 'panelOpen';
  if (!show && previous === true) return 'panelClose';
  return null;
}

/**
 * Remembers which notifications already sounded, by key ('vip:<record>', 'briefing:<date>'),
 * so a re-sent or re-hydrated card never sounds twice. `fresh(key)` is true the first time.
 */
export function createNoticeTracker(limit = 64) {
  const seen = [];
  return {
    fresh(key) {
      if (typeof key !== 'string' || !key || seen.includes(key)) return false;
      seen.push(key);
      if (seen.length > limit) seen.shift();
      return true;
    },
  };
}

/** Store values -> notification keys: the VIP call card and the morning briefing card. */
export const vipNoticeKey = alert => (alert && typeof alert.recordId === 'string' && alert.recordId ? `vip:${alert.recordId}` : null);
export const briefingNoticeKey = briefing => (briefing && typeof briefing.date === 'string' && briefing.date ? `briefing:${briefing.date}` : null);
