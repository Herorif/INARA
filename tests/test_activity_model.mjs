import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import {
  EMPTY_TEXT, KEPT_NOTE, TRACE_LIMIT, approvalLines, canLoadMore, formatCost, formatDuration, formatOffset, formatTime,
  formatTokens, mergeTraces, normalizeTrace, originLabel, outcomeView, summaryText, traceRow, waterfall,
} from '../src/features/activity/activityModel.js';
import { createActivityClient } from '../src/features/activity/activityClient.js';

const trace = (patch = {}) => ({
  id: 'a', origin: 'chat', started_at: '2026-11-15T09:05:00+00:00', provider: 'anthropic', model: 'claude-sonnet', effort: 'low',
  outcome: 'ok', total_ms: 2400, first_token_ms: 600, spans: [], tokens: { input: 1200, output: 80 }, cost_usd: 0.0042, approvals: [], ...patch,
});
const close = (actual, expected, label) => assert.ok(Math.abs(actual - expected) < 1e-9, `${label}: ${actual} != ${expected}`);

test('summary joins tool names in order, or says Answered', () => {
  assert.equal(summaryText(trace()), 'Answered');
  assert.equal(summaryText(trace({ spans: [
    { kind: 'model', name: 'anthropic', start_ms: 0, ms: 400 },
    { kind: 'tool', name: 'weather', start_ms: 400, ms: 300 },
    { kind: 'approval', name: 'web_search', start_ms: 700, ms: 100 },
    { kind: 'tool', name: 'web_search', start_ms: 800, ms: 900 },
  ] })), 'weather → web_search');
  assert.equal(summaryText(trace({ spans: [{ kind: 'tool', start_ms: 0, ms: 1 }] })), 'Answered');
});

test('durations, offsets, costs, tokens and times are formatted', () => {
  assert.equal(formatDuration(2400), '2.4 s');
  assert.equal(formatDuration(420), '420 ms');
  assert.equal(formatDuration(0), '0 ms');
  assert.equal(formatDuration(999.6), '1.0 s');
  assert.equal(formatDuration(59900), '59.9 s');
  assert.equal(formatDuration(65000), '1 min 5 s');
  assert.equal(formatDuration(120000), '2 min');
  assert.equal(formatDuration(null), null);
  assert.equal(formatDuration(-5), null);
  assert.equal(formatOffset(0), '+0.0 s');
  assert.equal(formatOffset(1250), '+1.3 s');
  assert.equal(formatOffset(-3400), '−3.4 s');
  assert.equal(formatOffset(null), null);
  assert.equal(formatCost(0.004), '$0.004');
  assert.equal(formatCost(0.0042), '$0.004');
  assert.equal(formatCost(0.0004), '<$0.001');
  assert.equal(formatCost(0), '$0.000');
  assert.equal(formatCost(1.5), '$1.50');
  assert.equal(formatCost(null), null);
  assert.equal(formatTokens({ input: 1200, output: 80 }), '1,200 in / 80 out');
  assert.equal(formatTokens(null), null);
  assert.equal(formatTokens({ input: null, output: null }), null);
  const iso = '2026-11-15T09:05:00+00:00', date = new Date(iso);
  assert.equal(formatTime(iso), `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`);
  assert.equal(formatTime(null), '--:--');
  assert.equal(formatTime('nope'), '--:--');
});

test('outcomes map to tone and label', () => {
  assert.deepEqual(outcomeView('ok'), { tone: 'ok', label: 'Done', quiet: true });
  assert.deepEqual(outcomeView('budget'), { tone: 'warn', label: 'Out of time', quiet: false });
  assert.equal(outcomeView('error').tone, 'danger');
  assert.equal(outcomeView('cancelled').tone, 'idle');
  assert.equal(outcomeView('interrupted').tone, 'idle');
  assert.equal(outcomeView(undefined).tone, 'idle');
  assert.equal(originLabel('voice'), 'VOICE');
  assert.equal(originLabel('vision'), 'VISION');
  assert.equal(originLabel('phone'), 'PHONE');
  assert.equal(originLabel('chat'), 'CHAT');
});

