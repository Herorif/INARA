// "What JARVIS did" (S4.3): pure logic for the flight recorder list in the Activity drawer.
// The trace shape is backend/services/trace.py (docs/DIAGNOSTICS.md). Tested without React
// in tests/test_activity_model.mjs.

export const TRACE_LIMIT = 200;
export const FIRST_PAGE = 50;
export const LIVE_FETCH = 5;

export const EMPTY_TEXT = 'Nothing yet. JARVIS lists each request here: the tools it used and how long each took.';
export const KEPT_NOTE = 'Kept in memory for the last 200 turns. Message text is not stored unless you turn it on in Preferences.';
export const LOAD_ERROR = "The activity list couldn't be loaded. Try again.";
export const CLEAR_ERROR = "The list couldn't be cleared. Try again.";

const ORIGINS = { chat: 'CHAT', voice: 'VOICE', phone: 'PHONE', vision: 'VISION' };
const KINDS = new Set(['wake', 'speech_in', 'model', 'tool', 'approval', 'speech_out']);

const num = value => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const str = value => (typeof value === 'string' && value ? value : null);

export function originLabel(origin) {
  return ORIGINS[origin] || String(origin || '').toUpperCase() || 'TURN';
}

/** The outcome dot: tone (ok | warn | danger | idle) and its label. */
export function outcomeView(outcome) {
  switch (outcome) {
    case 'ok': return { tone: 'ok', label: 'Done', quiet: true };
    case 'budget': return { tone: 'warn', label: 'Out of time', quiet: false };
    case 'error': return { tone: 'danger', label: 'Failed', quiet: false };
    case 'cancelled': return { tone: 'idle', label: 'Cancelled', quiet: false };
    case 'interrupted': return { tone: 'idle', label: 'Interrupted', quiet: false };
    default: return { tone: 'idle', label: 'Unknown', quiet: false };
  }
}

/** "420 ms", "2.4 s", "1 min 5 s"; null when unknown. */
export function formatDuration(ms) {
  const value = num(ms);
  if (value === null || value < 0) return null;
  if (Math.round(value) < 1000) return `${Math.round(value)} ms`;
  if (value < 59950) return `${(value / 1000).toFixed(1)} s`;
  const seconds = Math.round(value / 1000);
  const minutes = Math.floor(seconds / 60), rest = seconds % 60;
  return rest ? `${minutes} min ${rest} s` : `${minutes} min`;
}

/** A start offset on the waterfall: "+0.0 s", "+1.2 s", "−3.4 s" (true minus sign). */
export function formatOffset(ms) {
  const value = num(ms);
  if (value === null) return null;
  const sign = value < 0 ? '−' : '+';
  return `${sign}${(Math.abs(value) / 1000).toFixed(1)} s`;
}

/** "$0.004"; "<$0.001" for a priced turn that cost less; null when not priced. */
export function formatCost(usd) {
  const value = num(usd);
  if (value === null || value < 0) return null;
  if (value === 0) return '$0.000';
  if (value < 0.001) return '<$0.001';
  if (value < 1) return `$${value.toFixed(3)}`;
  return `$${value.toFixed(2)}`;
}

