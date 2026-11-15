// Pure model for the Live design's CAD-engine preview (no DOM, no React, no three.js): the
// `design.preview` contract, the canvas status chip, the facts line, the camera refit rule,
// the in-memory GLB cache and the stale-response rule. The core is the authority
// (backend/services/cad_design.py `set_preview`, docs/LIVE_DESIGN.md "Draft previews").
// node:test checks each rule (tests/test_live_design_kernel.mjs).

// No imports from model.js: model.js imports sanitizePreview from here (no module cycle).

export const PREVIEW_STATES = Object.freeze(['starting', 'building', 'ready', 'failed', 'paused', 'unavailable']);
/** Draft GLBs kept in memory, newest use last (by sha256). */
export const GLB_CACHE_SIZE = 4;
/** Largest draft GLB the canvas accepts (the core's artifact limit). */
export const MAX_GLB_BYTES = 16777216;
/** The camera refits only when the model's bounds change by more than this fraction. */
export const REFIT_THRESHOLD = 0.2;
/** Edges flash in --accent-hot this long when a new GLB arrives after a step (ms). */
export const FLASH_MS = 1200; // model.js HIGHLIGHT_MS
export const STARTING_TEXT = 'Starting the CAD engine…';
export const UPDATING_TEXT = 'Updating…';
export const PAUSED_TEXT = 'Paused in gaming mode';
export const UNAVAILABLE_TEXT = 'The CAD engine isn’t available.';
export const FAILED_TEXT = 'The draft preview could not be built.';
const MAX_WARNINGS = 8;

// eslint-disable-next-line no-control-regex
const CONTROL = /[\u0000-\u001f\u007f-\u009f]/g;
const highSurrogate = code => code >= 0xd800 && code <= 0xdbff;
// model.js clipText(): at most `limit` UTF-16 units, ending in "…" when cut.
function clipText(value, limit) {
  if (value.length <= limit) return value;
  let end = limit - 1;
  if (highSurrogate(value.charCodeAt(end - 1))) end -= 1;
  return `${value.slice(0, end).trimEnd()}…`;
}
// model.js formatNumber() and sizeText(): 2 decimals, no trailing zeros, "W × D × H".
const formatNumber = value => {
  const rounded = Math.round(Number(value) * 100) / 100;
  return String(Object.is(rounded, -0) ? 0 : rounded);
};
const sizeText = values => values.map(formatNumber).join(' × ');
const text = (value, limit) => (typeof value === 'string' ? clipText(value.replace(CONTROL, ' ').replace(/\s+/g, ' ').trim(), limit) : null);
const finite = (value, low = -Infinity, high = Infinity) => typeof value === 'number' && Number.isFinite(value) && value >= low && value <= high;
const triple = (value, low, high) => Array.isArray(value) && value.length === 3 && value.every(item => finite(item, low, high));
const count = value => Number.isInteger(value) && value >= 0 && value <= 10_000_000;
const object = value => !!value && typeof value === 'object' && !Array.isArray(value);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const SHA256 = /^[a-f0-9]{64}$/;

function sanitizeGlb(raw) {
  if (!object(raw) || raw.format !== 'glb') return null;
  if (typeof raw.request_id !== 'string' || !UUID.test(raw.request_id)) return null;
  if (typeof raw.sha256 !== 'string' || !SHA256.test(raw.sha256)) return null;
  if (!Number.isInteger(raw.bytes) || raw.bytes < 1 || raw.bytes > MAX_GLB_BYTES) return null;
  return { request_id: raw.request_id, format: 'glb', bytes: raw.bytes, sha256: raw.sha256 };
}

function sanitizeFacts(raw) {
  if (!object(raw) || !finite(raw.volume_mm3, 0) || !triple(raw.bbox_mm, 0, 100000)) return null;
  const min = raw.min_mm === null || raw.min_mm === undefined ? null : raw.min_mm;
  if (min !== null && !triple(min, -100000, 100000)) return null;
  if (![raw.faces, raw.edges, raw.solids].every(count) || typeof raw.valid !== 'boolean') return null;
  return { volume_mm3: raw.volume_mm3, bbox_mm: [...raw.bbox_mm], min_mm: min && [...min], faces: raw.faces, edges: raw.edges, solids: raw.solids, valid: raw.valid };
}

function sanitizeWarning(raw) {
  if (!object(raw)) return null;
  const message = text(raw.message, 200);
  if (!message) return null;
  return { code: text(raw.code, 40) || 'warning', index: Number.isInteger(raw.index) && raw.index >= 0 ? raw.index : null, message };
}

/**
 * The snapshot's `design.preview` (CAD engine only), or null for the box-engine path: an
 * unknown engine or state drops it; a malformed `glb` or `facts` becomes null on its own.
 */
export function sanitizePreview(raw) {
  if (!object(raw) || raw.engine !== 'kernel' || !PREVIEW_STATES.includes(raw.state)) return null;
  const warnings = Array.isArray(raw.warnings) ? raw.warnings.slice(0, MAX_WARNINGS).map(sanitizeWarning).filter(Boolean) : [];
  return {
    engine: 'kernel',
    state: raw.state,
    message: text(raw.message, 300) || null,
    current: raw.current === true,
    glb: sanitizeGlb(raw.glb),
    facts: sanitizeFacts(raw.facts),
    warnings,
    seconds: finite(raw.seconds, 0) ? raw.seconds : null,
    cached: raw.cached === true,
  };
}

/** The design's CAD-engine preview, or null on the box-engine path. */
export const kernelPreview = design => (design?.preview?.engine === 'kernel' ? design.preview : null);

