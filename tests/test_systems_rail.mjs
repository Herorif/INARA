import test from 'node:test';
import assert from 'node:assert/strict';
import {
  GAMING_PAUSED, RING_SIZE, SECTION_ORDER, clockText, countdownText, dateText, formatBytes, formatRate,
  formatUsage, msToNextMinute, normalizeVitals, pcRows, pushSample, remindersText, runningJobs,
  seriesData, seriesRange, visibleSections, watchRequest,
} from '../src/app/systemsRailModel.js';

const GB = 2 ** 30;
const sample = (t, extra = {}) => ({ t, cpu: 20, mem: { used: 8 * GB, total: 16 * GB }, disk: { used: 200 * GB, total: 500 * GB }, net: { up: 1500, down: 2_400_000 }, ...extra });

test('clock and date read like the spec', () => {
  const date = new Date(2026, 10, 15, 9, 5);
  assert.equal(clockText(date), '09:05');
  assert.equal(dateText(date), 'Sunday 15 November');
  assert.equal(clockText(new Date(2026, 0, 1, 23, 59)), '23:59');
  assert.equal(msToNextMinute(Date.UTC(2026, 10, 15, 1, 0, 30)), 30050);
});

test('countdown text: minutes, hours, starting now, then gone', () => {
  const now = Date.UTC(2026, 10, 15, 1, 0, 0);
  const at = minutes => now / 1000 + minutes * 60;
  assert.equal(countdownText('Design review', at(42), now), 'Design review in 42 min');
  assert.equal(countdownText('Design review', at(41.5), now), 'Design review in 42 min'); // rounds up
  assert.equal(countdownText('Lunch', at(60), now), 'Lunch in 1 h');
  assert.equal(countdownText('Lunch', at(65), now), 'Lunch in 1 h 5 min');
  assert.equal(countdownText('Standup', at(0), now), 'Standup starting now');
  assert.equal(countdownText('Standup', at(-0.5), now), 'Standup starting now');
  assert.equal(countdownText('Standup', at(-2), now), null);
  assert.equal(countdownText('  ', at(5), now), 'Next event in 5 min');
  assert.equal(countdownText('x', null, now), null);
  assert.equal(countdownText('x', Number.NaN, now), null);
});

test('reminders line: count and the first one', () => {
  assert.equal(remindersText({ count: 2, first: { title: 'Call the bank', time: '15:00' } }), '2 reminders today · Call the bank 15:00');
  assert.equal(remindersText({ count: 1, first: { title: 'Overdue thing', time: '—' } }), '1 reminder today · Overdue thing');
  assert.equal(remindersText({ count: 3 }), '3 reminders today');
  assert.equal(remindersText({ count: 0, first: null }), null);
  assert.equal(remindersText(null), null);
});

test('byte, rate and usage formatting', () => {
  assert.equal(formatBytes(0), '0 B');
  assert.equal(formatBytes(512), '512 B');
  assert.equal(formatBytes(1536), '1.5 KB');
  assert.equal(formatBytes(8.5 * GB), '8.5 GB');
  assert.equal(formatBytes(150 * 1024 * 1024), '150 MB');
  assert.equal(formatBytes(-1), '—');
  assert.equal(formatRate(0), '0 B/s');
  assert.equal(formatRate(12 * 1024), '12.0 KB/s');
  assert.equal(formatRate(1.25 * 1024 * 1024), '1.3 MB/s');
  assert.equal(formatRate(undefined), '—');
  assert.equal(formatUsage(7.9 * GB, 15.9 * GB), '7.9 / 15.9 GB');
  assert.equal(formatUsage(212 * GB, 476 * GB), '212 / 476 GB');
  assert.equal(formatUsage(1, 0), '—');
});

test('the ring keeps the last 60 samples and never mutates', () => {
  let ring = [];
  for (let index = 0; index < 75; index += 1) {
    const before = ring;
    ring = pushSample(ring, sample(index));
    assert.notEqual(ring, before);
  }
  assert.equal(RING_SIZE, 60);
  assert.equal(ring.length, 60);
  assert.equal(ring[0].t, 15);
  assert.equal(ring.at(-1).t, 74);
  assert.equal(pushSample(ring, null), ring);
  const [xs, ys] = seriesData(ring.slice(-3), 'mem');
  assert.deepEqual(xs, [72, 73, 74]);
  assert.deepEqual(ys, [50, 50, 50]);
  assert.deepEqual(seriesData(ring.slice(-1), 'net')[1], [2_401_500]);
  assert.deepEqual(seriesRange('cpu', [1, 2]), [0, 100]);
  assert.deepEqual(seriesRange('net', [0, 1000]), [0, 1100]);
  assert.deepEqual(seriesRange('net', [0, 0]), [0, 1024]);
});

