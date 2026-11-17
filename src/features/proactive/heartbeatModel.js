// Heartbeat (S7.3, docs/PROACTIVE.md "Heartbeat"): pure logic for Preferences > Assistant's
// "Standing instructions" row. The payload shapes are backend/transport/heartbeat.py.
// Tested in tests/test_heartbeat_model.mjs.

export const HEARTBEAT_LABEL = 'Standing instructions';
export const HEARTBEAT_HELP = 'JARVIS reads these every 30 minutes when something is waiting, to decide what to tell you. Leave it empty to use the defaults.';
export const HEARTBEAT_MAX = 4000;
export const HEARTBEAT_ROWS = 8;
export const HEARTBEAT_TOO_LONG = 'Keep standing instructions under 4,000 characters.';
export const HEARTBEAT_SAVED = 'Saved.';
export const HEARTBEAT_LOAD_ERROR = "Standing instructions couldn't be loaded. Try again.";

// Outcomes that reached the owner (backend services/heartbeat.py TOLD).
const TOLD = new Set(['spoken', 'card', 'overlay', 'balloon', 'phone', 'remote', 'alert']);
const ACTIONS = new Set(['notify', 'speak', 'run_routine', 'none']);

/** The saved length: the core stores \n line ends. */
export const savedLength = text => (typeof text === 'string' ? text.replace(/\r\n?/g, '\n').length : 0);

/** '' when the text can be saved, else the message to show. */
export function heartbeatTextError(text) {
  return savedLength(text) > HEARTBEAT_MAX ? HEARTBEAT_TOO_LONG : '';
}

/** `heartbeat_get` / `heartbeat_save` responses, validated: {text, lastRun, lastActions}. */
export function normalizeHeartbeat(response) {
  if (!response || typeof response !== 'object' || typeof response.text !== 'string') return null;
  const lastRun = typeof response.last_run === 'string' && !Number.isNaN(Date.parse(response.last_run))
    ? response.last_run : null;
  const lastActions = Array.isArray(response.last_actions)
    ? response.last_actions.filter(entry => entry && typeof entry === 'object' && ACTIONS.has(entry.action))
      .map(entry => ({ action: entry.action, outcome: typeof entry.outcome === 'string' ? entry.outcome : null }))
    : [];
  return { text: response.text, lastRun, lastActions };
}

/** How many of the last check's actions reached the owner. */
export const toldCount = lastActions => (Array.isArray(lastActions)
  ? lastActions.filter(entry => entry && TOLD.has(entry.outcome)).length : 0);

/** "Last check: 14:30 · told you 1 thing" (24-hour local time). */
export function lastCheckLine(lastRun, lastActions, timeZone) {
  if (!lastRun) return 'Last check: not yet';
  const at = new Date(lastRun);
  if (Number.isNaN(at.getTime())) return 'Last check: not yet';
  const clock = at.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, ...(timeZone ? { timeZone } : {}) });
  const told = toldCount(lastActions);
  const tail = told === 0 ? 'nothing to tell' : `told you ${told} ${told === 1 ? 'thing' : 'things'}`;
  return `Last check: ${clock} · ${tail}`;
}
