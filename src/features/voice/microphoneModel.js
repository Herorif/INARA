// The one Microphone setting (voice.local_microphone) seen from the window: matching the core's
// Windows device names to the browser's devices, the one-time adoption of the old window-only
// choice, when an open capture should follow a new Windows default, and the Preferences level
// bar's smoothing. Pure: no store, socket or media.

export const AUTOMATIC = 'default';
export const LEGACY_KEY = 'selectedMicId';
// Chromium's own entries for the system default and the communications default.
const ALIASES = new Set(['default', 'communications']);
const PREFIX = /^(default|communications)\s+-\s+/i;
// Chromium on Windows appends a USB device's vendor:product id to its label.
const USB_SUFFIX = /\s+\([0-9a-f]{4}:[0-9a-f]{4}\)$/i;

const inputsOf = (devices) => (Array.isArray(devices) ? devices : []).filter((device) => device && device.kind === 'audioinput');
const isNamed = (choice) => !!choice && typeof choice === 'object' && typeof choice.name === 'string' && choice.name.length > 0;

/** A device name as shown: without Chromium's "Default - " prefix or USB id suffix. */
export function cleanLabel(label) {
  return String(label || '').replace(/\s+/g, ' ').trim().replace(PREFIX, '').replace(USB_SUFFIX, '').trim();
}

/** The comparison form: cleaned, whitespace-normalised and case-insensitive. */
export function normalizeLabel(label) {
  return cleanLabel(label).toLowerCase();
}

export function labelsMatch(name, label) {
  const left = normalizeLabel(name);
  return left.length > 0 && left === normalizeLabel(label);
}

/** The browser deviceId for the saved choice; '' (the browser's default) for Automatic or no match. */
export function browserDeviceFor(choice, devices) {
  if (!isNamed(choice)) return '';
  const match = inputsOf(devices).find((device) => !ALIASES.has(device.deviceId) && labelsMatch(choice.name, device.label));
  return match ? match.deviceId : '';
}

/** Which physical device the browser's default input is now ('' when there is none). */
export function defaultInputKey(devices) {
  const inputs = inputsOf(devices);
  const entry = inputs.find((device) => device.deviceId === 'default')
    || inputs.find((device) => !ALIASES.has(device.deviceId));
  return entry ? `${entry.groupId || ''}|${normalizeLabel(entry.label)}` : '';
}

/**
 * What an open capture does after a `devicechange`: 'keep', 'restart' (Automatic, and the
 * Windows default moved to another device) or 'lost' (its device, or every microphone, is gone).
 * `deviceId` is what the capture asked for ('' for the default); `defaultKey` is
 * defaultInputKey() when it opened.
 */
export function captureDecision({ deviceId, trackDeviceId, defaultKey, devices }) {
  const inputs = inputsOf(devices);
  if (deviceId) {
    return trackDeviceId && !inputs.some((device) => device.deviceId === trackDeviceId) ? 'lost' : 'keep';
  }
  if (!inputs.length) return 'lost';
  return defaultInputKey(devices) !== defaultKey ? 'restart' : 'keep';
}

/**
 * The device Automatic uses now, by its Windows name: the browser's default matched to the
 * core's list, else its cleaned label, else the core's own default; '' when unknown.
 */
export function automaticDeviceName(inputs, devices) {
  const entries = Array.isArray(inputs) ? inputs : [];
  const current = inputsOf(devices).find((device) => device.deviceId === 'default' && cleanLabel(device.label));
  if (current) {
    const entry = entries.find((item) => labelsMatch(item.name, current.label));
    return entry ? entry.name : cleanLabel(current.label);
  }
  const fallback = entries.find((item) => item.default);
  return fallback ? fallback.name : '';
}

/** Whether adopting the old window-only choice needs the device lists. */
export function legacyNeedsLookup(storedId, saved) {
  return typeof storedId === 'string' && storedId !== '' && !ALIASES.has(storedId) && saved === AUTOMATIC;
}

/**
 * The old window-only microphone (localStorage `selectedMicId`, a browser deviceId) adopted
 * once: { choice, done }. `choice` is the core's { name, host_api } entry with the same name, or
 * null (Automatic stays; a microphone already chosen in the core is kept). `done` false means
 * the device's name could not be read yet, so the old key stays for the next start.
 */
export function legacyChoice({ storedId, saved, devices, inputs }) {
  if (!legacyNeedsLookup(storedId, saved)) return { choice: null, done: true };
  const device = inputsOf(devices).find((item) => item.deviceId === storedId);
  if (!device) return { choice: null, done: true };
  if (!cleanLabel(device.label)) return { choice: null, done: false };
  const entry = (Array.isArray(inputs) ? inputs : []).find((item) => labelsMatch(item.name, device.label));
  return { choice: entry ? { name: entry.name, host_api: entry.host_api } : null, done: true };
}

// --- the Preferences level bar -----------------------------------------------------------------

export const ATTACK_MS = 50;
export const RELEASE_MS = 200;

/** `min(1, 4 * rms)` of float samples in -1..1, the scale the core's player level uses. */
export function levelFromSamples(samples) {
  const count = samples ? samples.length : 0;
  if (!count) return 0;
  let total = 0;
  for (let index = 0; index < count; index++) total += samples[index] * samples[index];
  return Math.min(1, 4 * Math.sqrt(total / count));
}

/**
 * The next shown level, 0..1: fast attack (about 50 ms), slower release (about 200 ms).
 * With reduced motion the level is shown as measured, without smoothing.
 */
export function smoothLevel(previous, target, elapsedMs, reduced = false) {
  const goal = Math.min(1, Math.max(0, Number(target) || 0));
  if (reduced) return goal;
  const from = Math.min(1, Math.max(0, Number(previous) || 0));
  const elapsed = Math.max(0, Number(elapsedMs) || 0);
  const tau = goal > from ? ATTACK_MS : RELEASE_MS;
  return from + (goal - from) * (1 - Math.exp(-elapsed / tau));
}
