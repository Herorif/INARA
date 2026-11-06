// Pure copy and mappings for "Hey Jarvis" in Preferences (J3c): the saved switch and
// sensitivity with the core's defaults, the sensitivity help, the status line, and the
// update_settings patches.

export const WAKE_WORD_LABEL = 'Listen for "Hey Jarvis"';  // the tray menu's words
export const WAKE_SWITCH_LABEL = 'Listen for "Hey Jarvis"';
export const WAKE_WORD_HELP = 'Say "Hey Jarvis" to talk to JARVIS from anywhere, even with this window closed. The microphone stays on to listen for the phrase, and nothing leaves this PC until JARVIS hears it.';
export const DEFAULT_WAKE_WORD = true;
export const DEFAULT_SENSITIVITY = 'normal';
export const WAKE_SENSITIVITIES = [
  { id: 'low', label: 'Low', help: 'Responds only to a clear "Hey Jarvis". Fewest false starts.' },
  { id: 'normal', label: 'Normal', help: 'Balanced for a typical room.' },
  { id: 'high', label: 'High', help: 'Hears you from further away, but may start by mistake more often.' },
];
const STATUS_TEXT = {
  listening: 'Listening for "Hey Jarvis".',
  paused: 'Paused while gaming mode is on.',
};

const sensitivityOf = (id) => WAKE_SENSITIVITIES.find((item) => item.id === id);

/** Saved `settings.voice` -> { enabled, sensitivity }; missing or unknown values are the defaults. */
export function wakeWordChoice(voice) {
  const value = voice && typeof voice === 'object' ? voice : {};
  return {
    enabled: typeof value.wake_word === 'boolean' ? value.wake_word : DEFAULT_WAKE_WORD,
    sensitivity: sensitivityOf(value.wake_sensitivity) ? value.wake_sensitivity : DEFAULT_SENSITIVITY,
  };
}

export function sensitivityHelp(id) {
  return (sensitivityOf(id) || sensitivityOf(DEFAULT_SENSITIVITY)).help;
}

/** The status line for a `wake_word_status` answer; '' for off, no answer yet, or a failure. */
export function wakeStatusText(status) {
  const state = status && typeof status === 'object' ? status.state : undefined;
  if (state === 'unavailable') return typeof status.message === 'string' ? status.message : '';
  return Object.hasOwn(STATUS_TEXT, state) ? STATUS_TEXT[state] : '';
}

/** The patch that turns "Hey Jarvis" on or off, or null when nothing changes. */
export function wakeWordPatch(choice, enabled) {
  if (typeof enabled !== 'boolean' || enabled === choice.enabled) return null;
  return { voice: { wake_word: enabled } };
}

/** The patch that saves a sensitivity, or null when it is unchanged or unknown. */
export function sensitivityPatch(choice, id) {
  if (!sensitivityOf(id) || id === choice.sensitivity) return null;
  return { voice: { wake_sensitivity: id } };
}
