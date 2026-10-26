/** Pure live voice view helpers: no media, store or socket. */

/** Command-bar chip: OFF, READY, LISTENING (microphone open) or SPEAKING. */
export const voiceChip = ({ connected, gaming, voice }) => !connected || gaming ? 'OFF'
  : voice?.state === 'speaking' ? 'SPEAKING'
  : voice?.micOpen || voice?.state === 'listening' ? 'LISTENING'
  : 'READY';

/** PresenceRing state: speaking pulses, listening rotates, brain hand-off shows working. */
export const voicePresence = ({ connected, processing = false, voice }) => !connected ? 'offline'
  : voice?.state === 'speaking' ? 'speaking'
  : voice?.micOpen || voice?.state === 'listening' ? 'listening'
  : processing || ['connecting', 'thinking', 'working'].includes(voice?.state) ? 'working'
  : 'idle';
