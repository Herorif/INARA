import { createAudioDevicesClient, devicePatch } from '../../transport/audioDevicesClient.ts';
import { LEGACY_KEY, legacyChoice, legacyNeedsLookup } from './microphoneModel.js';

let attempted = false;

/** Tests only: allow another adoption in this process. */
export function resetLegacyAdoption() {
  attempted = false;
}

/**
 * Once per start: the old window-only microphone becomes the Microphone setting when the
 * core lists a device with its name and nothing is chosen there yet; then the old key goes.
 */
export async function adoptLegacyMicrophone({ socket, saved, emit, storage = globalThis.localStorage, media = globalThis.navigator?.mediaDevices }) {
  if (attempted) return;
  let stored;
  try {
    stored = storage?.getItem(LEGACY_KEY);
  } catch {
    return;
  }
  if (stored === null || stored === undefined) return;
  attempted = true;
  try {
    let devices = [], inputs = [];
    if (legacyNeedsLookup(stored, saved)) {
      devices = await media.enumerateDevices();
      const client = createAudioDevicesClient(socket);
      try {
        const report = await client.list();
        if (!report.available) return;
        inputs = report.inputs;
      } finally {
        client.dispose();
      }
    }
    const { choice, done } = legacyChoice({ storedId: stored, saved, devices, inputs });
    if (choice) emit('update_settings', devicePatch('microphone', choice));
    if (done) storage.removeItem(LEGACY_KEY);
  } catch {
    // The core or the device list is not reachable now; the old key stays for the next start.
  }
}
