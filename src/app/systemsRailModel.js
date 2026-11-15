/*
 * The Systems rail's pure logic (docs/SYSTEMS_RAIL.md): clock and date text, the next-event
 * countdown, byte and rate formatting, the 60-sample vitals ring and which sections show.
 * No React, no socket: tests/test_systems_rail.mjs runs it in Node.
 */

export const RING_SIZE = 60;                 // 2 minutes of 2 s samples
export const WEATHER_REFRESH_MS = 15 * 60000;
export const AGENDA_REFRESH_MS = 60000;
export const HOME_REFRESH_MS = 60000;
export const SECTION_ORDER = ['now', 'weather', 'next', 'home', 'pc', 'jobs', 'jarvis'];
export const RAIL_TITLES = { now: 'Now', weather: 'Weather', next: 'Next', home: 'Home', pc: 'This PC', jobs: 'Jobs', jarvis: 'JARVIS' };
export const GAMING_PAUSED = 'Paused in gaming mode';

const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const pad = value => String(value).padStart(2, '0');
const finite = value => typeof value === 'number' && Number.isFinite(value);

/** "09:05" (24 h, local time). */
export const clockText = date => `${pad(date.getHours())}:${pad(date.getMinutes())}`;

/** "Sunday 15 November" (local time). */
export const dateText = date => `${WEEKDAYS[date.getDay()]} ${date.getDate()} ${MONTHS[date.getMonth()]}`;

/** Milliseconds to the next minute boundary (plus a small margin so the minute has turned). */
export const msToNextMinute = nowMs => 60000 - (nowMs % 60000) + 50;

/**
 * "Design review in 42 min", "… in 1 h 5 min", "… starting now"; null once it has started
 * (more than a minute ago) or without a valid time. `at` is epoch seconds.
 */
export function countdownText(title, at, nowMs) {
  if (!finite(at) || !finite(nowMs)) return null;
  const name = typeof title === 'string' && title.trim() ? title.trim() : 'Next event';
  const minutes = Math.ceil((at * 1000 - nowMs) / 60000);
  if (minutes < 0) return null;
  if (minutes <= 0) return `${name} starting now`;
  if (minutes < 60) return `${name} in ${minutes} min`;
  const hours = Math.floor(minutes / 60), rest = minutes % 60;
  return `${name} in ${hours} h${rest ? ` ${rest} min` : ''}`;
}

/** "2 reminders today · Call the bank 15:00" / "1 reminder today · Water the plants". */
export function remindersText(reminders) {
  if (!reminders || !finite(reminders.count) || reminders.count < 1) return null;
  const count = `${reminders.count} ${reminders.count === 1 ? 'reminder' : 'reminders'} today`;
  const first = reminders.first;
  if (!first || typeof first.title !== 'string' || !first.title) return count;
  const time = typeof first.time === 'string' && /^\d\d:\d\d$/.test(first.time) ? ` ${first.time}` : '';
  return `${count} · ${first.title}${time}`;
}

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB'];

/** 1024-based sizes: "512 B", "1.5 KB", "7.9 GB" (one decimal under 100, none above). */
export function formatBytes(bytes) {
  if (!finite(bytes) || bytes < 0) return '—';
  let value = bytes, unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) { value /= 1024; unit += 1; }
  if (unit === 0) return `${Math.round(value)} B`;
  return `${value >= 100 ? Math.round(value) : value.toFixed(1)} ${UNITS[unit]}`;
}

/** Bytes per second: "0 B/s", "12.0 KB/s", "1.2 MB/s". */
export const formatRate = perSecond => (finite(perSecond) && perSecond >= 0 ? `${formatBytes(perSecond)}/s` : '—');

/** "7.9 / 15.9 GB" (both in the larger value's unit). */
export function formatUsage(used, total) {
  if (!finite(used) || !finite(total) || total <= 0) return '—';
  let unit = 0, scale = 1;
  while (total / scale >= 1024 && unit < UNITS.length - 1) { scale *= 1024; unit += 1; }
  const show = value => { const scaled = value / scale; return scaled >= 100 ? String(Math.round(scaled)) : scaled.toFixed(1); };
  return `${show(used)} / ${show(total)} ${UNITS[unit]}`;
}

export const percentOf = (used, total) => (finite(used) && finite(total) && total > 0 ? Math.min(100, Math.max(0, (used / total) * 100)) : null);

