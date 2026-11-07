// Pure validation of tray voice payloads for the workspace's speaking core (no DOM, no store).
// `local_voice` is the talking overlay's snapshot plus `source`; this is the renderer-side
// equivalent of electron/overlay-policy.cjs sanitizeSnapshot, which the browser bundle cannot
// load (it is CommonJS for the overlay's main process). tests/test_speaking_core.mjs checks
// that both agree.

export const LOCAL_STATES = Object.freeze(['connecting', 'listening', 'thinking', 'working', 'speaking', 'ended']);
export const LOCAL_END_KINDS = Object.freeze(['quiet', 'error', 'now']);
/** How a tray session started: the tray's "Talk to JARVIS", or "Hey Jarvis". */
export const LOCAL_SOURCES = Object.freeze(['tray', 'wake']);
export const LOCAL_LIMITS = Object.freeze({ session: 128, user: 300, jarvis: 600, message: 300 });

// Control characters other than tab and newline never reach the page.
// eslint-disable-next-line no-control-regex
const CONTROL = /[\u0000-\u0008\u000b-\u001f\u007f-\u009f]/g;
const highSurrogate = code => code >= 0xd800 && code <= 0xdbff;
const lowSurrogate = code => code >= 0xdc00 && code <= 0xdfff;

/** At most `limit` UTF-16 units without splitting a surrogate pair; 'end' keeps the newest words. */
function clip(value, limit, keep = 'start') {
  const text = value.replace(CONTROL, '');
  if (text.length <= limit) return text;
  if (keep === 'end') {
    let start = text.length - limit;
    if (lowSurrogate(text.charCodeAt(start))) start += 1;
    return text.slice(start);
  }
  let end = limit;
  if (highSurrogate(text.charCodeAt(end - 1))) end -= 1;
  return text.slice(0, end);
}

/**
 * One `local_voice` payload: a fresh object with only the contract fields (text clipped to its
 * limit, JARVIS's words keeping their newest end), or null to drop it (a wrong type, enum or
 * source). An end makes the state "ended", and "ended" with no end reads as a quiet end.
 */
export function sanitizeLocalVoice(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const { session, state, user, user_final: userFinal, jarvis, jarvis_final: jarvisFinal, approval, design, end, source } = raw;
  if (session !== null && (typeof session !== 'string' || session.length > LOCAL_LIMITS.session)) return null;
  if (typeof state !== 'string' || !LOCAL_STATES.includes(state)) return null;
  if (typeof user !== 'string' || typeof jarvis !== 'string') return null;
  if (typeof userFinal !== 'boolean' || typeof jarvisFinal !== 'boolean' || typeof approval !== 'boolean') return null;
  if (typeof source !== 'string' || !LOCAL_SOURCES.includes(source)) return null;
  let cleanEnd = null;
  if (end !== null && end !== undefined) {
    if (typeof end !== 'object' || Array.isArray(end) || !LOCAL_END_KINDS.includes(end.kind)) return null;
    if (end.message !== null && end.message !== undefined && typeof end.message !== 'string') return null;
    cleanEnd = { kind: end.kind, message: typeof end.message === 'string' ? clip(end.message, LOCAL_LIMITS.message) : null };
  }
  if (state === 'ended' && !cleanEnd) cleanEnd = { kind: 'quiet', message: null };
  return {
    session,
    state: cleanEnd ? 'ended' : state,
    user: clip(user, LOCAL_LIMITS.user),
    user_final: userFinal,
    jarvis: clip(jarvis, LOCAL_LIMITS.jarvis, 'end'),
    jarvis_final: jarvisFinal,
    approval,
    design: design === true,
    end: cleanEnd,
    source,
  };
}

/** One `local_voice_level` payload: a finite number clamped to 0..1, or null to drop it. */
export function sanitizeLocalLevel(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const { level } = raw;
  if (typeof level !== 'number' || !Number.isFinite(level)) return null;
  return Math.min(1, Math.max(0, level));
}

/**
 * The store patch for one validated snapshot. `endedAt` is when this session's end first
 * arrived (ms on `now`'s clock), which starts the stage's end hold; the level resets at the end
 * and when a different session starts.
 */
export function localVoicePatch(previous, previousEndedAt, snapshot, now) {
  const same = !!previous && previous.session === snapshot.session;
  if (snapshot.state !== 'ended') {
    return { localVoice: snapshot, localVoiceEndedAt: null, ...(same ? {} : { localVoiceLevel: 0 }) };
  }
  const endedAt = same && previous.state === 'ended' && previousEndedAt !== null ? previousEndedAt : now;
  return { localVoice: snapshot, localVoiceEndedAt: endedAt, localVoiceLevel: 0 };
}

/** Everything about tray voice cleared (core disconnected). */
export const LOCAL_VOICE_CLEARED = Object.freeze({ localVoice: null, localVoiceLevel: 0, localVoiceEndedAt: null });