test('waterfall puts every span on one axis, including negative voice starts', () => {
  const view = waterfall(trace({ total_ms: 3000, spans: [
    { kind: 'wake', start_ms: -2000, ms: 500 },
    { kind: 'speech_in', start_ms: -1500, ms: 1500 },
    { kind: 'model', name: 'anthropic', start_ms: 0, ms: 1000 },
    { kind: 'tool', name: 'weather', start_ms: 1000, ms: 1000 },
    { kind: 'speech_out', start_ms: 2000, ms: 2000 },
  ] }));
  assert.equal(view.min, -2000);
  assert.equal(view.max, 4000);
  assert.equal(view.range, 6000);
  close(view.zero, 100 / 3, 'zero');
  close(view.rows[0].bar.left, 0, 'wake left');
  close(view.rows[0].bar.width, 500 / 60, 'wake width');
  close(view.rows[2].bar.left, 100 / 3, 'model left');
  close(view.rows[3].bar.left, 50, 'tool left');
  close(view.rows[4].bar.left + view.rows[4].bar.width, 100, 'speech end');
  assert.deepEqual(view.rows.map(row => row.role), ['speech', 'speech', 'system', 'acting', 'speech']);
  assert.equal(view.rows[0].offset, '−2.0 s');
  assert.equal(view.rows[3].label, 'tool · weather');
  assert.equal(view.rows[1].label, 'speech in');
});

test('waterfall handles a turn with no negative spans, missing times and tiny spans', () => {
  const view = waterfall(trace({ total_ms: 1000, spans: [
    { kind: 'model', start_ms: 0, ms: 1 },
    { kind: 'tool', name: 'x', start_ms: null, ms: 20 },
    { kind: 'approval', name: 'y', start_ms: 998, ms: null },
  ] }));
  assert.equal(view.min, 0);
  assert.equal(view.zero, null);
  assert.equal(view.range, 1000);
  close(view.rows[0].bar.width, 0.6, 'min width');
  assert.equal(view.rows[1].bar, null);
  assert.equal(view.rows[1].offset, null);
  close(view.rows[2].bar.left + view.rows[2].bar.width, 100, 'clamped to the axis');
  assert.equal(view.rows[2].role, 'warn');
  assert.equal(waterfall(trace({ total_ms: null, spans: [] })).range, 1);
});

test('merge replaces a row by id and keeps newest first, at most 200', () => {
  const first = mergeTraces([], [trace({ id: 'old', started_at: '2026-11-15T09:00:00+00:00' }), trace({ id: 'new', started_at: '2026-11-15T09:10:00+00:00' })]);
  assert.deepEqual(first.map(item => item.id), ['new', 'old']);
  const replaced = mergeTraces(first, [trace({ id: 'old', started_at: '2026-11-15T09:00:00+00:00', total_ms: 9000, spans: [{ kind: 'speech_out', start_ms: 2000, ms: 1000 }] })]);
  assert.equal(replaced.length, 2);
  assert.equal(replaced[1].total_ms, 9000);
  assert.equal(replaced[1].spans.length, 1);
  const added = mergeTraces(replaced, [trace({ id: 'newest', started_at: '2026-11-15T09:20:00+00:00' }), { nope: true }, null]);
  assert.deepEqual(added.map(item => item.id), ['newest', 'new', 'old']);
  const many = Array.from({ length: 250 }, (_, i) => trace({ id: `t${i}`, started_at: new Date(Date.UTC(2026, 10, 15, 0, 0, i)).toISOString() }));
  const capped = mergeTraces([], many);
  assert.equal(capped.length, TRACE_LIMIT);
  assert.equal(capped[0].id, 't249');
});