test('vitals payloads are checked; battery and gpu are optional', () => {
  assert.equal(normalizeVitals(null), null);
  assert.equal(normalizeVitals({ t: 1, cpu: 5 }), null);
  assert.equal(normalizeVitals({ t: 1, cpu: 'x', mem: { used: 1, total: 2 }, net: { up: 0, down: 0 } }), null);
  const plain = normalizeVitals({ t: 1, cpu: 140, mem: { used: 1, total: 2 }, disk: { used: 1, total: 2 }, net: { up: 0, down: 3 }, extra: 'ignored' });
  assert.deepEqual(plain, { t: 1, cpu: 100, mem: { used: 1, total: 2 }, disk: { used: 1, total: 2 }, net: { up: 0, down: 3 } });
  const full = normalizeVitals({ ...sample(2), battery: { percent: 64, plugged: false }, gpu: { percent: 41 } });
  assert.deepEqual(full.battery, { percent: 64, plugged: false });
  assert.deepEqual(full.gpu, { percent: 41 });
  assert.equal(normalizeVitals({ ...sample(3), battery: { percent: null } }).battery, undefined);
});

test('This PC rows: three sparkline rows, then disk and battery as values', () => {
  assert.deepEqual(pcRows([]), { spark: [], plain: [] });
  const rows = pcRows([sample(1, { battery: { percent: 64.4, plugged: true } })]);
  assert.deepEqual(rows.spark.map(row => [row.key, row.label, row.value]), [
    ['cpu', 'CPU', '20%'],
    ['mem', 'Memory', '8.0 / 16.0 GB'],
    ['net', 'Network', '↑ 1.5 KB/s ↓ 2.3 MB/s'],
  ]);
  assert.deepEqual(rows.spark[2].parts, ['↑ 1.5 KB/s', '↓ 2.3 MB/s']);
  assert.deepEqual(rows.plain.map(row => [row.key, row.value]), [['disk', '200 / 500 GB'], ['battery', '64% · plugged in']]);
  const bare = pcRows([{ ...sample(1), disk: null }]);
  assert.deepEqual(bare.plain, []);
});

test('running jobs: this project only, name and phase', () => {
  const activity = [
    { key: 'cad:1', project: 'p', state: 'running', phase: 'building_mesh', name: 'Shelf bracket' },
    { key: 'image:2', project: 'p', state: 'succeeded', phase: 'done', name: 'Poster' },
    { key: 'cad:3', project: 'other', state: 'queued', phase: 'queued', name: 'Elsewhere' },
    { key: 'image:4', project: 'p', state: 'approval', phase: '', name: '' },
  ];
  assert.deepEqual(runningJobs(activity, 'p'), [
    { key: 'cad:1', name: 'Shelf bracket', phase: 'building mesh' },
    { key: 'image:4', name: 'Untitled job', phase: 'approval' },
  ]);
  assert.deepEqual(runningJobs(null, 'p'), []);
});

test('section visibility: each block hides without a source, in the fixed order', () => {
  const nowMs = Date.UTC(2026, 10, 15, 1, 0, 0);
  assert.deepEqual(visibleSections({ nowMs }), ['now', 'jarvis']);
  assert.deepEqual(visibleSections({ ring: [sample(1)], nowMs }), ['now', 'pc', 'jarvis']);
  assert.deepEqual(visibleSections({ gaming: true, nowMs }), ['now', 'pc', 'jarvis']); // reads "Paused in gaming mode"
  const all = visibleSections({
    weather: { home: true, line: 'Kuala Lumpur: 31°C, light rain.' },
    agenda: { event: { title: 'Design review', at: nowMs / 1000 + 600 }, reminders: null },
    home: { connected: true, line: 'At home: 2 of 5 lights on.' },
    ring: [sample(1)], jobs: [{ key: 'a', name: 'x', phase: 'running' }], nowMs,
  });
  assert.deepEqual(all, SECTION_ORDER);
  assert.deepEqual(visibleSections({
    weather: { home: false }, home: { connected: false, line: null },
    agenda: { event: { title: 'Gone', at: nowMs / 1000 - 600 }, reminders: { count: 0 } }, nowMs,
  }), ['now', 'jarvis']);
  assert.deepEqual(visibleSections({ agenda: { event: null, reminders: { count: 1, first: { title: 'Bank', time: '15:00' } } }, nowMs }), ['now', 'next', 'jarvis']);
  assert.deepEqual(visibleSections({ home: { connected: true, line: null }, nowMs }), ['now', 'jarvis']);
  assert.equal(GAMING_PAUSED, 'Paused in gaming mode');
});

test('the watch request carries the low battery hint only while on', () => {
  assert.deepEqual(watchRequest({ on: true }), { on: true, low_battery: false });
  assert.deepEqual(watchRequest({ on: true, lowBattery: true }), { on: true, low_battery: true });
  assert.deepEqual(watchRequest({ on: false, lowBattery: true }), { on: false, low_battery: false });
});
