// Pure model for the JARVIS core glow and the workspace dot grid (9NovWork specs S13a "Core glow"
// and "Idle life"; audit B "Light", "Depth", "Motion"). No DOM, no three.js, tested in node.
//
// The 3D core gets an additive sprite behind it (src/app/coreScene.js); the flat ring a CSS
// box-shadow (src/app/presence.css). Both follow the core's state; the dot grid behind the
// Assistant view moves a few pixels toward the pointer.
import { motionMode } from '../shared/motion/motionModel.js';
import { presenceState } from './coreModel.js';

export const GLOW_COLOR = '#70e0ed';

/**
 * Per-state weights: `level` the base opacity, `breath` how much of the 4 s breathing shows,
 * `sweep` how much of the working sweep shows, `speak` how much the voice level adds.
 * Idle dim, listening a little brighter, speaking pulses with the voice, working sweeps slowly,
 * offline off.
 */
export const GLOW_TARGETS = Object.freeze({
  idle: Object.freeze({ level: 0.30, breath: 1, sweep: 0, speak: 0 }),
  listening: Object.freeze({ level: 0.42, breath: 0, sweep: 0, speak: 0 }),
  speaking: Object.freeze({ level: 0.30, breath: 0, sweep: 0, speak: 1 }),
  working: Object.freeze({ level: 0.34, breath: 0, sweep: 1, speak: 0 }),
  offline: Object.freeze({ level: 0, breath: 0, sweep: 0, speak: 0 }),
});
const KEYS = ['level', 'breath', 'sweep', 'speak'];

/** Breathing: a 4 s ease-in-out (cosine) cycle of about ±15% around the base. */
export const BREATH = Object.freeze({ period: 4, depth: 0.15 });
/** Working: a slower, deeper sweep of intensity. */
export const SWEEP = Object.freeze({ period: 2.4, depth: 0.4 });
/** Speaking adds gain × voice (voice 0..1 from coreModel: the level, or the synthetic pulse). */
export const SPEAK_GAIN = 0.5;
/** Easing time constant between states, in ms. */
export const GLOW_TAU = 250;
/** Below this opacity the sprite is hidden (no draw call). */
export const GLOW_VISIBLE = 0.002;
/** Dot grid parallax: at most this many CSS px toward the pointer. */
export const PARALLAX_MAX = 4;

const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
const finite = (value, fallback = 0) => (Number.isFinite(value) ? value : fallback);

/**
 * The on/off rule, from the same three switches as the materialise motion (motionModel):
 * gaming mode → 'off' (no glow at all), reduced motion or low battery → 'static' (glow, no
 * breathing), otherwise 'breathe'.
 */
export function glowMode({ reducedMotion = false, gaming = false, lowBattery = false } = {}) {
  const mode = motionMode({ reducedMotion, gaming, lowBattery });
  return mode === 'instant' ? 'off' : mode === 'fade' ? 'static' : 'breathe';
}

/** The flat ring's glow: the mode above, and none while the core is offline. */
export function flatGlow(state, mode) {
  if (presenceState(state) === 'offline') return 'off';
  return mode === 'off' || mode === 'static' ? mode : 'breathe';
}

/** Breathing factor at `time` seconds: 1 - depth at t = 0, 1 + depth at half a period. */
export function breathing(time, { period, depth } = BREATH) {
  return 1 - depth * Math.cos(2 * Math.PI * finite(time) / period);
}

/** Working sweep factor at `time` seconds (same curve, slower and deeper). */
export const sweeping = time => breathing(time, SWEEP);

/** Weights for `state` (any presence alias). */
export const glowTarget = state => GLOW_TARGETS[presenceState(state)];

/** Weights at rest in `state` (no easing at mount). */
export const initialGlow = (state = 'idle') => ({ ...glowTarget(state) });

/** Frame-rate-independent easing of every weight toward `target` over `dt` ms. */
export function stepGlow(glow, target, dt) {
  const k = Math.exp(-Math.max(0, finite(dt)) / GLOW_TAU);
  const next = {};
  for (const key of KEYS) next[key] = target[key] + (glow[key] - target[key]) * k;
  return next;
}

/**
 * Sprite opacity (0..1). `voice` and `offline` come from the core pose (coreModel), `time` is the
 * animation clock in seconds. 'static' holds the curves still; 'off' is always 0.
 */
export function glowOpacity(glow, { voice = 0, time = 0, offline = 0, mode = 'breathe' } = {}) {
  if (mode === 'off') return 0;
  const still = mode === 'static';
  const breath = still ? 1 : 1 + glow.breath * (breathing(time) - 1);
  const sweep = still ? 1 : 1 + glow.sweep * (sweeping(time) - 1);
  const value = glow.level * breath * sweep + glow.speak * SPEAK_GAIN * clamp(finite(voice), 0, 1);
  return clamp(value * (1 - clamp(finite(offline), 0, 1)), 0, 1);
}

/**
 * Parallax runs only in full motion (motionModel's 'full'): never with reduced motion, gaming
 * mode or low battery. Off means no pointer listener at all.
 */
export const parallaxEnabled = motion => motion === 'full';

/**
 * Grid offset in CSS px toward `pointer` ({x, y} client px) inside `box` (a DOMRect-like
 * {left, top, width, height}): ±max at the edges, 0 at the centre, clamped to ±max outside,
 * {0, 0} with no pointer.
 */
export function parallaxOffset(pointer, box, max = PARALLAX_MAX) {
  const limit = Math.max(0, finite(max));
  if (!pointer || !box || !(box.width > 0) || !(box.height > 0)) return { x: 0, y: 0 };
  const axis = (at, start, length) => {
    const value = (finite(at, start + length / 2) - (start + length / 2)) / (length / 2);
    return Math.round(clamp(value, -1, 1) * limit * 100) / 100 || 0;
  };
  return { x: axis(pointer.x, finite(box.left), box.width), y: axis(pointer.y, finite(box.top), box.height) };
}