/** Local HH:MM from the ISO start time. */
export function formatTime(iso) {
  const date = new Date(iso);
  if (!str(iso) || Number.isNaN(date.getTime())) return '--:--';
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

export function formatTokens(tokens) {
  const input = num(tokens?.input), output = num(tokens?.output);
  if (input === null && output === null) return null;
  const n = value => (value === null ? '—' : value.toLocaleString('en-US'));
  return `${n(input)} in / ${n(output)} out`;
}

/** Tool names in the order they ran, joined by " → ", or "Answered" when none ran. */
export function summaryText(trace) {
  const tools = (trace?.spans || []).filter(span => span.kind === 'tool' && str(span.name)).map(span => span.name);
  return tools.length ? tools.join(' → ') : 'Answered';
}

function normalizeSpan(raw) {
  if (!raw || typeof raw !== 'object' || !KINDS.has(raw.kind)) return null;
  return { kind: raw.kind, name: str(raw.name), start_ms: num(raw.start_ms), ms: num(raw.ms), outcome: str(raw.outcome) };
}

/** A defensive copy of one trace from the core, or null when it is unusable. */
export function normalizeTrace(raw) {
  if (!raw || typeof raw !== 'object' || !str(raw.id)) return null;
  const tokens = raw.tokens && typeof raw.tokens === 'object' ? { input: num(raw.tokens.input), output: num(raw.tokens.output) } : null;
  return {
    id: raw.id,
    origin: str(raw.origin) || 'chat',
    started_at: str(raw.started_at),
    provider: str(raw.provider),
    model: str(raw.model),
    effort: str(raw.effort),
    outcome: str(raw.outcome),
    total_ms: num(raw.total_ms),
    first_token_ms: num(raw.first_token_ms),
    spans: Array.isArray(raw.spans) ? raw.spans.map(normalizeSpan).filter(Boolean) : [],
    tokens,
    cost_usd: num(raw.cost_usd),
    approvals: Array.isArray(raw.approvals)
      ? raw.approvals.filter(item => item && str(item.tool)).map(item => ({ tool: item.tool, asked_ms: num(item.asked_ms), answer: str(item.answer) }))
      : [],
    request_text: str(raw.request_text),
    answer_text: str(raw.answer_text),
  };
}

const startedAt = trace => {
  const time = trace.started_at ? Date.parse(trace.started_at) : NaN;
  return Number.isNaN(time) ? -Infinity : time;
};

/**
 * Merge incoming traces into the list by id (an incoming trace replaces the row with the
 * same id: a voice brain turn is announced twice), newest first, at most 200.
 */
export function mergeTraces(list, incoming) {
  const byId = new Map((list || []).map(trace => [trace.id, trace]));
  for (const raw of incoming || []) {
    const trace = normalizeTrace(raw);
    if (trace) byId.set(trace.id, trace);
  }
  const order = new Map((list || []).map((trace, index) => [trace.id, index]));
  return [...byId.values()]
    .sort((a, b) => startedAt(b) - startedAt(a) || (order.get(a.id) ?? -1) - (order.get(b.id) ?? -1))
    .slice(0, TRACE_LIMIT);
}

const KIND_LABEL = { wake: 'wake', speech_in: 'speech in', model: 'model', tool: 'tool', approval: 'approval', speech_out: 'speech out' };
const KIND_ROLE = { model: 'system', tool: 'acting', approval: 'warn', wake: 'speech', speech_in: 'speech', speech_out: 'speech' };

/**
 * Waterfall geometry on one shared axis from the earliest start (negative for voice wake
 * and speech spans) to the latest end (at least the turn's total). left/width are percent.
 */
export function waterfall(trace, { minWidth = 0.6 } = {}) {
  const spans = trace?.spans || [];
  const timed = spans.filter(span => span.start_ms !== null);
  const total = num(trace?.total_ms) ?? 0;
  const min = Math.min(0, ...timed.map(span => span.start_ms));
  const max = Math.max(total, 0, ...timed.map(span => span.start_ms + Math.max(0, span.ms ?? 0)));
  const range = Math.max(1, max - min);
  const pct = value => (value / range) * 100;
  const rows = spans.map(span => {
    const label = span.name ? `${KIND_LABEL[span.kind]} · ${span.name}` : KIND_LABEL[span.kind];
    const base = { kind: span.kind, role: KIND_ROLE[span.kind], label, offset: formatOffset(span.start_ms), duration: formatDuration(span.ms), outcome: span.outcome };
    if (span.start_ms === null) return { ...base, bar: null };
    const left = pct(span.start_ms - min);
    const width = Math.min(100 - left, Math.max(minWidth, pct(Math.max(0, span.ms ?? 0))));
    return { ...base, bar: { left, width } };
  });
  return { min, max, range, zero: min < 0 ? pct(-min) : null, rows };
}

const ANSWER_TEXT = { approved: 'approved', denied: 'denied', timeout: 'no answer' };

/** "Asked: place_task_call — approved after 6.2 s" for each approval. */
export function approvalLines(trace) {
  const spans = (trace?.spans || []).filter(span => span.kind === 'approval');
  const used = new Set();
  return (trace?.approvals || []).map(item => {
    const index = spans.findIndex((span, i) => !used.has(i) && span.name === item.tool && (item.asked_ms === null || span.start_ms === null || span.start_ms === item.asked_ms));
    const fallback = index < 0 ? spans.findIndex((span, i) => !used.has(i) && span.name === item.tool) : index;
    if (fallback >= 0) used.add(fallback);
    const after = fallback >= 0 ? formatDuration(spans[fallback].ms) : null;
    const answer = ANSWER_TEXT[item.answer] || 'no answer';
    return `Asked: ${item.tool} — ${answer}${after ? ` after ${after}` : ''}`;
  });
}

/** Everything one row shows, collapsed and expanded. */
export function traceRow(trace) {
  const brain = [trace.provider, trace.model, trace.effort].filter(Boolean).join(' · ');
  return {
    id: trace.id,
    time: formatTime(trace.started_at),
    origin: originLabel(trace.origin),
    summary: summaryText(trace),
    total: formatDuration(trace.total_ms) || '—',
    outcome: outcomeView(trace.outcome),
    request: trace.request_text,
    brain: brain || null,
    tokens: formatTokens(trace.tokens),
    cost: formatCost(trace.cost_usd),
    approvals: approvalLines(trace),
  };
}

/** Whether "Load more" can fetch older turns. */
export function canLoadMore(count, requested) {
  return requested < TRACE_LIMIT && count >= requested;
}
