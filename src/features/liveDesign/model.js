// Pure model for the Live design panel (no DOM, no React, no three.js): snapshot validation,
// the renderer port of the core's bounds(), the reveal queue, highlights, ghosts and every
// label the panel shows. node:test checks each rule (tests/test_live_design_panel.mjs).
// The core is the authority (backend/services/cad_design.py, docs/LIVE_DESIGN.md).

export const MAX_OBJECTS = 8;
export const MAX_STEPS = 40;
/** Canvas width (px) from which the conversation and the panel sit side by side. */
// 900 keeps the split on the owner's 1440 px window with the context inspector open (a
// 972 px canvas); the two minimums (360 + 420) still fit.
export const WIDE_MIN_PX = 900;
/** New parts appear one at a time, this far apart (ms). */
export const REVEAL_GAP_MS = 400;
/** Each new part fades in and drops into place over this long (ms). */
export const REVEAL_MS = 300;
/** How far a new part drops into place (mm). */
export const DROP_MM = 8;
/** New or changed parts keep accent edges this long (ms); the last 300 ms fade back. */
export const HIGHLIGHT_MS = 1200;
export const HIGHLIGHT_FADE_MS = 300;
/** Dashed ghosts of a change's old parts clear at the next step, or after this long (ms). */
export const GHOST_MS = 6000;
/** Inline action errors stay this long (ms). */
export const ERROR_MS = 6000;

export const STATUSES = Object.freeze(['draft', 'building', 'saved', 'failed']);
export const SHAPES = Object.freeze(['box', 'bracket', 'enclosure']);
export const MATERIALS = Object.freeze(['cyan', 'titanium', 'amber', 'ceramic']);
export const PHASES = Object.freeze(['Building geometry', 'Checking the solid', 'Saving exports']);
const KINDS = ['add', 'change', 'unsupported'];
const WHO = ['jarvis', 'owner'];
const LIMITS = Object.freeze({ id: 64, project: 120, name: 60, title: 80, detail: 160, state: 32, error: 300 });

// --- text ---------------------------------------------------------------------------------

// Control characters become spaces (as the core's clean_text), then whitespace collapses.
// eslint-disable-next-line no-control-regex
const CONTROL = /[\u0000-\u001f\u007f-\u009f]/g;
const highSurrogate = code => code >= 0xd800 && code <= 0xdbff;

/** At most `limit` UTF-16 units, ending in "…" when cut; never splits a surrogate pair. */
export function clipText(value, limit) {
  if (value.length <= limit) return value;
  let end = limit - 1;
  if (highSurrogate(value.charCodeAt(end - 1))) end -= 1;
  return `${value.slice(0, end).trimEnd()}…`;
}

const text = (value, limit) => (typeof value === 'string' ? clipText(value.replace(CONTROL, ' ').replace(/\s+/g, ' ').trim(), limit) : null);

/** The core's number(): rounded to 2 decimals, no trailing zeros ("160", "40.5"). */
export function formatNumber(value) {
  const rounded = Math.round(Number(value) * 100) / 100;
  return String(Object.is(rounded, -0) ? 0 : rounded);
}

/** "W × D × H" of three numbers. */
export const sizeText = values => values.map(formatNumber).join(' × ');
const plural = (count, word) => `${count} ${word}${count === 1 ? '' : 's'}`;

// --- bounds: a port of the core's transform() and bounds() ---------------------------------

/** Scale, then X/Y/Z rotation in degrees, then translation (creative/scene.py). */
export function transformPoint(point, part) {
  const scale = part.scale || [1, 1, 1], rotation = part.rotation || [0, 0, 0], position = part.position || [0, 0, 0];
  let [x, y, z] = point.map((value, i) => value * scale[i]);
  rotation.forEach((angle, axis) => {
    const c = Math.cos(angle * Math.PI / 180), s = Math.sin(angle * Math.PI / 180);
    if (axis === 0) [y, z] = [c * y - s * z, s * y + c * z];
    else if (axis === 1) [x, z] = [c * x + s * z, -s * x + c * z];
    else [x, y] = [c * x - s * y, s * x + c * y];
  });
  return [x + position[0], y + position[1], z + position[2]];
}

