// The owner's default voice mode (settings.voice.mode, chosen in Preferences) applied to the
// Quick assistant. Pure: no store, socket or media.

export const VOICE_MODES = ['push_to_talk', 'conversation'];
export const DEFAULT_VOICE_MODE = 'push_to_talk';
// Conversation starts only as a direct result of opening the Quick assistant (the hotkey);
// if the core connects later than this, the owner turns Conversation on themselves.
export const AUTO_START_WINDOW_MS = 8000;

/** settings -> 'push_to_talk' | 'conversation', with the core's fallback for unknown values. */
export function defaultVoiceMode(settings) {
  const mode = settings && typeof settings === 'object' && settings.voice && typeof settings.voice === 'object'
    ? settings.voice.mode : undefined;
  return VOICE_MODES.includes(mode) ? mode : DEFAULT_VOICE_MODE;
}

/** Whether a just-opened Quick assistant should turn Conversation on now (at most once). */
export function shouldStartConversation({ mode, started, elapsed, connected, gaming, locked, restoring, liveState, speechState }) {
  return mode === 'conversation' && !started && elapsed >= 0 && elapsed <= AUTO_START_WINDOW_MS
    && !!connected && !gaming && !locked && !restoring
    && liveState === 'off' && ['idle', 'answered'].includes(speechState);
}

/** Primary voice control for the mode: Hold to talk for push to talk, none for conversation. */
export function holdButtonTone(mode) {
  return mode === 'conversation' ? 'btn--secondary' : 'btn--primary';
}