/** A `vitals` payload checked and reduced to numbers, or null. */
export function normalizeVitals(payload) {
  if (!payload || typeof payload !== 'object' || !finite(payload.t) || !finite(payload.cpu)) return null;
  const pair = (value, a, b) => (value && finite(value[a]) && finite(value[b]) ? { [a]: value[a], [b]: value[b] } : null);
  const mem = pair(payload.mem, 'used', 'total'), disk = pair(payload.disk, 'used', 'total'), net = pair(payload.net, 'up', 'down');
  if (!mem || !net) return null;
  const sample = { t: payload.t, cpu: Math.min(100, Math.max(0, payload.cpu)), mem, disk, net };
  if (payload.battery && finite(payload.battery.percent)) {
    sample.battery = { percent: payload.battery.percent, plugged: typeof payload.battery.plugged === 'boolean' ? payload.battery.plugged : null };
  }
  if (payload.gpu && finite(payload.gpu.percent)) sample.gpu = { percent: payload.gpu.percent };
  return sample;
}

/** The ring with one more sample (oldest dropped past RING_SIZE); never mutates. */
export function pushSample(ring, sample, size = RING_SIZE) {
  if (!sample) return ring;
  const next = ring.length >= size ? ring.slice(ring.length - size + 1) : ring.slice();
  next.push(sample);
  return next;
}

/** uPlot data [xs, ys] for one series of the ring. */
export function seriesData(ring, key) {
  const pick = {
    cpu: sample => sample.cpu,
    mem: sample => percentOf(sample.mem.used, sample.mem.total),
    net: sample => sample.net.up + sample.net.down,
  }[key];
  return [ring.map(sample => sample.t), ring.map(pick)];
}

/** The y range of a sparkline: 0–100 for percentages, 0–(peak + 10%) for the network. */
export function seriesRange(key, ys) {
  if (key !== 'net') return [0, 100];
  const peak = Math.max(0, ...ys.filter(finite));
  return [0, peak > 0 ? peak * 1.1 : 1024];
}

/** The This PC rows from the latest sample: three sparkline rows and the plain values. */
export function pcRows(ring) {
  const last = ring[ring.length - 1];
  if (!last) return { spark: [], plain: [] };
  const spark = [
    { key: 'cpu', label: 'CPU', value: `${Math.round(last.cpu)}%` },
    { key: 'mem', label: 'Memory', value: formatUsage(last.mem.used, last.mem.total) },
    { key: 'net', label: 'Network', value: `↑ ${formatRate(last.net.up)} ↓ ${formatRate(last.net.down)}`, parts: [`↑ ${formatRate(last.net.up)}`, `↓ ${formatRate(last.net.down)}`], spoken: `Network up ${formatRate(last.net.up)}, down ${formatRate(last.net.down)}` },
  ];
  const plain = [];
  if (last.disk) plain.push({ key: 'disk', label: 'Disk', value: formatUsage(last.disk.used, last.disk.total) });
  if (last.battery) {
    const state = last.battery.plugged === true ? ' · plugged in' : last.battery.plugged === false ? ' · on battery' : '';
    plain.push({ key: 'battery', label: 'Battery', value: `${Math.round(last.battery.percent)}%${state}` });
  }
  if (last.gpu) plain.push({ key: 'gpu', label: 'GPU', value: `${Math.round(last.gpu.percent)}%` });
  return { spark, plain };
}

const RUNNING = new Set(['submitting', 'approval', 'queued', 'running']);

/** Running creative jobs in this project: [{key, name, phase}]. */
export function runningJobs(activity, project) {
  return (Array.isArray(activity) ? activity : [])
    .filter(item => item && item.project === project && RUNNING.has(item.state))
    .map(item => ({ key: item.key, name: item.name || 'Untitled job', phase: String(item.phase || item.state).replaceAll('_', ' ') }));
}

/**
 * Which sections show, in order. Each hides without a source; Now and JARVIS always show.
 * This PC shows with samples, or while gaming (it then reads "Paused in gaming mode").
 */
export function visibleSections({ weather, agenda, home, ring = [], gaming = false, jobs = [], nowMs = Date.now() } = {}) {
  const shown = {
    now: true,
    weather: !!(weather && weather.home && typeof weather.line === 'string' && weather.line),
    next: !!(agenda && ((agenda.event && countdownText(agenda.event.title, agenda.event.at, nowMs)) || remindersText(agenda.reminders))),
    home: !!(home && home.connected && typeof home.line === 'string' && home.line),
    pc: gaming || ring.length > 0,
    jobs: jobs.length > 0,
    jarvis: true,
  };
  return SECTION_ORDER.filter(id => shown[id]);
}

/** The core decides the rate; the renderer only says whether its Battery API reads low. */
export const watchRequest = ({ on, lowBattery = false }) => ({ on: !!on, low_battery: !!on && !!lowBattery });
