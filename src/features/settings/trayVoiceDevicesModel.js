// Pure mappings for the tray voice devices in Preferences (J2): the saved choice per kind,
// the <select> options built from the core's device list, and the plain notes.
import { isAudioDeviceChoice } from '../../transport/audioDevicesClient.ts';

export const SYSTEM_DEFAULT = 'default';
export const DEVICE_KINDS = [
  { kind: 'microphone', label: 'Microphone', list: 'inputs', setting: 'local_microphone' },
  { kind: 'speaker', label: 'Speaker', list: 'outputs', setting: 'local_speaker' },
];
export const TRAY_VOICE_HELP = 'Used when you talk to JARVIS from the tray. The microphone is open only while you talk, and pauses while JARVIS speaks.';

const SAVED = 'saved';
const kindOf = kind => DEVICE_KINDS.find(item => item.kind === kind) || DEVICE_KINDS[0];
const same = (entry, choice) => entry.name === choice.name && entry.host_api === choice.host_api;

/** Saved `settings.voice` -> 'default' | { name, host_api } for one kind (the core's fallback). */
export function savedDevice(voice, kind) {
  const value = voice && typeof voice === 'object' ? voice[kindOf(kind).setting] : undefined;
  return isAudioDeviceChoice(value) ? { name: value.name, host_api: value.host_api } : SYSTEM_DEFAULT;
}

const savedIndex = (entries, saved) => (saved === SYSTEM_DEFAULT ? -1 : entries.findIndex(entry => same(entry, saved)));

/** <select> options: System default, the listed devices, then a saved device that is not connected. */
export function deviceOptions(entries, saved) {
  const options = [{ value: SYSTEM_DEFAULT, label: 'System default' }];
  entries.forEach((entry, index) => options.push({ value: `device:${index}`, label: entry.name }));
  if (saved !== SYSTEM_DEFAULT && savedIndex(entries, saved) === -1) {
    options.push({ value: SAVED, label: `${saved.name} (not connected)` });
  }
  return options;
}

export function selectedValue(entries, saved) {
  if (saved === SYSTEM_DEFAULT) return SYSTEM_DEFAULT;
  const index = savedIndex(entries, saved);
  return index === -1 ? SAVED : `device:${index}`;
}

/** The choice for a picked option value, or null when nothing changes. */
export function selectionFor(entries, saved, value) {
  if (value === selectedValue(entries, saved) || value === SAVED) return null;
  if (value === SYSTEM_DEFAULT) return SYSTEM_DEFAULT;
  const match = /^device:(\d+)$/.exec(String(value));
  const entry = match ? entries[Number(match[1])] : undefined;
  return entry ? { name: entry.name, host_api: entry.host_api } : null;
}

/** A plain note when a saved device is not connected right now. */
export function deviceNote(entries, saved, kind, available) {
  if (!available || saved === SYSTEM_DEFAULT || savedIndex(entries, saved) !== -1) return '';
  return `This ${kindOf(kind).label.toLowerCase()} is not connected; tray voice uses the system default until it is.`;
}