/** The placed parts' corners: { min: [x, y, z], max: [x, y, z] } in mm, or null with no parts. */
export function extent(parts) {
  if (!Array.isArray(parts) || !parts.length) return null;
  const min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity];
  for (const part of parts) {
    for (const x of [0, part.width]) for (const y of [0, part.depth]) for (const z of [0, part.height]) {
      transformPoint([x, y, z], part).forEach((value, i) => { min[i] = Math.min(min[i], value); max[i] = Math.max(max[i], value); });
    }
  }
  return { min, max };
}

/** Overall width, depth and height in mm, rounded to 0.1 mm (the core's bounds()). */
export function bounds(parts) {
  const box = extent(parts);
  return box ? box.max.map((value, i) => Math.round((value - box.min[i]) * 10) / 10) : [0, 0, 0];
}

/** Camera framing for the parts: the centre (CAD axes, mm), the radius and a key that changes with either. */
export function framing(parts) {
  const box = extent(parts);
  if (!box) return null;
  const center = box.min.map((value, i) => (value + box.max[i]) / 2);
  const size = box.max.map((value, i) => value - box.min[i]);
  const radius = Math.max(Math.hypot(...size) / 2, 1);
  return { center, radius, floor: box.min[2], key: [...center, ...size].map(value => Math.round(value * 10) / 10).join(':') };
}

// --- snapshot validation ------------------------------------------------------------------

const finite = (value, low, high) => typeof value === 'number' && Number.isFinite(value) && value >= low && value <= high;
const vector = (value, low, high) => Array.isArray(value) && value.length === 3 && value.every(item => finite(item, low, high));
const index = value => Number.isInteger(value) && value >= 0 && value < MAX_OBJECTS;

/** One scene part, or null when any field is out of contract. */
export function sanitizePart(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const name = text(raw.name, LIMITS.name);
  if (!name || !SHAPES.includes(raw.shape) || !MATERIALS.includes(raw.material)) return null;
  if (!['width', 'depth', 'height'].every(key => finite(raw[key], 1, 1000)) || !finite(raw.thickness, 0.5, 100)) return null;
  const position = raw.position ?? [0, 0, 0], rotation = raw.rotation ?? [0, 0, 0], scale = raw.scale ?? [1, 1, 1];
  if (!vector(position, -2000, 2000) || !vector(rotation, -360, 360) || !vector(scale, 0.1, 5)) return null;
  return {
    name, shape: raw.shape, width: raw.width, depth: raw.depth, height: raw.height, thickness: raw.thickness,
    position: [...position], rotation: [...rotation], scale: [...scale], material: raw.material,
  };
}

function sanitizeStep(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const { n, who, kind } = raw;
  if (!Number.isInteger(n) || n < 1 || !WHO.includes(who) || !KINDS.includes(kind)) return null;
  const title = text(raw.title, LIMITS.title), detail = text(raw.detail ?? '', LIMITS.detail);
  if (title === null || detail === null) return null;
  const indices = value => (Array.isArray(value) ? value.filter(index).slice(0, MAX_OBJECTS) : []);
  const removed = Array.isArray(raw.removed) ? raw.removed.slice(0, MAX_OBJECTS).map(sanitizePart).filter(Boolean) : [];
  const before = {};
  if (raw.before && typeof raw.before === 'object' && !Array.isArray(raw.before)) {
    for (const [key, value] of Object.entries(raw.before).slice(0, MAX_OBJECTS)) {
      const part = /^[0-7]$/.test(key) ? sanitizePart(value) : null;
      if (part) before[key] = part;
    }
  }
  return { n, who, kind, title, detail, added: indices(raw.added), changed: indices(raw.changed), removed, before, undoable: raw.undoable === true };
}

function sanitizeJob(raw) {
  if (raw === null || raw === undefined) return null;
  if (typeof raw !== 'object' || Array.isArray(raw)) return undefined;
  const requestId = text(raw.request_id, LIMITS.id), state = text(raw.state, LIMITS.state), phase = text(raw.phase, LIMITS.state);
  if (!requestId || !state || !phase) return undefined;
  return { request_id: requestId, state, phase, error: typeof raw.error === 'string' ? text(raw.error, LIMITS.error) : null };
}

