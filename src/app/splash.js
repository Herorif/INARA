// Startup splash (the static #splash in index.html, painted before any script runs). Once the
// app shell has rendered, it fades out and is removed. It never adds a wait: dismissal starts
// at React's first commit, and with reduced motion the element goes at once.

// Matches the opacity transition on #splash (src/app/splash.css).
export const SPLASH_FADE_MS = 180;

/**
 * Fade out and remove the splash. Safe to call more than once (StrictMode runs effects twice).
 * @param {{ document?: Document, setTimeout?: (callback: () => void, ms: number) => unknown, reducedMotion?: boolean }} [options]
 * @returns {boolean} whether a splash was found and dismissed by this call
 */
export function dismissSplash({ document: doc = globalThis.document, setTimeout: later = globalThis.setTimeout, reducedMotion } = {}) {
    const splash = doc?.getElementById('splash');
    if (!splash || splash.classList.contains('is-done')) return false;
    const reduce = reducedMotion ?? !!doc.defaultView?.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    splash.classList.add('is-done');
    // Removal follows time, not transitionend: reduced motion removes the transition.
    if (reduce) splash.remove();
    else later(() => splash.remove(), SPLASH_FADE_MS);
    return true;
}
