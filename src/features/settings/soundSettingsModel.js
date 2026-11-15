// Pure copy and mappings for Preferences > Interface sounds (S13a, docs/SOUND.md): the saved
// settings.sound with the core's defaults, the slider's percent, and the update_settings patches.
import { soundChoice } from '../../services/sound/uiSoundsModel.js';

export const HEADING = 'Sound';
export const SOUNDS_LABEL = 'Interface sounds';
export const SOUNDS_HELP = 'Short tones when JARVIS wakes, listens, opens a panel, gets an answer to an approval or has news. Silent in gaming mode and during calls.';
export const VOLUME_LABEL = 'Volume';
export const SAMPLE_LABEL = 'Play a sample';
export const THINKING_LABEL = 'Thinking sound';
export const THINKING_HELP = 'A very quiet pulse while JARVIS works.';

export { soundChoice };

/** Volume 0..1 -> the slider's whole percent. */
export const volumePercent = volume => Math.round(Math.min(1, Math.max(0, Number(volume) || 0)) * 100);

/** The slider's percent -> volume 0..1 with two decimals, or null when it is not a number. */
export function percentVolume(percent) {
  const value = Number(percent);
  if (!Number.isFinite(value)) return null;
  return Math.round(Math.min(100, Math.max(0, value))) / 100;
}

/** The patch for one switch ('enabled' or 'thinking'), or null when nothing changes. */
export function switchPatch(choice, key, value) {
  if ((key !== 'enabled' && key !== 'thinking') || typeof value !== 'boolean' || value === choice[key]) return null;
  return { sound: { [key]: value } };
}

/** The patch for a new slider percent, or null when it is invalid or unchanged. */
export function volumePatch(choice, percent) {
  const volume = percentVolume(percent);
  if (volume === null || volume === choice.volume) return null;
  return { sound: { volume } };
}
