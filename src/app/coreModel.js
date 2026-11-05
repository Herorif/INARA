// Pure model for the live JARVIS core (no DOM, no three.js), so node can unit-test it.
// The scene is art/blender/jarvis-core.py; src/app/coreScene.js applies these poses to it.

/** Presence states the core can show. */
export const CORE_STATES = ['idle', 'listening', 'speaking', 'working', 'offline'];
const ALIASES = { recording: 'listening', transcribing: 'working', thinking: 'working', playback: 'speaking' };

/** Normalises any caller state (idle, listening, recording, transcribing, working, speaking, playback, offline). */
export const presenceState = state => ALIASES[state] || (CORE_STATES.includes(state) ? state : 'idle');

/** The live core needs 64 px or more, motion allowed, no low-power mode and a working WebGL. */
export const MIN_3D_SIZE = 64;
/** Below this the core drops to the small level of detail. */
export const FULL_LOD_SIZE = 96;

export function presenceMode({ size, reducedMotion, lowPower, webgl }) {
  return size >= MIN_3D_SIZE && !reducedMotion && !lowPower && webgl !== false ? '3d' : 'flat';
}

export const coreLod = size => (size < FULL_LOD_SIZE ? 'small' : 'full');

// Speeds in degrees per second; tilt is the fraction of each ring's stored rest tilt;
// speak 1 lets the voice drive the core; sweep 1 shows the working arcs at small LOD;
// offline 1 turns the lines steel.
export const CORE_TARGETS = Object.freeze({
  idle: Object.freeze({ midSpeed: 6, innerSpeed: -4, arcSpeed: 0, tilt: 1, arcOpacity: 0.35, speak: 0, sweep: 0, offline: 0 }),
  listening: Object.freeze({ midSpeed: 12, innerSpeed: -8, arcSpeed: 0, tilt: 0.35, arcOpacity: 1, speak: 0, sweep: 0, offline: 0 }),
  speaking: Object.freeze({ midSpeed: 8, innerSpeed: -5, arcSpeed: 0, tilt: 1, arcOpacity: 1, speak: 1, sweep: 0, offline: 0 }),
  working: Object.freeze({ midSpeed: 60, innerSpeed: 30, arcSpeed: 120, tilt: 1, arcOpacity: 1, speak: 0, sweep: 1, offline: 0 }),
  offline: Object.freeze({ midSpeed: 0, innerSpeed: 0, arcSpeed: 0, tilt: 1, arcOpacity: 0.35, speak: 0, sweep: 0, offline: 1 }),
});

/** Easing time constants in milliseconds. */
export const TAU = Object.freeze({ speed: 400, tilt: 250, coreScale: 250, arcOpacity: 250, sweep: 250, offline: 150 });
export const ENVELOPE_TAU = Object.freeze({ attack: 50, release: 200 });
/** Speaking with no new level for longer than this uses the synthetic pulse. */
export const LEVEL_STALE_MS = 300;
/** Core scale = 1 + gain * voice, per level of detail. */
export const CORE_SCALE_GAIN = Object.freeze({ small: 0.30, full: 0.12 });
/** Small LOD only: core_edges opacity = base + gain * voice (the dim crystal lights up). */
export const EDGE_GLOW = Object.freeze({ base: 0.35, gain: 0.65 });
/** Below this sweep weight the small-LOD arc band is hidden. */
export const SWEEP_VISIBLE = 0.001;
/** The approved idle still: the first frame matches it. */
export const INITIAL_ANGLES = Object.freeze({ midAngle: 10, innerAngle: -6, arcAngle: 0 });

/** Synthetic voice drive (0..1, t in seconds) for sessions that send no level. */
export const syntheticPulse = t => 0.5 + 0.5 * Math.sin(2 * Math.PI * t / 1.2);

/**
 * Target for one frame. `envelope` is the smoothed level (0..1), `levelAge` the ms since the
 * last new level value, `time` the animation clock in seconds.
 */
export function coreTarget(state, { envelope = 0, levelAge = Infinity, time = 0 } = {}) {
  const stale = !(levelAge <= LEVEL_STALE_MS);
  return {
    ...CORE_TARGETS[presenceState(state)],
    levelDrive: Math.min(1, Math.max(0, envelope)),
    pulseDrive: syntheticPulse(time),
    pulse: stale ? 1 : 0,
  };
}

