// Pure helpers for the talking overlay (electron/overlay-app.cjs): window bounds, bootstrap and
// core payload validation. No electron import, so node:test can require this file directly.
const path = require('node:path');

/** Window: the 560 px panel plus 24 px side margins; 24 top margin + 116 max panel + 16 bottom gap. */
const PANEL_WIDTH = 560;
const SIDE_MARGIN = 24;
const WINDOW_WIDTH = PANEL_WIDTH + 2 * SIDE_MARGIN; // 608
const WINDOW_HEIGHT = 156;
const NARROW_WORK_AREA = 640;
const NARROW_INSET = 32;

const STATES = Object.freeze(['connecting', 'listening', 'thinking', 'working', 'speaking', 'ended']);
const END_KINDS = Object.freeze(['quiet', 'error', 'now']);
const LIMITS = Object.freeze({ session: 128, user: 300, jarvis: 600, message: 300 });

const TOKEN = /^[0-9a-f]{64}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const LOCAL_CORE_HOSTS = new Set(['127.0.0.1', 'localhost']);

const integer = value => typeof value === 'number' && Number.isFinite(value) ? Math.round(value) : null;

/**
 * Overlay window bounds inside a display work area (which already excludes the taskbar):
 * centred horizontally, bottom edge on the work area's bottom edge. Narrow work areas
 * (< 640 px) use their width minus 32 px.
 */
function overlayBounds(workArea) {
  const x = integer(workArea?.x), y = integer(workArea?.y);
  const width = integer(workArea?.width), height = integer(workArea?.height);
  if (x === null || y === null || width === null || height === null || width <= 0 || height <= 0) throw Error('Invalid work area');
  const windowWidth = width < NARROW_WORK_AREA ? Math.max(1, width - NARROW_INSET) : WINDOW_WIDTH;
  return {
    x: x + Math.round((width - windowWidth) / 2),
    y: y + height - WINDOW_HEIGHT,
    width: windowWidth,
    height: WINDOW_HEIGHT,
  };
}

/** The core origin: plain http on 127.0.0.1 or localhost with an explicit port, nothing else. */
function coreOrigin(value) {
  if (typeof value !== 'string' || value.length > 64) return null;
  let url;
  try { url = new URL(value); } catch { return null; }
  if (url.protocol !== 'http:' || !LOCAL_CORE_HOSTS.has(url.hostname) || !url.port) return null;
  if (url.username || url.password || url.search || url.hash || (url.pathname !== '/' && url.pathname !== '')) return null;
  // Reject anything the URL parser normalised away (spaces, case, trailing junk, default port).
  const origin = `http://${url.hostname}:${url.port}`;
  if (value !== origin && value !== `${origin}/`) return null;
  return origin;
}

/**
 * Strict bootstrap check. Returns { ok: true, value } with only the known fields, or
 * { ok: false, error } with a one-line message that never contains the token.
 */
function validateBootstrap(raw) {
  const fail = field => ({ ok: false, error: `Invalid overlay bootstrap: ${field}` });
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return fail('not an object');
  if (typeof raw.token !== 'string' || !TOKEN.test(raw.token)) return fail('token');
  if (typeof raw.clientId !== 'string' || !UUID.test(raw.clientId)) return fail('clientId');
  if (typeof raw.profile !== 'string' || raw.profile.length > 1024 || !path.isAbsolute(raw.profile) || raw.profile.includes('\0')) return fail('profile');
  const core = coreOrigin(raw.core);
  if (!core) return fail('core');
  if (raw.dev !== undefined && typeof raw.dev !== 'boolean') return fail('dev');
  return { ok: true, value: { token: raw.token, clientId: raw.clientId, profile: raw.profile, core, dev: raw.dev === true } };
}

/** Parses the stdin text; same contract as validateBootstrap. */
function parseBootstrap(text) {
  let raw;
  try { raw = JSON.parse(text); } catch { return { ok: false, error: 'Invalid overlay bootstrap: not JSON' }; }
  return validateBootstrap(raw);
}

// Control characters other than tab and newline never reach the renderer.
// eslint-disable-next-line no-control-regex
const CONTROL = /[\u0000-\u0008\u000b-\u001f\u007f-\u009f]/g;

const highSurrogate = code => code >= 0xd800 && code <= 0xdbff;
const lowSurrogate = code => code >= 0xdc00 && code <= 0xdfff;

/**
 * Truncates to at most `limit` UTF-16 units without splitting a surrogate pair. `keep` 'start'
 * keeps the beginning; 'end' keeps the newest words (the main caption shows newest at the bottom).
 */
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
 * Validates one `voice_overlay` snapshot. Returns a fresh object with only the contract fields,
 * text truncated to its limit (JARVIS's words keep their newest end), or null when a type or enum is wrong (the snapshot is dropped).
 * `end` and `state` agree afterwards: an end makes the state "ended", and "ended" with no end
 * reads as a quiet end.
 */
function sanitizeSnapshot(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const { session, state, user, user_final: userFinal, jarvis, jarvis_final: jarvisFinal, approval, end } = raw;
  if (session !== null && (typeof session !== 'string' || session.length > LIMITS.session)) return null;
  if (typeof state !== 'string' || !STATES.includes(state)) return null;
  if (typeof user !== 'string' || typeof jarvis !== 'string') return null;
  if (typeof userFinal !== 'boolean' || typeof jarvisFinal !== 'boolean' || typeof approval !== 'boolean') return null;
  let cleanEnd = null;
  if (end !== null && end !== undefined) {
    if (typeof end !== 'object' || Array.isArray(end) || !END_KINDS.includes(end.kind)) return null;
    if (end.message !== null && end.message !== undefined && typeof end.message !== 'string') return null;
    cleanEnd = { kind: end.kind, message: typeof end.message === 'string' ? clip(end.message, LIMITS.message) : null };
  }
  if (state === 'ended' && !cleanEnd) cleanEnd = { kind: 'quiet', message: null };
  return {
    session,
    state: cleanEnd ? 'ended' : state,
    user: clip(user, LIMITS.user),
    user_final: userFinal,
    jarvis: clip(jarvis, LIMITS.jarvis, 'end'),
    jarvis_final: jarvisFinal,
    approval,
    end: cleanEnd,
  };
}

/** Validates one `voice_level` payload: a finite number clamped to 0..1, or null to drop it. */
function sanitizeLevel(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const { level } = raw;
  if (typeof level !== 'number' || !Number.isFinite(level)) return null;
  return { level: Math.min(1, Math.max(0, level)) };
}

module.exports = {
  PANEL_WIDTH,
  SIDE_MARGIN,
  WINDOW_WIDTH,
  WINDOW_HEIGHT,
  NARROW_WORK_AREA,
  STATES,
  END_KINDS,
  LIMITS,
  overlayBounds,
  coreOrigin,
  validateBootstrap,
  parseBootstrap,
  sanitizeSnapshot,
  sanitizeLevel,
};
