/**
 * Per-viewer storage keys. The product was renamed from INARA to JARVIS on 5 Nov 2026 and its
 * keys moved from `inara…` to `jarvis…`. Reading a `jarvis…` key that is not set yet falls back
 * once to its pre-rename name and moves the value across, so the client id, conversations and
 * per-viewer settings survive the rename. Drop the fallback one release after the rename.
 */
const legacyKey = key => (/^jarvis/.test(key) ? key.replace(/^jarvis/, 'inara') : null);

/** The stored value for `key` (after a one-time move from its legacy name), or null. Never throws. */
export function readMigrated(storage, key) {
  try {
    const store = storage || globalThis.localStorage;
    const value = store.getItem(key);
    const legacy = value === null ? legacyKey(key) : null;
    if (!legacy) return value;
    const old = store.getItem(legacy);
    if (old === null) return null;
    try {
      store.setItem(key, old);
      store.removeItem(legacy);
    } catch {
      // Storage is full or blocked: keep using the legacy value this time.
    }
    return old;
  } catch {
    return null;
  }
}