const EASED = [
  ['midSpeed', TAU.speed], ['innerSpeed', TAU.speed], ['arcSpeed', TAU.speed],
  ['tilt', TAU.tilt], ['arcOpacity', TAU.arcOpacity], ['speak', TAU.coreScale], ['pulse', TAU.coreScale],
  ['sweep', TAU.sweep], ['offline', TAU.offline],
];
export const EASED_KEYS = EASED.map(([key]) => key);
const SPIN = [['midAngle', 'midSpeed'], ['innerAngle', 'innerSpeed'], ['arcAngle', 'arcSpeed']];

const wrap = angle => ((angle % 360) + 360) % 360;
/** voice = speak × d, with d the level drive blended into the synthetic pulse by `pulse`. */
const voiceOf = pose => pose.speak * ((1 - pose.pulse) * pose.levelDrive + pose.pulse * pose.pulseDrive);

/** Pose at rest in `state` (no easing at mount: the flat ring was showing before). */
export function initialPose(state = 'idle', options) {
  const target = coreTarget(state, options);
  const pose = { ...INITIAL_ANGLES };
  for (const key of EASED_KEYS) pose[key] = target[key];
  pose.levelDrive = target.levelDrive;
  pose.pulseDrive = target.pulseDrive;
  pose.voice = voiceOf(pose);
  return pose;
}

/**
 * Frame-rate-independent exponential smoothing toward `target` over `dt` ms
 * (k = 1 - exp(-dt/τ)). Angles (degrees) accumulate the exact integral of the eased speeds,
 * so they are frame-rate independent too. Returns a new pose.
 */
export function stepPose(pose, target, dt) {
  const next = { ...pose };
  if (!(dt > 0)) dt = 0;
  for (const [key, tau] of EASED) next[key] = target[key] + (pose[key] - target[key]) * Math.exp(-dt / tau);
  const decay = Math.exp(-dt / TAU.speed);
  for (const [angle, speed] of SPIN) {
    const travelled = target[speed] * dt + (pose[speed] - target[speed]) * TAU.speed * (1 - decay);
    next[angle] = wrap(pose[angle] + travelled / 1000);
  }
  // The level and pulse drives are already continuous; only their weights are eased.
  next.levelDrive = target.levelDrive;
  next.pulseDrive = target.pulseDrive;
  next.voice = voiceOf(next);
  return next;
}

const TOLERANCE = { midSpeed: 0.01, innerSpeed: 0.01, arcSpeed: 0.01 };
/**
 * True when every visible eased value has reached its target. The level/pulse weight only shows
 * while speaking, so a level arriving in another state never keeps the loop awake.
 */
export function isSettled(pose, target) {
  const silent = target.speak === 0 && pose.speak <= 1e-3;
  return EASED_KEYS.every(key => (silent && key === 'pulse') || Math.abs(pose[key] - target[key]) <= (TOLERANCE[key] ?? 1e-3));
}

/** Level envelope: attack τ 50 ms, release τ 200 ms. */
export function levelEnvelope(env, level, dt) {
  const value = Math.min(1, Math.max(0, Number.isFinite(level) ? level : 0));
  const tau = value > env ? ENVELOPE_TAU.attack : ENVELOPE_TAU.release;
  return value + (env - value) * Math.exp(-Math.max(0, dt) / tau);
}

/** Milliseconds between frames (idle 15 fps, live or settling 60 fps); null means stop the loop. */
export function frameInterval(state, settling) {
  const value = presenceState(state);
  if (value === 'offline') return settling ? 1000 / 60 : null;
  if (value === 'idle' && !settling) return 1000 / 15;
  return 1000 / 60;
}

/** Vertical FOV of the README default view: 100 mm lens on a 36 mm sensor. */
export const CORE_FOV = 2 * Math.atan(18 / 100) * 180 / Math.PI;
const AZIMUTH = 24, ELEVATION = 12;

/** Camera for a square canvas: full LOD frames the reticle (README), small the outer ring at 88%. */
export function cameraFor(size, lod) {
  const half = Math.tan(CORE_FOV * Math.PI / 360);
  const distance = lod === 'small' ? 1.0 / (0.88 * half) : (1.2 * 256 / 228) / half;
  const az = AZIMUTH * Math.PI / 180, el = ELEVATION * Math.PI / 180;
  return {
    fov: CORE_FOV, aspect: 1, near: 0.1, far: 100, distance,
    position: [distance * Math.cos(el) * Math.sin(az), distance * Math.sin(el), distance * Math.cos(el) * Math.cos(az)],
    target: [0, 0, 0], up: [0, 1, 0],
  };
}
