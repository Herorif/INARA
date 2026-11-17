// S7.3 heartbeat UI (docs/PROACTIVE.md "Heartbeat"): Preferences > Assistant's "Standing
// instructions" row (model and wiring).
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  HEARTBEAT_HELP, HEARTBEAT_MAX, HEARTBEAT_ROWS, HEARTBEAT_TOO_LONG, heartbeatTextError, lastCheckLine,
  normalizeHeartbeat, savedLength, toldCount,
} from '../src/features/proactive/heartbeatModel.js';

const KL = 'Asia/Kuala_Lumpur';
const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');

test('the last check line counts what reached the owner', () => {
  const at = '2026-11-15T06:30:00+00:00'; // 14:30 in Malaysia
  assert.equal(lastCheckLine(null, []), 'Last check: not yet');
  assert.equal(lastCheckLine('nope', []), 'Last check: not yet');
  assert.equal(lastCheckLine(at, [], KL), 'Last check: 14:30 · nothing to tell');
  assert.equal(lastCheckLine(at, [{ action: 'notify', outcome: 'card' }, { action: 'none', outcome: 'acknowledged' }], KL),
    'Last check: 14:30 · told you 1 thing');
  assert.equal(lastCheckLine(at, [{ action: 'speak', outcome: 'spoken' }, { action: 'notify', outcome: 'balloon' },
    { action: 'notify', outcome: 'held' }], KL), 'Last check: 14:30 · told you 2 things');
  assert.equal(toldCount(null), 0);
});

test('the text is length-checked as the core saves it', () => {
  assert.equal(heartbeatTextError('x'.repeat(HEARTBEAT_MAX)), '');
  assert.equal(heartbeatTextError('x'.repeat(HEARTBEAT_MAX + 1)), HEARTBEAT_TOO_LONG);
  assert.equal(savedLength('a\r\nb'), 3);
  assert.equal(heartbeatTextError('\r\n'.repeat(HEARTBEAT_MAX)), '');
  assert.equal(heartbeatTextError(''), '');
});

test('responses are validated', () => {
  assert.equal(normalizeHeartbeat(null), null);
  assert.equal(normalizeHeartbeat({ text: 3 }), null);
  assert.deepEqual(normalizeHeartbeat({ text: '', last_run: 'x', last_actions: 'x' }),
    { text: '', lastRun: null, lastActions: [] });
  assert.deepEqual(normalizeHeartbeat({
    text: '# Standing instructions', last_run: '2026-11-15T06:30:00+00:00',
    last_actions: [{ action: 'notify', signal: 'k', kind: 'calendar.soon', outcome: 'card' }, { action: 'shout' }, null],
  }), { text: '# Standing instructions', lastRun: '2026-11-15T06:30:00+00:00', lastActions: [{ action: 'notify', outcome: 'card' }] });
});

test('the row sits in Preferences > Assistant with the briefed copy', () => {
  assert.equal(HEARTBEAT_ROWS, 8);
  assert.match(HEARTBEAT_HELP, /^JARVIS reads these every 30 minutes when something is waiting/);
  const row = read('src/features/settings/HeartbeatSettings.jsx');
  assert.match(row, /font-mono/);
  assert.doesNotMatch(row, /text-\[0\.([0-6]\d*|7[0-4]\d*)rem\]|text-\[([0-9]|1[01])px\]/); // 12 px minimum
  assert.match(read('src/features/settings/ProactiveSettings.jsx'), /<HeartbeatSettings \/>/);
  const client = read('src/features/proactive/proactiveClient.js');
  assert.match(client, /'heartbeat_get'/);
  assert.match(client, /'heartbeat_save', \{ text \}/);
});
