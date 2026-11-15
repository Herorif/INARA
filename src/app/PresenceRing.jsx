import React, { lazy, Suspense, useCallback, useEffect, useState } from 'react';
import { presenceMode, presenceState } from './coreModel.js';
import { flatGlow, glowMode } from './glowModel.js';
import './presence.css';

// three.js stays out of the main chunk: the live core loads only when it is shown.
// A chunk that cannot load counts as a failure too (flat ring, one warning).
function MissingCore({ onFail }) {
  useEffect(() => { onFail?.(); }, [onFail]);
  return null;
}
const JarvisCore = lazy(() => import('./JarvisCore').catch(error => {
  console.warn(`JARVIS core: the renderer could not load (${error?.message || error}); showing the flat presence ring.`);
  return { default: MissingCore };
}));

const LABELS = {
  idle: 'STANDING BY',
  listening: 'LISTENING',
  working: 'WORKING',
  speaking: 'SPEAKING',
  offline: 'CORE OFFLINE',
};
const REDUCED_MOTION = '(prefers-reduced-motion: reduce)';
const LOW_BATTERY = 0.2;

/** Normalises any caller state (idle, listening, recording, transcribing, working, speaking, playback, offline). */
export { presenceState };
export const presenceLabel = state => LABELS[presenceState(state)];

function useReducedMotion() {
  const [reduced, setReduced] = useState(() => typeof window.matchMedia === 'function' && window.matchMedia(REDUCED_MOTION).matches);
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined;
    const query = window.matchMedia(REDUCED_MOTION);
    const change = () => setReduced(query.matches);
    change();
    query.addEventListener('change', change);
    return () => query.removeEventListener('change', change);
  }, []);
  return reduced;
}

/** Discharging at 20% or less. A missing Battery API means not low power. */
function useLowBattery(enabled) {
  const [low, setLow] = useState(false);
  useEffect(() => {
    if (!enabled || typeof navigator.getBattery !== 'function') return undefined;
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

/** Flat presence indicator: one hairline ring with a gap and a centre dot. */
function FlatRing({ size }) {
  const radius = size / 2 - 2;
  const circumference = 2 * Math.PI * radius;
  return <svg className="presence-ring" width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true" focusable="false">
    <circle className="presence-ring__arc" cx={size / 2} cy={size / 2} r={radius} fill="none" strokeWidth="1"
      strokeDasharray={`${circumference * .75} ${circumference * .25}`} />
    <circle className="presence-ring__dot" cx={size / 2} cy={size / 2} r="3" />
  </svg>;
}

/**
 * Assistant presence. At 64 px or more it shows the live three.js core (src/app/JarvisCore.jsx)
 * unless motion is reduced, power is low or WebGL fails; otherwise the flat ring.
 * `lowPower` is gaming mode at every call site. Glow (glowModel.glowMode): gaming none, reduced
 * motion or low battery a still glow, otherwise breathing (the core's sprite or the ring's shadow).
 */
export default function PresenceRing({ size = 36, state = 'idle', showLabel = false, className = '', level = 0, lowPower = false }) {
  const value = presenceState(state);
  const label = LABELS[value];
  const reducedMotion = useReducedMotion();
  // Read at every size: below 64 px it only decides between a breathing and a still glow.
  const lowBattery = useLowBattery(!lowPower);
  // Any WebGL, model or context failure falls back to flat for the life of this mount.
  const [webgl, setWebgl] = useState(true);
  const onFail = useCallback(() => setWebgl(false), []);
  const mode = presenceMode({ size, reducedMotion, lowPower: lowPower || lowBattery, webgl });
  const glow = glowMode({ reducedMotion, gaming: lowPower, lowBattery });
  const flat = <FlatRing size={size} />;
  return <span className={`presence ${className}`.trim()} data-presence={value} data-presence-mode={mode} data-presence-glow={flatGlow(value, glow)} role="status" aria-label={`Assistant ${label.toLowerCase()}`}>
    {mode === '3d'
      ? <span className="presence-stage" style={{ width: size, height: size }}>
        <Suspense fallback={flat}><JarvisCore size={size} state={value} level={level} glow={glow} fallback={flat} onFail={onFail} /></Suspense>
      </span>
      : flat}
    {showLabel && <span className="presence-label hud-label">{label}</span>}
  </span>;
}
