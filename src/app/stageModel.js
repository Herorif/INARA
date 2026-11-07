// Pure model for the Assistant view's speaking core (no DOM, no React, no store), so node:test
// can check every rule. Conversation.jsx renders it; the core's caption rules for tray voice
// are the talking overlay's (src/overlay/overlayModel.js).
import { HOLD_MS, endOf, ringState, snapshotView, stripWake } from '../overlay/overlayModel.js';

/** Who has the microphone, as the stage names it. */
export const SOURCE_LABELS = Object.freeze({ window: 'Window mic', tray: 'Tray voice', wake: 'Hey Jarvis' });

/** Window voice counts as active with the microphone open or in one of these states. */
const WINDOW_ACTIVE = new Set(['connecting', 'listening', 'thinking', 'working', 'speaking']);
const STATE_WORDS = Object.freeze({
  connecting: 'CONNECTING', listening: 'LISTENING', thinking: 'THINKING', working: 'WORKING', speaking: 'SPEAKING',
});
const VOICE_PRESENCE = Object.freeze({ connecting: 'working', listening: 'listening', thinking: 'working', working: 'working', speaking: 'speaking' });
const REST_WORDS = Object.freeze({ idle: 'STANDING BY', working: 'WORKING', offline: 'CORE OFFLINE' });
/** The label while a finished tray session's last words are held (the overlay's "Voice is off"). */
export const ENDED_WORD = 'VOICE OFF';

const quoted = text => `“${text}”`;

export const windowVoiceActive = voice => !!voice && (voice.micOpen === true || WINDOW_ACTIVE.has(voice.state));

/** A tray session that has not ended. */
export const localRunning = snapshot => !!snapshot && typeof snapshot.session === 'string' && snapshot.state !== 'ended';

/** Window voice state as the stage shows it: an open microphone with no other state is listening. */
const windowState = voice => (WINDOW_ACTIVE.has(voice.state) ? voice.state : 'listening');

/**
 * The window caption: the newest caption message of the current turn (the transcript's last
 * message, when it is a live voice caption). The owner's words quoted while listening,
 * JARVIS's words while speaking, nothing otherwise.
 */
export function windowCaption(message, state) {
  // While JARVIS prepares an answer, the same placeholders as tray voice.
  if (state === 'thinking') return { text: 'Thinking…', tone: 'tertiary' };
  if (state === 'working') return { text: 'Working on it…', tone: 'tertiary' };
  if (!message || typeof message.captionKey !== 'string' || typeof message.text !== 'string') return null;
  const text = message.text.trim();
  if (!text) return null;
  if (message.sender === 'You' && state === 'listening') return { text: quoted(text), tone: 'primary' };
  if (message.sender === 'JARVIS' && state === 'speaking') return { text, tone: 'primary' };
  return null;
}

/**
 * The tray caption, from the overlay's rules: JARVIS's words (or "Thinking…" / "Working on it…"
 * while waiting) when there are any, otherwise the owner's words in quotes, dimmed once they
 * have finished. "Hey Jarvis" is never shown.
 */
export function localCaption(snapshot) {
  const view = snapshotView(snapshot);
  if (view.main) return view.main;
  if (!endOf(snapshot) && snapshot.state !== 'connecting' && stripWake(snapshot.user)) return view.top;
  return null;
}

const rest = ({ connected, processing }) => {
  const presence = !connected ? 'offline' : processing ? 'working' : 'idle';
  return { mode: 'rest', presence, label: REST_WORDS[presence], source: null, caption: null, level: 0, stop: null, microphone: false, until: null };
};

/**
 * Inputs: connected, processing (a typed request runs), voice (store.voice), caption (the
 * transcript's last message), local (the latest local_voice snapshot), localEndedAt (when its
 * end arrived), localLevel, and now (ms, same clock as localEndedAt).
 *
 * Output: { mode: 'rest' | 'voice', presence (a PresenceRing state), label (the state word),
 * source (a SOURCE_LABELS value or null), caption ({ text, tone } or null), level, stop
 * ('window' | 'local' | null), microphone (the composer's "MICROPHONE ON"), until (when an end
 * hold finishes, or null) }.
 *
 * Priority: a running tray session, then active window voice, then a finished tray session's
 * hold (quiet 4 s, error 8 s, now 0 s), then rest.
 */
export function stageView({ connected = false, processing = false, voice = null, caption = null, local = null, localEndedAt = null, localLevel = 0, now = 0 } = {}) {
  if (connected && localRunning(local)) {
    return {
      mode: 'voice',
      presence: ringState(local.state),
      label: STATE_WORDS[local.state] || STATE_WORDS.working,
      source: SOURCE_LABELS[local.source] || SOURCE_LABELS.tray,
      caption: localCaption(local),
      level: Number.isFinite(localLevel) ? Math.min(1, Math.max(0, localLevel)) : 0,
      stop: 'local',
      microphone: true,
      until: null,
    };
  }
  if (connected && windowVoiceActive(voice)) {
    const state = windowState(voice);
    return {
      mode: 'voice',
      presence: VOICE_PRESENCE[state],
      label: STATE_WORDS[state],
      source: SOURCE_LABELS.window,
      caption: windowCaption(caption, state),
      level: Number.isFinite(voice.level) ? Math.min(1, Math.max(0, voice.level)) : 0,
      stop: 'window',
      microphone: voice.micOpen === true,
      until: null,
    };
  }
  const end = connected && local && typeof local.session === 'string' ? endOf(local) : null;
  if (end && Number.isFinite(localEndedAt)) {
    const until = localEndedAt + (HOLD_MS[end.kind] ?? HOLD_MS.quiet);
    if (now < until) {
      return {
        mode: 'voice',
        presence: ringState('ended'),
        label: ENDED_WORD,
        source: SOURCE_LABELS[local.source] || SOURCE_LABELS.tray,
        caption: localCaption(local),
        level: 0,
        stop: null,
        microphone: false,
        until,
      };
    }
  }
  return rest({ connected, processing });
}

/**
 * Whether this renderer shows the speaking core (reported to the core as voice_stage): the
 * Conversation view is mounted, the document is visible, the window has focus and the app
 * is not locked.
 */
export const stageVisible = ({ mounted, documentVisible, focused, locked }) =>
  mounted === true && documentVisible === true && focused === true && locked !== true;
