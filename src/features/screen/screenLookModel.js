// Screen help (docs/SCREEN_HELP.md): the core's `screen_look` {state, region} while it takes
// the one approved screenshot. The workspace shows "Looking at your screen…" for at most 1 s.

export const SCREEN_LOOK_MS = 1000;
export const SCREEN_LOOK_TEXT = 'Looking at your screen…';

/** The notice for one `screen_look` event: true to show it, false to clear it, null to ignore. */
export function screenLookVisible(payload) {
  if (payload?.state === 'capturing') return true;
  if (payload?.state === 'done') return false;
  return null;
}
