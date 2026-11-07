// Pure mappings for the voice devices in Preferences (J2): the saved choice per kind, the
// <select> options built from the core's device list, and the plain notes. The microphone is
// the one Microphone setting every voice uses; the speaker is tray voice's.
import { isAudioDeviceChoice } from '../../transport/audioDevicesClient.ts';

export const SYSTEM_DEFAULT = 'default';
export const DEVICE_KINDS = [
  { kind: 'microphone', label: 'Microphone', list: 'inputs', setting: 'local_microphone' },
  { kind: 'speaker', label: 'Speaker', list: 'outputs', setting: 'local_speaker' },
];
/** The tray voice block lists the speaker only; the microphone has its own row. */
export const TRAY_KINDS = DEVICE_KINDS.filter(item => item.kind === 'speaker');
export const AUTOMATIC_LABEL = 'Automatic (follows Windows)';
const DEFAULT_LABELS = { microphone: AUTOMATIC_LABEL, speaker: 'System default' };
const NOT_CONNECTED = {
  microphone: 'This microphone is not connected; JARVIS uses the Windows default until it is.',
  speaker: 'This speaker is not connected; tray voice uses the system default until it is.',
};
export const TRAY_VOICE_HELP = 'Used when you talk to JARVIS from the tray or say "Hey Jarvis". The microphone pauses while JARVIS speaks.';

const SAVED = 'saved';
const kindOf = kind => DEVICE_KINDS.find(item => item.kind === kind) || DEVICE_KINDS[0];
const same = (entry, choice) => entry.name === choice.name && entry.host_api === choice.host_api;

/** Saved `settings.voice` -> 'default' | { name, host_api } for one kind (the core's fallback). */
export function savedDevice(voice, kind) {
  const value = voice && typeof voice === 'object' ? voice[kindOf(kind).setting] : undefined;
  return isAudioDeviceChoice(value) ? { name: value.name, host_api: value.host_api } : SYSTEM_DEFAULT;
}

const savedIndex = (entries, saved) => (saved === SYSTEM_DEFAULT ? -1 : entries.findIndex(entry => same(entry, saved)));

/** <select> options: the default (Automatic for the microphone), the listed devices, then a saved device that is not connected. */
export function deviceOptions(entries, saved, kind = 'speaker') {
  const options = [{ value: SYSTEM_DEFAULT, label: DEFAULT_LABELS[kindOf(kind).kind] }];
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
  return NOT_CONNECTED[kindOf(kind).kind];
}