/**
 * One `cad_design` snapshot (or an RPC reply): `{ design: null }`, `{ design }` with only the
 * contract fields (at most 8 parts and the newest 40 steps, strings clipped), or null to drop it.
 */
export function sanitizeDesignSnapshot(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw) || !('design' in raw)) return null;
  const design = raw.design;
  if (design === null) return { design: null };
  if (!design || typeof design !== 'object' || Array.isArray(design)) return null;
  const id = typeof design.id === 'string' && design.id.length <= LIMITS.id && /^[0-9a-f-]+$/i.test(design.id) ? design.id : null;
  const name = text(design.name, LIMITS.name), project = text(design.project, LIMITS.project);
  if (!id || !name || project === null || !STATUSES.includes(design.status)) return null;
  const recipe = design.recipe;
  if (!recipe || typeof recipe !== 'object' || recipe.shape !== 'scene' || !Array.isArray(recipe.objects)) return null;
  if (recipe.objects.length < 1 || recipe.objects.length > MAX_OBJECTS) return null;
  const objects = recipe.objects.map(sanitizePart);
  if (objects.some(part => !part)) return null;
  if (!Array.isArray(design.steps)) return null;
  const steps = design.steps.slice(-MAX_STEPS).map(sanitizeStep);
  if (steps.some(step => !step)) return null;
  const job = sanitizeJob(design.job);
  if (job === undefined) return null;
  return {
    design: {
      id, project, name, status: design.status,
      recipe: { name: text(recipe.name, LIMITS.name) || name, shape: 'scene', engine: 'offline', objects },
      steps, job, updated: finite(design.updated, 0, Number.MAX_SAFE_INTEGER) ? design.updated : 0,
    },
  };
}

/** The newest step number (0 with none). */
export const latestStep = design => (design?.steps?.length ? Math.max(...design.steps.map(step => step.n)) : 0);

/**
 * Store patch for an incoming snapshot, or null to drop it. The first snapshot since the
 * page loaded marks every step seen, so a reload never replays the reveal.
 */
export function snapshotPatch(state, raw) {
  const clean = sanitizeDesignSnapshot(raw);
  if (!clean) return null;
  const patch = { liveDesign: clean.design, liveDesignReady: true };
  if (!state.liveDesignReady && clean.design) patch.liveDesignSeen = { id: clean.design.id, n: latestStep(clean.design) };
  return patch;
}

/** Steps the panel has not shown yet: after the last seen step, or all of a new design. */
export function unseenSteps(design, seen) {
  if (!design) return [];
  const after = seen && seen.id === design.id ? seen.n : 0;
  return design.steps.filter(step => step.n > after);
}

/** Banner on another page or with a feature open: the panel is out of sight and has news. */
export function bannerVisible({ design, seen, panelVisible }) {
  if (!design || panelVisible) return false;
  return !seen || seen.id !== design.id || latestStep(design) > seen.n;
}

// --- reveal, highlight and ghosts -----------------------------------------------------------

export const emptyTimeline = (id = null) => ({ id, reveal: [], highlight: {}, ghost: null });
const easeOut = value => 1 - (1 - value) ** 3;
const clamp = value => Math.min(1, Math.max(0, value));

/**
 * Reveal queue for a batch of unseen steps: every part of each new "add" step, one at a time,
 * REVEAL_GAP_MS apart from `start`. None with reduced motion, and none when a change follows
 * the adds in the same batch (its indices would no longer match).
 */
export function revealQueue(batch, objectCount, { start, reducedMotion = false }) {
  if (reducedMotion) return [];
  const firstAdd = batch.findIndex(step => step.kind === 'add');
  if (firstAdd < 0 || batch.slice(firstAdd).some(step => step.kind === 'change')) return [];
  const items = [];
  for (const step of batch) {
    if (step.kind !== 'add') continue;
    for (const part of step.added) if (part < objectCount) items.push({ n: step.n, index: part, at: start + items.length * REVEAL_GAP_MS });
  }
  return items;
}

