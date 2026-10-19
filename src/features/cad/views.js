/** Small revision-scoped camera bookmarks; never stores geometry or prompts. */
export const validView = value => value && ['position','target'].every(key => Array.isArray(value[key]) && value[key].length === 3 && value[key].every(number => typeof number === 'number' && Number.isFinite(number) && Math.abs(number) <= 100));
export function loadView(storage, key) {
  try { const raw = (storage || globalThis.localStorage).getItem(key); if (!raw || raw.length > 512) return null; const view = JSON.parse(raw); return validView(view) ? view : null; } catch { return null; }
}
export function saveView(storage, key, view) {
  if (!key || !validView(view)) return false;
  try { (storage || globalThis.localStorage).setItem(key, JSON.stringify(view)); return true; } catch { return false; }
}
