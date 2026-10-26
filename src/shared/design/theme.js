/**
 * Design tokens for code that cannot use CSS directly (three.js materials, 2D canvas).
 * Values are read from the custom properties in src/app/tokens.css; the hex fallbacks
 * mirror those tokens and are used where no document exists (Node tests, workers).
 */

/** Resolve a CSS custom property on :root, or `fallback` when it is unavailable. */
export function themeColor(name, fallback) {
  const property = name.startsWith('--') ? name : `--${name}`;
  try {
    if (typeof document === 'undefined' || typeof getComputedStyle !== 'function' || !document.documentElement) return fallback;
    const value = getComputedStyle(document.documentElement).getPropertyValue(property).trim();
    return value || fallback;
  } catch {
    return fallback;
  }
}

/** Neutral used when a mesh has no recognised material. */
export const MODEL_NEUTRAL = '#b8c4cf';
/** No emission (three.js needs an explicit colour to clear a highlight). */
export const NO_EMISSION = '#000000';

/**
 * Swatches for the CAD material names the backend understands. They describe the
 * physical material the user picked, so they stay fixed rather than following the UI theme.
 */
export const CAD_MATERIALS = Object.freeze({
  cyan: '#4fc8cf',
  amber: '#ed984d',
  titanium: '#9cabbf',
  ceramic: '#e0e8ea',
});

/** First and second tracked hand in the vision overlay (cheap enough to call per frame). */
export function handColors() {
  return [themeColor('--accent', '#70e0ed'), themeColor('--warn', '#ffc670')];
}

/** Palette for three.js scenes and canvas overlays. */
export function sceneColors() {
  return {
    background: themeColor('--bg-canvas', '#05080c'),
    gridMajor: themeColor('--line-strong', '#243241'),
    gridMinor: themeColor('--line', '#17212c'),
    model: MODEL_NEUTRAL,
    materials: CAD_MATERIALS,
    selection: themeColor('--accent', '#70e0ed'),
    /** emissiveIntensity for the selection tint, so the accent reads as a highlight, not a glow. */
    selectionIntensity: 0.22,
    none: NO_EMISSION,
    fillLight: themeColor('--text-2', '#9fb0bf'),
    axis: {
      x: themeColor('--danger', '#ff8585'),
      y: themeColor('--ok', '#6de2b5'),
      z: themeColor('--accent', '#70e0ed'),
      /** Opacity to apply to axis lines so they stay secondary to the model. */
      opacity: 0.6,
    },
    /** First and second tracked hand in the vision overlay. */
    hands: handColors(),
  };
}
