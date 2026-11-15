/*
 * The materialise enter/exit sequence for HUD frames (motion/react). The timing logic lives in
 * ./motionModel.js; this file turns a plan into motion variants and reads the three switches.
 *
 * Variant labels: 'hidden' (before enter), 'shown', 'gone' (exit). <Materialise> owns them and
 * hands the per-layer variants to <HudFrame> (border layer, content layer) through
 * MaterialiseContext, so a HudFrame outside a Materialise renders with no motion at all.
 */
import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { useReducedMotion } from 'motion/react';
import { MOTION_TOKENS, materialisePlan, motionMode, readTimings } from './motionModel.js';

export { MOTION_TOKENS, materialisePlan, motionMode, readTimings };

/** Per-layer variants from the nearest <Materialise>, or null. */
export const MaterialiseContext = createContext(null);
export const useMaterialiseLayers = () => useContext(MaterialiseContext);

const LOW_BATTERY = 0.2;
// Border reveal: a clip that opens from the top-left corner to the bottom-right one.
export const CLIP_HIDDEN = 'inset(0% 100% 100% 0%)';
export const CLIP_SHOWN = 'inset(0% 0% 0% 0%)';

const seconds = ms => Math.max(0, ms) / 1000;
const DEFAULT_EASE = 'easeOut';

/** Discharging at 20% or less (same rule as the presence core). A missing Battery API means not low. */
export function useLowBattery(enabled = true) {
  const [low, setLow] = useState(false);
  useEffect(() => {
    if (!enabled || typeof navigator === 'undefined' || typeof navigator.getBattery !== 'function') return undefined;
    let battery = null, live = true;
    const update = () => { if (live && battery) setLow(!battery.charging && battery.level <= LOW_BATTERY); };
    navigator.getBattery().then(value => {
      if (!live) return;
      battery = value;
      battery.addEventListener('chargingchange', update);
      battery.addEventListener('levelchange', update);
      update();
    }, () => {});
    return () => {
      live = false;
      battery?.removeEventListener('chargingchange', update);
      battery?.removeEventListener('levelchange', update);
    };
  }, [enabled]);
  return enabled && low;
}

/** 'full' | 'fade' | 'instant' from reduced motion, gaming mode and low battery. */
export function useMotionMode({ gaming = false } = {}) {
  const reducedMotion = !!useReducedMotion();
  const lowBattery = useLowBattery(!gaming);
  return motionMode({ reducedMotion, gaming, lowBattery });
}

/** The timings from the CSS tokens on :root, read once per mount. */
export function useMotionTimings() {
  const [timings] = useState(() => {
    if (typeof document === 'undefined' || typeof getComputedStyle !== 'function') return readTimings(null);
    const style = getComputedStyle(document.documentElement);
    return readTimings(name => style.getPropertyValue(name));
  });
  return timings;
}

/** Motion variants for every layer of a materialising frame. */
export function materialiseVariants(plan) {
  const ease = plan.ease || DEFAULT_EASE;
  const exitEase = plan.exitEase || 'easeIn';
  const { enter, exit } = plan;
  const fading = plan.mode === 'fade';
  const root = {
    hidden: { opacity: fading ? 0 : 1 },
    shown: { opacity: 1, transition: { duration: seconds(enter.fade.duration), ease: 'linear' } },
    gone: { opacity: fading ? 0 : 1, transition: { duration: seconds(exit.fade.duration), ease: 'linear' } },
  };
  if (plan.mode !== 'full') return { mode: plan.mode, root, border: {}, content: {}, item: {} };
  const rise = plan.rise;
  return {
    mode: plan.mode,
    root,
    border: {
      hidden: { clipPath: CLIP_HIDDEN },
      shown: { clipPath: CLIP_SHOWN, transition: { delay: seconds(enter.border.delay), duration: seconds(enter.border.duration), ease } },
      gone: { clipPath: CLIP_HIDDEN, transition: { delay: seconds(exit.border.delay), duration: seconds(exit.border.duration), ease: exitEase } },
    },
    content: {
      hidden: { opacity: 0, y: rise },
      shown: {
        opacity: 1, y: 0,
        transition: {
          delay: seconds(enter.content.delay), duration: seconds(enter.content.duration), ease,
          delayChildren: seconds(enter.content.delay), staggerChildren: seconds(enter.stagger),
        },
      },
      gone: { opacity: 0, y: rise, transition: { delay: seconds(exit.content.delay), duration: seconds(exit.content.duration), ease: exitEase } },
    },
    item: {
      hidden: { opacity: 0, y: rise },
      shown: { opacity: 1, y: 0, transition: { duration: seconds(enter.content.duration), ease } },
      gone: { opacity: 0, transition: { duration: seconds(exit.content.duration), ease: exitEase } },
    },
  };
}

/** Mode, plan and variants for one materialising element. */
export function useMaterialise({ gaming = false } = {}) {
  const mode = useMotionMode({ gaming });
  const timings = useMotionTimings();
  return useMemo(() => {
    const plan = materialisePlan(mode, timings);
    return { mode, plan, variants: materialiseVariants(plan) };
  }, [mode, timings]);
}