/** Whether a reveal is still running at `now`, and how many of its parts have started ("k of n"). */
export function revealProgress(queue, now) {
  if (!queue?.length) return { active: false, k: 0, n: 0, step: null };
  const started = queue.filter(item => item.at <= now);
  const active = now < queue[queue.length - 1].at + REVEAL_MS;
  return { active, k: Math.max(1, started.length), n: queue.length, step: (started[started.length - 1] || queue[0]).n };
}

/** Steps not yet revealed at `now` (their rows wait until their part appears). */
export const pendingSteps = (queue, now) => new Set((queue || []).filter(item => item.at > now).map(item => item.n));

/** A part's reveal motion at `now`: opacity 0..1 and its drop (mm still to fall). */
export function partMotion(at, now) {
  if (at === undefined || at === null) return { opacity: 1, drop: 0 };
  if (now < at) return { opacity: 0, drop: DROP_MM };
  const eased = easeOut(clamp((now - at) / REVEAL_MS));
  return { opacity: eased, drop: DROP_MM * (1 - eased) };
}

/** Accent strength 0..1 of a part's edges: full, then fading back over the last 300 ms. */
export function highlightMix(until, now, from = -Infinity) {
  if (until === undefined || until === null || now < from || now >= until) return 0;
  return clamp((until - now) / HIGHLIGHT_FADE_MS);
}

/** Dashed ghosts for a batch: the newest change's old parts and removed parts; null clears them. */
export function ghostFor(batch, now) {
  const change = [...batch].reverse().find(step => step.kind === 'change');
  if (!change) return null;
  const objects = [...Object.values(change.before), ...change.removed];
  return objects.length ? { n: change.n, objects, until: now + GHOST_MS } : null;
}

/** The ghost still shows: within its 6 s, and its change is still in the design (not undone). */
export const ghostAlive = (ghost, design, now) => !!ghost && now < ghost.until && !!design?.steps?.some(step => step.n === ghost.n);

/**
 * The next timeline after a batch of unseen steps: the reveal queue (continuing a running
 * reveal of the same design), accent highlights and ghosts.
 */
export function nextTimeline(previous, batch, design, { now, reducedMotion = false }) {
  if (!batch.length) return previous;
  const same = previous?.id === design.id;
  const base = same ? previous : emptyTimeline(design.id);
  const running = base.reveal.length && now < base.reveal[base.reveal.length - 1].at + REVEAL_MS;
  const recipeChange = batch.some(step => step.kind === 'change');
  const kept = running && !recipeChange ? base.reveal : [];
  const start = kept.length ? Math.max(now, kept[kept.length - 1].at + REVEAL_GAP_MS) : now;
  const added = revealQueue(batch, design.recipe.objects.length, { start, reducedMotion });
  const reveal = [...kept, ...added];
  const highlight = Object.fromEntries(Object.entries(same ? base.highlight : {}).filter(([, item]) => item.until > now));
  for (const item of added) highlight[item.index] = { from: item.at, until: item.at + HIGHLIGHT_MS };
  if (!added.length) {
    const newest = [...batch].reverse().find(step => step.kind !== 'unsupported');
    if (newest) for (const part of [...newest.added, ...newest.changed]) highlight[part] = { from: now, until: now + HIGHLIGHT_MS };
  }
  return { id: design.id, reveal, highlight, ghost: ghostFor(batch, now) };
}

// --- labels -----------------------------------------------------------------------------------

/** Header chip: { text, tone } with tone accent | muted | warn | ok | danger. */
export function chipView({ status, reveal = null, approval = false }) {
  if (approval) return { text: 'Needs your approval', tone: 'warn' };
  if (reveal?.active) return { text: `Drafting · ${reveal.k} of ${reveal.n}`, tone: 'accent' };
  if (status === 'building') return { text: 'Building', tone: 'accent' };
  if (status === 'saved') return { text: 'Saved', tone: 'ok' };
  if (status === 'failed') return { text: 'Failed', tone: 'danger' };
  return { text: 'Draft · not built', tone: 'muted' };
}

