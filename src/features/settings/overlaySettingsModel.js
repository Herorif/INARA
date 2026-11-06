// Pure copy and mappings for the voice overlay switch in Preferences (J4c): the saved
// value with the core's default and the update_settings patch.

export const OVERLAY_LABEL = 'Show JARVIS while you talk';
export const OVERLAY_HELP = 'A small panel above the taskbar shows what you and JARVIS say when you talk from the tray or say "Hey Jarvis". It never takes the keyboard, is hidden from screen sharing, and closes itself when you’re done.';
export const DEFAULT_OVERLAY = true;

/** Saved `settings.voice` -> { enabled }; a missing or non-boolean value is the default. */
export function overlayChoice(voice) {
  const value = voice && typeof voice === 'object' ? voice : {};
  return { enabled: typeof value.overlay === 'boolean' ? value.overlay : DEFAULT_OVERLAY };
}

/** The patch that turns the overlay on or off, or null when nothing changes. */
export function overlayPatch(choice, enabled) {
  if (typeof enabled !== 'boolean' || enabled === choice.enabled) return null;
  return { voice: { overlay: enabled } };
}
