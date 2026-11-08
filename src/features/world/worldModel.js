/**
 * World view (docs/WORLD_VIEW.md): pure helpers for the World page. The core's
 * `world_status`, `world_tour` and `world_view` payloads are validated here; anything the
 * core would never send reads as null.
 */

export const STATES = ['not_installed', 'stopped', 'starting', 'ready', 'error'];
export const REASONS = ['node_missing', 'root_missing', 'dist_missing'];
/** The page reports in this often while it is open (the core counts it closed after 120 s). */
export const HEARTBEAT_MS = 30_000;
export const MAX_VIEWS = 4;
const VIEW_ID = /^[0-9a-f]{32}$/;
const NO_TOUR = Object.freeze({ active: false, title: null, caption: null });

/** The setup script's steps (scripts/install-world-view.ps1), for "How to set it up". */
export const SETUP_STEPS = [
  'Open PowerShell in the JARVIS folder.',
  'Run powershell -ExecutionPolicy Bypass -File scripts\\install-world-view.ps1 -WhatIf to see each step without changing anything.',
  'Run it again without -WhatIf. It downloads Node 24 and checks its SHA-256, fetches God\'s Eye View at a pinned commit, then installs and builds it in your tools folder.',
  'Open World again. The globe starts on this PC.',
];

const text = (value, limit) => (typeof value === 'string' && value.trim() ? value.trim().slice(0, limit) : null);
const port = value => (Number.isInteger(value) && value >= 1024 && value <= 65535 && value !== 8000 ? value : null);

export function normalizeTour(raw) {
  if (!raw || typeof raw !== 'object' || typeof raw.active !== 'boolean') return null;
  if (!raw.active) return NO_TOUR;
  return { active: true, title: text(raw.title, 80), caption: text(raw.caption, 400) };
}

/** A validated world_status, or null. */
export function normalizeStatus(raw) {
  if (!raw || typeof raw !== 'object' || !STATES.includes(raw.state)) return null;
  const value = port(raw.port);
  if (value === null || typeof raw.enabled !== 'boolean') return null;
  const diagnostics = raw.diagnostics && typeof raw.diagnostics === 'object' ? {
    exitCode: Number.isInteger(raw.diagnostics.exit_code) ? raw.diagnostics.exit_code : null,
    stderr: typeof raw.diagnostics.stderr === 'string' ? raw.diagnostics.stderr.slice(-1500) : '',
  } : null;
  return {
    state: raw.state,
    reason: REASONS.includes(raw.reason) ? raw.reason : null,
    message: text(raw.message, 200),
    port: value,
    enabled: raw.enabled,
    tour: normalizeTour(raw.tour) || NO_TOUR,
    diagnostics,
  };
}

/** A world_view request from the core: {id, view, title}, or null. */
export function normalizeViewRequest(raw) {
  if (!raw || typeof raw !== 'object' || typeof raw.id !== 'string' || !VIEW_ID.test(raw.id)) return null;
  if (!raw.view || typeof raw.view !== 'object' || Array.isArray(raw.view)) return null;
  return { id: raw.id, view: raw.view, title: text(raw.title, 80) };
}

/** The embedded globe's origin and address, from the status port (loopback only). */
export const embedOrigin = value => (port(value) === null ? null : `http://127.0.0.1:${value}`);
export const embedUrl = value => (embedOrigin(value) && `${embedOrigin(value)}/?embed=1`);
/** "Open in browser": the full app, not embed mode. */
export const appUrl = value => (embedOrigin(value) && `${embedOrigin(value)}/`);

/**
 * What the page shows. `status` is the normalised world_status (null before the first
 * answer), `tour` the latest world_tour, `failure` a start/stop RPC error message.
 * phase: not_installed | starting | ready | error.
 */
export function pageView({ status, tour, failure = null }) {
  const current = tour || status?.tour || NO_TOUR;
  let phase = 'starting';
  if (failure) phase = 'error';
  else if (status?.state === 'not_installed') phase = 'not_installed';
  else if (status?.state === 'ready') phase = 'ready';
  else if (status?.state === 'error') phase = 'error';
  const driving = phase === 'ready' && current.active;
  const chip = {
    not_installed: { label: 'Not set up', tone: 'idle' },
    starting: { label: 'Starting', tone: 'accent' },
    ready: driving ? { label: 'JARVIS is driving', tone: 'accent' } : { label: 'Ready', tone: 'ok' },
    error: { label: 'Error', tone: 'danger' },
  }[phase];
  const message = phase === 'error'
    ? failure || status?.message || 'World view couldn\'t start.'
    : phase === 'starting' ? 'Starting the globe on this PC…' : null;
  return {
    phase,
    chip,
    message,
    frameUrl: phase === 'ready' ? embedUrl(status.port) : null,
    origin: status ? embedOrigin(status.port) : null,
    canOpen: phase === 'ready',
    canStop: phase === 'ready' || (phase === 'starting' && status?.state === 'starting'),
    tourBar: current.active ? { label: `TOUR · ${current.title || 'World'}`, caption: current.caption || '' } : null,
  };
}

/** God's Eye View's view-applied steps, bounded to what the core accepts. */
export function cleanSteps(steps) {
  if (!Array.isArray(steps)) return [];
  return steps.slice(0, 64).flatMap(item => {
    if (!item || typeof item !== 'object' || typeof item.step !== 'string' || typeof item.ok !== 'boolean') return [];
    const step = item.step.trim().slice(0, 64);
    if (!step) return [];
    const error = typeof item.error === 'string' && item.error.trim() ? item.error.trim().slice(0, 300) : null;
    return [error ? { step, ok: item.ok, error } : { step, ok: item.ok }];
  });
}