/** Which footer shows: offline | approval | building | saved | failed | draft. */
export function footerKind({ connected, status, approval = false }) {
  if (!connected) return 'offline';
  if (approval) return 'approval';
  if (status === 'building' || status === 'saved' || status === 'failed') return status;
  return 'draft';
}

/** The pending `build_live_design` approval for this design, or null. */
export function matchingApproval(queue, designId) {
  if (!designId || !Array.isArray(queue)) return null;
  return queue.find(request => request?.tool === 'build_live_design' && request.args?.design_id === designId) || null;
}

/** The global approval popup's queue: the visible panel answers its own design's build. */
export function popupQueue(queue, { panelVisible, designId }) {
  if (!panelVisible || !designId) return queue;
  return queue.filter(request => !(request?.tool === 'build_live_design' && request.args?.design_id === designId));
}

/** The inline approval card: the core's pending request first, else the panel's own Build it. */
export function approvalCard({ request, confirming, status }) {
  if (request) return { source: 'request', id: request.id };
  if (confirming && (status === 'draft' || status === 'failed')) return { source: 'local', id: null };
  return null;
}

/** Callout chip on the canvas: { text, tone } with tone primary | warn | ok, or null. */
export function calloutView(design, { step: stepN = null } = {}) {
  if (!design) return null;
  if (design.status === 'saved' && design.job?.request_id) return { text: `Saved · revision ${design.job.request_id.slice(0, 8)}`, tone: 'ok' };
  const step = (stepN !== null && design.steps.find(item => item.n === stepN)) || design.steps[design.steps.length - 1];
  if (!step) return null;
  if (step.kind === 'add') {
    const name = step.title.replace(/^\+\s*/, '');
    const part = design.recipe.objects[step.added[0]];
    return { text: `+ ${name}${part ? ` · ${sizeText([part.width, part.depth, part.height])} mm` : ''}`, tone: 'primary' };
  }
  if (step.kind === 'unsupported') return { text: clipText(step.detail, 72), tone: 'warn' };
  return { text: clipText(step.detail, 72), tone: 'primary' };
}

/** Bottom-left HUD line on the canvas. */
export function hudLine(status) {
  if (status === 'building') return 'Building on this PC';
  if (status === 'saved') return 'Saved geometry · validated';
  return 'Draft blockout · not built';
}

/** The build phase 1..3 from the job: queued or building, validating, saving or blender. */
export function buildPhase(job) {
  const phase = job?.phase;
  if (phase === 'validating') return 2;
  if (phase === 'saving' || phase === 'blender') return 3;
  return 1;
}

/** The three build rows: done (✓ in ok), active (text-1) or pending (text-3). */
export const phaseRows = job => {
  const current = buildPhase(job);
  return PHASES.map((label, i) => ({ label, state: i + 1 < current ? 'done' : i + 1 === current ? 'active' : 'pending' }));
};

/** Footer summary line for a draft or a saved design. */
export function summaryLine(design, kind = 'draft') {
  const parts = design.recipe.objects.length;
  const size = sizeText(bounds(design.recipe.objects));
  return kind === 'saved' ? `${parts} closed ${parts === 1 ? 'part' : 'parts'} · ${size} mm` : `${plural(parts, 'part')} · ${size} mm · draft`;
}

/** The approval card's two lines. */
export function approvalLines(design) {
  return { title: `Build “${design.name}”?`, detail: `${plural(design.recipe.objects.length, 'part')} · STL and GLB on this PC · about 10 s` };
}

/** Header suffix when the design belongs to another project. */
export const projectNote = (design, currentProject) => (design && design.project !== (currentProject || 'temp') ? `· in ${design.project}` : '');

/** The 3D studio's working draft for a live design (one-way hand-off). */
export function studioDraft(design) {
  return {
    name: design.recipe.name, shape: 'scene', width: 80, depth: 60, height: 30, thickness: 3,
    objects: design.recipe.objects.map(part => ({ ...part, position: [...part.position], rotation: [...part.rotation], scale: [...part.scale] })),
    engine: 'offline', presentation: { camera: 'isometric', lighting: 'studio', quality: 'preview', background: 'dark' },
  };
}

/** A step row's who badge. */
export const whoLabel = who => (who === 'owner' ? 'YOU' : 'JARVIS');
