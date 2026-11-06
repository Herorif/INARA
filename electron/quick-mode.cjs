// Quick assistant size switching for the workspace window (native-main.cjs, desktop.js).
// The window and the page both report mode changes to each other, so a mode is applied only
// when it actually changes; a repeated request is a no-op and can never bounce back and forth.

/**
 * @param {boolean} initial the mode the window was created in
 * @param {(quick: boolean) => void} apply resizes the window and tells the page
 */
function createQuickMode(initial, apply) {
  let current = initial === true;
  return {
    get: () => current,
    /** Switch to `value` (true: quick assistant). Returns whether anything changed. */
    set(value) {
      const next = value === true;
      if (next === current) return false;
      current = next;
      apply(next);
      return true;
    },
  };
}

module.exports = { createQuickMode };
