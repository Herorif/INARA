import React from 'react';
import './presence.css';

const LABELS = {
  idle: 'STANDING BY',
  listening: 'LISTENING',
  working: 'WORKING',
  speaking: 'SPEAKING',
  offline: 'CORE OFFLINE',
};
const ALIASES = { recording: 'listening', transcribing: 'working', thinking: 'working', playback: 'speaking' };

/** Normalises any caller state (idle, listening, recording, transcribing, working, speaking, playback, offline). */
export const presenceState = state => ALIASES[state] || (LABELS[state] ? state : 'idle');
export const presenceLabel = state => LABELS[presenceState(state)];

/** Flat presence indicator: one hairline ring with a gap and a centre dot. */
export default function PresenceRing({ size = 36, state = 'idle', showLabel = false, className = '' }) {
  const value = presenceState(state);
  const label = LABELS[value];
  const radius = size / 2 - 2;
  const circumference = 2 * Math.PI * radius;
  return <span className={`presence ${className}`.trim()} data-presence={value} role="status" aria-label={`Assistant ${label.toLowerCase()}`}>
    <svg className="presence-ring" width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true" focusable="false">
      <circle className="presence-ring__arc" cx={size / 2} cy={size / 2} r={radius} fill="none" strokeWidth="1"
        strokeDasharray={`${circumference * .75} ${circumference * .25}`} />
      <circle className="presence-ring__dot" cx={size / 2} cy={size / 2} r="3" />
    </svg>
    {showLabel && <span className="presence-label hud-label">{label}</span>}
  </span>;
}
