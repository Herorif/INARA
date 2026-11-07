import useStore from '../../store';
import { browserDeviceFor } from './microphoneModel.js';

/**
 * The browser deviceId for the saved Microphone (voice.local_microphone), read when a capture
 * opens: '' (the browser's default, which follows Windows) for Automatic or no match.
 */
export async function microphoneDeviceId(media = globalThis.navigator?.mediaDevices) {
  const choice = useStore.getState().voiceMicrophone;
  if (!choice || typeof choice !== 'object' || !media?.enumerateDevices) return '';
  try {
    return browserDeviceFor(choice, await media.enumerateDevices());
  } catch {
    return '';
  }
}
