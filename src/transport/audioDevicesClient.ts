import { createRpcScope, RpcError, type RpcSocket } from './rpc.ts';
import type { AudioDeviceChoice, AudioDeviceEntry, AudioDevicesReport } from './generated/audio.ts';

/**
 * Owner-only tray voice devices (J2): the core's microphones and speakers, listed without
 * opening them. A device is saved by name and host API, or as 'default' (the system default),
 * in `voice.local_microphone` / `voice.local_speaker` through update_settings.
 */
export type AudioDeviceSelection = AudioDeviceChoice | 'default';
export type AudioDeviceKind = 'microphone' | 'speaker';
export const SETTING_KEYS: Record<AudioDeviceKind, 'local_microphone' | 'local_speaker'> = {
  microphone: 'local_microphone',
  speaker: 'local_speaker',
};

const NAME_LIMIT = 200, HOST_API_LIMIT = 64, DEVICE_LIMIT = 64;
// Printable text only, as the core validates it.
const PRINTABLE = /^[^\u0000-\u001f\u007f]+$/;

type Obj = Record<string, unknown>;
const isObject = (value: unknown): value is Obj => !!value && typeof value === 'object' && !Array.isArray(value);
const isLabel = (value: unknown, limit: number): value is string =>
  typeof value === 'string' && value.length >= 1 && value.length <= limit && PRINTABLE.test(value);
const optionalText = (value: unknown, limit: number) => value === null || (typeof value === 'string' && value.length <= limit);

export const isAudioDeviceChoice = (value: unknown): value is AudioDeviceChoice =>
  isObject(value) && Object.keys(value).length === 2 && isLabel(value.name, NAME_LIMIT) && isLabel(value.host_api, HOST_API_LIMIT);

export const isAudioDeviceSelection = (value: unknown): value is AudioDeviceSelection =>
  value === 'default' || isAudioDeviceChoice(value);

export const isAudioDeviceEntry = (value: unknown): value is AudioDeviceEntry =>
  isObject(value) && isLabel(value.name, NAME_LIMIT) && isLabel(value.host_api, HOST_API_LIMIT)
  && typeof value.default === 'boolean'
  && Number.isInteger(value.channels) && (value.channels as number) >= 1 && (value.channels as number) <= 64
  && Number.isInteger(value.sample_rate) && (value.sample_rate as number) >= 8000 && (value.sample_rate as number) <= 384000;

/** The `audio_devices` ACK body, or null when a field is missing or mistyped. */
export function parseAudioDevices(response: unknown): AudioDevicesReport | null {
  if (!isObject(response) || typeof response.available !== 'boolean') return null;
  if (!optionalText(response.code, 64) || !optionalText(response.message, 500) || !optionalText(response.host_api, HOST_API_LIMIT)) return null;
  const { inputs, outputs } = response;
  if (!Array.isArray(inputs) || inputs.length > DEVICE_LIMIT || !inputs.every(isAudioDeviceEntry)) return null;
  if (!Array.isArray(outputs) || outputs.length > DEVICE_LIMIT || !outputs.every(isAudioDeviceEntry)) return null;
  if (!response.available && (inputs.length || outputs.length)) return null;
  return {
    available: response.available,
    code: response.code as string | null,
    message: response.message as string | null,
    host_api: response.host_api as string | null,
    inputs: inputs.map(entry => ({ ...entry })),
    outputs: outputs.map(entry => ({ ...entry })),
  };
}

export function createAudioDevicesClient(socket: RpcSocket) {
  const scope = createRpcScope(socket);
  return {
    on: scope.on,
    dispose: scope.dispose,
    async list(): Promise<AudioDevicesReport> {
      // Listing may wait for the audio system to start the first time.
      const report = parseAudioDevices(await scope.call('audio_devices', {}, 15000));
      if (!report) throw new RpcError('The core returned an incomplete device list. Reopen Preferences to try again.', 'invalid_response');
      return report;
    },
  };
}

/** The update_settings patch that saves one tray voice device. */
export function devicePatch(kind: AudioDeviceKind, selection: AudioDeviceSelection) {
  if (!isAudioDeviceSelection(selection)) throw new RpcError('Choose a listed device.', 'invalid_arguments');
  const value = selection === 'default' ? 'default' : { name: selection.name, host_api: selection.host_api };
  return { voice: { [SETTING_KEYS[kind]]: value } };
}