/** The GLB the canvas should show: { request_id, sha256, bytes }, or null. */
export function wantedGlb(preview) {
  const glb = preview?.glb;
  return glb ? { request_id: glb.request_id, sha256: glb.sha256, bytes: glb.bytes } : null;
}

/**
 * The canvas corner chip: { text, tone } (tone accent | warn | muted), or null when the shown
 * model is the current draft. The last good model stays on screen in every state.
 */
export function previewChip(preview) {
  if (!preview) return null;
  switch (preview.state) {
    case 'starting': return { text: preview.message || STARTING_TEXT, tone: 'accent' };
    case 'building': return preview.current ? null : { text: UPDATING_TEXT, tone: 'accent' };
    case 'failed': return { text: preview.message || FAILED_TEXT, tone: 'warn' };
    case 'paused': return { text: PAUSED_TEXT, tone: 'muted' };
    case 'unavailable': return { text: preview.message || UNAVAILABLE_TEXT, tone: 'muted' };
    default: return null;
  }
}

/** "11.6" from mm³: cubic centimetres with one decimal. */
export function cubicCentimetres(mm3) {
  const value = Math.round((Number(mm3) / 1000) * 10) / 10;
  return (Object.is(value, -0) ? 0 : value).toFixed(1);
}

/** Footer line for a kernel draft: "Volume 11.6 cm³ · 60 × 40 × 5 mm", or null without facts. */
export function factsLine(facts) {
  if (!facts) return null;
  return `Volume ${cubicCentimetres(facts.volume_mm3)} cm³ · ${sizeText(facts.bbox_mm)} mm`;
}

/** The warn rows above the footer (the core's plain messages). */
export const warningRows = preview => (preview?.warnings || []).map((item, i) => ({ key: `${item.code}:${item.index ?? 'x'}:${i}`, text: item.message }));

// --- camera framing -------------------------------------------------------------------------

/**
 * Framing (CAD axes, mm) for a model's box `{ min, size }`: the centre, the radius, the floor
 * and a key, as model.js framing() returns for the box parts. Null for an empty box.
 */
export function boxFraming(box) {
  if (!box || !triple(box.min, -1e6, 1e6) || !triple(box.size, 0, 1e6)) return null;
  const center = box.min.map((value, i) => value + box.size[i] / 2);
  const radius = Math.max(Math.hypot(...box.size) / 2, 1);
  return { center, radius, floor: box.min[2], size: [...box.size], key: [...center, ...box.size].map(value => Math.round(value * 10) / 10).join(':') };
}

/** The facts' box ({ min, size } in mm), or null when the core sent no minimum corner. */
export const factsBox = facts => (facts?.min_mm && facts.bbox_mm ? { min: facts.min_mm, size: facts.bbox_mm } : null);

/**
 * Whether the camera refits from `previous` to `next` framing: always for the first model;
 * otherwise only when any side changes by more than `threshold` of the old largest side, or
 * the centre moves by more than `threshold` of the old radius. Rebuilds that add a hole or a
 * fillet keep the view still.
 */
export function shouldRefit(previous, next, threshold = REFIT_THRESHOLD) {
  if (!next) return false;
  if (!previous) return true;
  const scale = Math.max(...previous.size, 1);
  if (next.size.some((value, i) => Math.abs(value - previous.size[i]) > threshold * scale)) return true;
  const moved = Math.hypot(...next.center.map((value, i) => value - previous.center[i]));
  return moved > threshold * previous.radius;
}

/** The framing to use: the previous one unless shouldRefit() says the bounds really changed. */
export const stableFraming = (previous, next, threshold = REFIT_THRESHOLD) => (shouldRefit(previous, next, threshold) ? next : previous);

// --- edge flash -----------------------------------------------------------------------------

/**
 * The edge flash when the shown GLB changes: { from, until }, or null. No flash for the first
 * model on screen, for the same model again, or with reduced motion.
 */
export function flashFor(previousSha, nextSha, { now, reducedMotion = false }) {
  if (reducedMotion || !previousSha || !nextSha || previousSha === nextSha) return null;
  return { from: now, until: now + FLASH_MS };
}

// --- GLB cache and stale responses ------------------------------------------------------------

/** An in-memory LRU of verified GLB bytes by sha256 (at most `limit`). */
export function createGlbCache(limit = GLB_CACHE_SIZE) {
  const entries = new Map();
  return {
    get(sha) {
      if (!entries.has(sha)) return undefined;
      const value = entries.get(sha);
      entries.delete(sha);
      entries.set(sha, value);
      return value;
    },
    set(sha, value) {
      entries.delete(sha);
      entries.set(sha, value);
      while (entries.size > limit) entries.delete(entries.keys().next().value);
    },
    has: sha => entries.has(sha),
    keys: () => [...entries.keys()],
    get size() { return entries.size; },
  };
}

/**
 * The stale-response rule: every fetch takes a ticket; a response is used only when its ticket
 * is the newest one issued (a newer request is pending or done, so the older bytes are dropped).
 */
export function createLoadSequencer() {
  let latest = 0;
  return {
    next(sha) { latest += 1; return { seq: latest, sha }; },
    accept: ticket => !!ticket && ticket.seq === latest,
    cancel() { latest += 1; },
  };
}

/** The artifact matches the snapshot's reference (checked before the bytes' own digest). */
export function artifactMatches(artifact, wanted) {
  return !!artifact && !!wanted && artifact.sha256 === wanted.sha256 && artifact.bytes === wanted.bytes;
}
