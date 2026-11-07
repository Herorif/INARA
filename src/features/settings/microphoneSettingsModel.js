// Preferences > Voice > Microphone: the one microphone every voice uses (voice.local_microphone).
// Pure: copy, the "Using:" line and when the level bar reopens.
import { AUTOMATIC, browserDeviceFor, defaultInputKey } from '../voice/microphoneModel.js';

export const MICROPHONE_LABEL = 'Microphone';
export const LEVEL_HELP = 'Speak to check. The bar moves when JARVIS hears you.';
export const BLOCKED_HELP = "JARVIS can't hear this microphone. Choose another or check Windows sound settings.";

/** "Using: <name>" under the select while Automatic is chosen and the device is known. */
export function usingText(saved, name) {
  return saved === AUTOMATIC && name ? `Using: ${name}` : '';
}

/**
 * The level bar's device for the saved choice: { deviceId, restartKey }. It reopens when the
 * mapped device changes, when the default moves (Automatic, or no match) and when microphones
 * come and go (so a blocked bar tries again).
 */
export function meterTarget(saved, devices) {
  const deviceId = browserDeviceFor(saved, devices);
  const inputs = (Array.isArray(devices) ? devices : []).filter((device) => device && device.kind === 'audioinput').length;
  return { deviceId, restartKey: `${deviceId || `default:${defaultInputKey(devices)}`}|${inputs}` };
}
