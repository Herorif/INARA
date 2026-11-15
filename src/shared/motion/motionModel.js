/*
 * The "materialise" motion (9NovWork specs S13a, audit B "Motion"): pure logic, tested without React.
 *
 * Enter: the frame draws its border in --dur-draw, then the content fades and rises RISE_PX in
 * --dur-fill, children staggering by --stagger. Exit: the reverse in --dur-exit (content first,
 * then the border). Durations come only from the CSS tokens in src/app/tokens.css; a token that
 * cannot be read counts as 0 ms (instant), so there is no second copy of the numbers here.
 *
 * Modes, from the three existing switches:
 * - 'instant': gaming mode. Nothing animates.
 * - 'fade':    reduced motion or low battery. No movement, a plain --dur-fast opacity fade.
 * - 'full':    everything above.
 */

export const RISE_PX = 8;

/** CSS custom properties the timings are read from. */
export const MOTION_TOKENS = Object.freeze({
  draw: '--dur-draw',
  fill: '--dur-fill',
  exit: '--dur-exit',
  stagger: '--stagger',
  fade: '--dur-fast',
  ease: '--ease-out',
});

/** Gaming wins (instant), then reduced motion or low battery (fade); otherwise full. */
export function motionMode({ reducedMotion = false, gaming = false, lowBattery = false } = {}) {
  if (gaming) return 'instant';
  if (reducedMotion || lowBattery) return 'fade';
  return 'full';
}

/** "160ms" / "0.2s" / ".2s" -> milliseconds; anything else -> null. */
export function parseDuration(text) {
  const match = /^\s*(\d*\.?\d+)\s*(ms|s)\s*$/i.exec(String(text ?? ''));
  if (!match) return null;
  const value = Number(match[1]) * (match[2].toLowerCase() === 's' ? 1000 : 1);
  return Number.isFinite(value) && value >= 0 ? value : null;
}

/** "cubic-bezier(.2,.8,.2,1)" -> [0.2, 0.8, 0.2, 1]; anything else -> null. */
export function parseEase(text) {
  const match = /^\s*cubic-bezier\(([^)]*)\)\s*$/i.exec(String(text ?? ''));
  if (!match) return null;
  const values = match[1].split(',').map(part => Number(part.trim()));
  if (values.length !== 4 || values.some(value => !Number.isFinite(value))) return null;
  if (values[0] < 0 || values[0] > 1 || values[2] < 0 || values[2] > 1) return null;
  return values;
}

/** The same curve played backwards in time (for the exit). */
export function reverseEase(ease) {
  if (!Array.isArray(ease)) return ease;
  const [x1, y1, x2, y2] = ease;
  return [1 - x2, 1 - y2, 1 - x1, 1 - y1].map(value => Math.round(value * 1000) / 1000);
}

/**
 * Reads the timings through `read(name) -> string` (for example a getComputedStyle lookup).
 * Unreadable durations are 0 ms; an unreadable ease is null (the caller's default curve).
 */
export function readTimings(read) {
  const get = name => {
    try { return typeof read === 'function' ? read(name) : ''; } catch { return ''; }
  };
  const ms = name => parseDuration(get(name)) ?? 0;
  return {
    draw: ms(MOTION_TOKENS.draw),
    fill: ms(MOTION_TOKENS.fill),
    exit: ms(MOTION_TOKENS.exit),
    stagger: ms(MOTION_TOKENS.stagger),
    fade: ms(MOTION_TOKENS.fade),
    ease: parseEase(get(MOTION_TOKENS.ease)),
  };
}

const span = (delay = 0, duration = 0) => ({ delay, duration });

/**
 * The whole sequence in milliseconds for one mode. `fade` is the opacity fade of the outer
 * element (fade mode only); `border`, `content` and `stagger` only move in full mode.
 */
export function materialisePlan(mode, timings = {}) {
  const t = { draw: 0, fill: 0, exit: 0, stagger: 0, fade: 0, ease: null, ...timings };
  const still = {
    mode,
    rise: 0,
    ease: t.ease,
    exitEase: reverseEase(t.ease),
    enter: { fade: span(), border: span(), content: span(), stagger: 0, total: 0 },
    exit: { fade: span(), content: span(), border: span(), total: 0 },
  };
  if (mode === 'instant') return still;
  if (mode === 'fade') {
    return { ...still, enter: { ...still.enter, fade: span(0, t.fade), total: t.fade }, exit: { ...still.exit, fade: span(0, t.fade), total: t.fade } };
  }
  // Exit is the enter reversed, squeezed into --dur-exit: content out in the first half, border in the second.
  const half = t.exit / 2;
  return {
    ...still,
    rise: RISE_PX,
    enter: { fade: span(), border: span(0, t.draw), content: span(t.draw, t.fill), stagger: t.stagger, total: t.draw + t.fill },
    exit: { fade: span(), content: span(0, half), border: span(half, half), total: t.exit },
  };
}

/** When child `index` (0-based) of a staggered list starts to appear, in ms. */
export function staggerDelay(plan, index) {
  const i = Math.max(0, Math.floor(Number(index) || 0));
  return plan.enter.content.delay + i * plan.enter.stagger;
}

/** Total enter time for a list of `count` staggered children, in ms. */
export function staggerTotal(plan, count) {
  const n = Math.max(0, Math.floor(Number(count) || 0));
  if (!n) return plan.enter.total;
  return Math.max(plan.enter.total, staggerDelay(plan, n - 1) + plan.enter.content.duration);
}

/** "01 · WORLD": index and title, either one alone, or '' when neither is given. */
export function frameLabel(index, title) {
  return [index, title].map(part => (part == null ? '' : String(part).trim())).filter(Boolean).join(' · ');
}
