// Pure model for the talking overlay (no DOM, no React): snapshot → view, and the close
// countdown as a reducer over an injected clock, so node:test can check every rule.
// The main process (electron/overlay-app.cjs) has already validated each snapshot.

/** Hold before fading out, per end kind (ms). "now" fades at once. */
export const HOLD_MS = Object.freeze({ quiet: 4000, error: 8000, now: 0 });
/** Leaving the panel resumes the countdown with at least this long left. */
export const RESUME_MIN_MS = 2000;
/** Exit fade (matches the CSS 180 ms exit). */
export const FADE_MS = 180;

/** Text tones → colour tokens (see overlay.css). */
export const TONES = Object.freeze({ primary: '--text-1', secondary: '--text-2', tertiary: '--text-3', warn: '--warn' });

const RING = { connecting: 'working', thinking: 'working', working: 'working', listening: 'listening', speaking: 'speaking', ended: 'offline' };

/** PresenceRing state for a snapshot state. */
export const ringState = state => RING[state] || 'working';

// "hey jarvis" (any case, a comma or spaces between) and any following , . ! and spaces.
const WAKE = /^\s*hey[\s,]+jarvis(?![a-z])[\s,.!]*/i;

/** The owner's words without a leading "Hey Jarvis", next letter capitalised; '' when nothing is left. */
export function stripWake(text) {
  const value = typeof text === 'string' ? text : '';
  const rest = value.replace(WAKE, '').trim();
  if (rest === value.trim()) return rest;
  return rest ? rest.charAt(0).toUpperCase() + rest.slice(1) : '';
}

const quoted = text => `“${text}”`;

/** The end of a snapshot, or null while the session runs. */
export const endOf = snapshot => (snapshot && snapshot.state === 'ended' ? snapshot.end || { kind: 'quiet', message: null } : null);

/**
 * View for one snapshot: { ring, top, main, showStop, showOpen, endKind } where top and main
 * are { text, tone } or null (hidden). Text is plain text; the renderer never parses it as HTML.
 */
export function snapshotView(snapshot) {
  if (!snapshot) return { ring: 'working', top: null, main: null, showStop: false, showOpen: false, endKind: null };
  const end = endOf(snapshot);
  const jarvis = (snapshot.jarvis || '').trim();
  const ring = ringState(snapshot.state);
  if (end?.kind === 'now') return { ring, top: null, main: null, showStop: false, showOpen: false, endKind: 'now' };
  if (end) {
    const message = (end.message || '').trim();
    return {
      ring,
      top: end.kind === 'quiet' ? { text: 'Voice is off', tone: 'tertiary' } : null,
      main: end.kind === 'quiet'
        ? (jarvis ? { text: jarvis, tone: 'secondary' } : null)
        : (message ? { text: message, tone: 'warn' } : null),
      showStop: false,
      showOpen: end.kind === 'quiet' || snapshot.approval === true,
      endKind: end.kind,
    };
  }
  let top;
  const words = stripWake(snapshot.user);
  if (snapshot.state === 'connecting') top = { text: 'Connecting…', tone: 'tertiary' };
  else if (!words) top = { text: 'Listening', tone: 'tertiary' };
  else if (jarvis) top = { text: quoted(words), tone: 'tertiary' };
  else top = { text: quoted(words), tone: snapshot.user_final ? 'secondary' : 'primary' };
  let main = null;
  if (jarvis) main = { text: jarvis, tone: snapshot.state === 'speaking' ? 'primary' : 'secondary' };
  else if (snapshot.state === 'thinking') main = { text: 'Thinking…', tone: 'tertiary' };
  else if (snapshot.state === 'working') main = { text: 'Working on it…', tone: 'tertiary' };
  return { ring, top, main, showStop: true, showOpen: snapshot.approval === true, endKind: null };
}

/*
 * Close countdown. Phases: waiting (no snapshot yet) → open → hold (ended, counting down)
 * → fading (exit motion) → closed (the renderer calls done()). Times are ms on one clock.
 */
export const initialOverlay = Object.freeze({
  snapshot: null, session: undefined, phase: 'waiting', pointer: false, deadline: null, remaining: null, fadeUntil: null,
});

const fadeAt = (state, now) => ({ ...state, phase: 'fading', deadline: null, remaining: null, fadeUntil: now + FADE_MS });

function beginEnd(state, end, now) {
  const hold = HOLD_MS[end.kind] ?? HOLD_MS.quiet;
  if (hold <= 0) return fadeAt(state, now);
  return state.pointer
    ? { ...state, phase: 'hold', deadline: null, remaining: hold }
    : { ...state, phase: 'hold', deadline: now + hold, remaining: null };
}

function onSnapshot(state, snapshot, now) {
  if (!snapshot || state.phase === 'closed') return state;
  const end = endOf(snapshot);
  if (state.phase === 'hold' || state.phase === 'fading') {
    // A different session that is still running cancels the close and shows it.
    if (!end && snapshot.session !== state.session) {
      return { ...state, snapshot, session: snapshot.session, phase: 'open', deadline: null, remaining: null, fadeUntil: null };
    }
    // The same ended session may refresh its text while holding; nothing changes while fading.
    if (state.phase === 'hold' && end && snapshot.session === state.session) {
      const next = { ...state, snapshot };
      return end.kind === 'now' ? fadeAt(next, now) : next;
    }
    return state;
  }
  const next = { ...state, snapshot, session: snapshot.session, phase: 'open' };
  return end ? beginEnd(next, end, now) : next;
}

function onPointer(state, inside, now) {
  const next = { ...state, pointer: inside === true };
  if (state.phase !== 'hold') return next;
  if (next.pointer && state.deadline !== null) return { ...next, deadline: null, remaining: Math.max(0, state.deadline - now) };
  if (!next.pointer && state.deadline === null) return { ...next, deadline: now + Math.max(state.remaining ?? 0, RESUME_MIN_MS), remaining: null };
  return next;
}

function onTick(state, now) {
  if (state.phase === 'hold' && state.deadline !== null && now >= state.deadline) return fadeAt(state, now);
  if (state.phase === 'fading' && now >= state.fadeUntil) return { ...state, phase: 'closed', fadeUntil: null };
  return state;
}

/**
 * Actions: { type: 'snapshot', snapshot, now } | { type: 'pointer', inside, now } |
 * { type: 'tick', now } | { type: 'open', now } (Open JARVIS clicked).
 */
export function overlayReducer(state, action) {
  switch (action?.type) {
    case 'snapshot': return onSnapshot(state, action.snapshot, action.now);
    case 'pointer': return onPointer(state, action.inside, action.now);
    case 'tick': return onTick(state, action.now);
    // After the session has ended, Open JARVIS fades the panel out right away.
    case 'open': return state.phase === 'hold' ? fadeAt(state, action.now) : state;
    default: return state;
  }
}

/** When the next tick is due (ms on the reducer's clock), or null when nothing is pending. */
export function nextDeadline(state) {
  if (state.phase === 'hold') return state.deadline;
  if (state.phase === 'fading') return state.fadeUntil;
  return null;
}

/** Full view: the snapshot view plus whether the panel is showing (it fades out otherwise). */
export function overlayView(state) {
  return { ...snapshotView(state.snapshot), visible: state.phase === 'open' || state.phase === 'hold', phase: state.phase };
}