test('normalize drops unusable data and unknown span kinds', () => {
  assert.equal(normalizeTrace(null), null);
  assert.equal(normalizeTrace({ id: '' }), null);
  const clean = normalizeTrace({ id: 'z', spans: [{ kind: 'bogus' }, { kind: 'tool', name: 'a', start_ms: '1', ms: 2 }], approvals: [{ tool: 'a', answer: 'approved' }, {}], cost_usd: 'x' });
  assert.equal(clean.spans.length, 1);
  assert.equal(clean.spans[0].start_ms, null);
  assert.equal(clean.approvals.length, 1);
  assert.equal(clean.cost_usd, null);
  assert.equal(clean.request_text, null);
});

test('approvals read as sentences with how long the owner took', () => {
  const lines = approvalLines(trace({
    spans: [
      { kind: 'approval', name: 'place_task_call', start_ms: 1200, ms: 6200, outcome: 'approved' },
      { kind: 'approval', name: 'send_message', start_ms: 9000, ms: null, outcome: 'timeout' },
    ],
    approvals: [{ tool: 'place_task_call', asked_ms: 1200, answer: 'approved' }, { tool: 'send_message', asked_ms: 9000, answer: 'timeout' }, { tool: 'other', asked_ms: null, answer: 'denied' }],
  }));
  assert.deepEqual(lines, [
    'Asked: place_task_call — approved after 6.2 s',
    'Asked: send_message — no answer',
    'Asked: other — denied',
  ]);
});

test('a row has what the list shows', () => {
  const row = traceRow(normalizeTrace(trace({ outcome: 'budget', request_text: 'What is the weather?', spans: [{ kind: 'tool', name: 'weather', start_ms: 0, ms: 10 }] })));
  assert.equal(row.origin, 'CHAT');
  assert.equal(row.summary, 'weather');
  assert.equal(row.total, '2.4 s');
  assert.equal(row.outcome.label, 'Out of time');
  assert.equal(row.request, 'What is the weather?');
  assert.equal(row.brain, 'anthropic · claude-sonnet · low');
  assert.equal(row.cost, '$0.004');
  assert.equal(row.tokens, '1,200 in / 80 out');
  assert.equal(traceRow(normalizeTrace(trace({ total_ms: null, provider: null, model: null, effort: null }))).total, '—');
  assert.equal(traceRow(normalizeTrace(trace({ provider: null, model: null, effort: null }))).brain, null);
});

test('load more until 200', () => {
  assert.equal(canLoadMore(50, 50), true);
  assert.equal(canLoadMore(12, 50), false);
  assert.equal(canLoadMore(200, 200), false);
  assert.match(EMPTY_TEXT, /^Nothing yet\./);
  assert.match(KEPT_NOTE, /last 200 turns/);
});

test('the client calls trace_recent and trace_clear and filters trace_added', async () => {
  const socket = new EventEmitter();
  socket.connected = true;
  const sent = [];
  socket.emit = (event, data, ack) => {
    if (typeof ack !== 'function') return EventEmitter.prototype.emit.call(socket, event, data);
    sent.push([event, data]);
    ack(event === 'trace_recent' ? { ok: true, traces: [trace(), { bad: 1 }] } : { ok: true });
    return true;
  };
  const client = createActivityClient(socket);
  const list = await client.recent(500);
  assert.equal(list.length, 1);
  await client.clear();
  assert.deepEqual(sent, [['trace_recent', { limit: 200 }], ['trace_clear', {}]]);
  const seen = [];
  client.onAdded(payload => seen.push(payload.id));
  EventEmitter.prototype.emit.call(socket, 'trace_added', { id: 'x', origin: 'voice', outcome: 'ok', total_ms: 1 });
  EventEmitter.prototype.emit.call(socket, 'trace_added', { origin: 'voice' });
  assert.deepEqual(seen, ['x']);
  client.dispose();
});
