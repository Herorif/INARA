/**
 * Show JARVIS (docs/VISION_STUDIO.md#show-jarvis): one still photo from the live preview, one
 * question at a time. Pure state transitions; the panel keeps the photo bytes in memory only.
 *
 * Phases: 'camera-on' (live preview, no photo), 'still' (photo taken, consent card), 'sending'
 * (question sent, answer streaming), 'answered', 'follow-up' (asking again about the same photo).
 * Every function returns the same object when nothing changes.
 */

export const QUESTION_LIMIT = 500;
export const PHOTO_TTL_MS = 5 * 60 * 1000;
export const PHOTO_PREFIX = '📷 photo · ';
export const STILL_MAX_WIDTH = 1280;
export const STILL_QUALITY = 0.85;
export const MAX_IMAGE_BYTES = 1_500_000;
export const EXPOSURE_MS = 1000;

export const initialShow = Object.freeze({ phase: 'camera-on', photo: null, question: '', turns: [], error: '' });

const PHOTO_PHASES = new Set(['still', 'sending', 'answered', 'follow-up']);
const ASKING = new Set(['still', 'follow-up']);

/** Control characters become spaces and whitespace collapses, as the core does. */
export function cleanQuestion(text) {
  if (typeof text !== 'string') return '';
  // eslint-disable-next-line no-control-regex -- control characters are exactly what is removed
  return text.replace(/[\u0000-\u001f\u007f-\u009f\u200b-\u200f\u2028-\u202e\u2060-\u206f\ufeff]/g, ' ').replace(/\s+/g, ' ').trim();
}

export const validQuestion = text => {
  const clean = cleanQuestion(text);
  return clean.length >= 1 && clean.length <= QUESTION_LIMIT;
};

/** The owner's line in the conversation; the photo itself is never stored. */
export const photoLine = question => PHOTO_PREFIX + cleanQuestion(question);

export const hasPhoto = state => PHOTO_PHASES.has(state.phase) && !!state.photo;

/** The still's size: at most 1280 px wide, aspect ratio kept, never upscaled. */
export function stillSize(width, height, maxWidth = STILL_MAX_WIDTH) {
  if (!(width > 0) || !(height > 0)) return null;
  const scale = Math.min(1, maxWidth / width);
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}

/** Show JARVIS: freeze one frame. `prefill` is a question already given (for example by voice). */
export function takeStill(state, { id, takenAt, prefill = '' }) {
  if (state.phase === 'sending' || typeof id !== 'string' || !id || !Number.isFinite(takenAt)) return state;
  return { phase: 'still', photo: { id, takenAt }, question: typeof prefill === 'string' ? prefill.slice(0, QUESTION_LIMIT) : '', turns: [], error: '' };
}

export function editQuestion(state, text) {
  if (!ASKING.has(state.phase) || typeof text !== 'string') return state;
  const question = text.slice(0, QUESTION_LIMIT);
  return question === state.question && !state.error ? state : { ...state, question, error: '' };
}

/** Send is possible with a photo, a 1-500 character question, a connected core and no other reply running. */
export const canSend = (state, { connected = true, busy = false } = {}) =>
  ASKING.has(state.phase) && !!state.photo && connected && !busy && validQuestion(state.question);

export function sendQuestion(state, { requestId, connected = true, busy = false }) {
  if (typeof requestId !== 'string' || !requestId || !canSend(state, { connected, busy })) return state;
  const turn = { requestId, question: cleanQuestion(state.question), answer: '', status: 'sending' };
  return { ...state, phase: 'sending', question: '', error: '', turns: [...state.turns, turn] };
}

const updateTurn = (state, requestId, change) => {
  const index = state.turns.findIndex(turn => turn.requestId === requestId);
  if (index === -1) return null;
  const turns = [...state.turns];
  turns[index] = { ...turns[index], ...change };
  return turns;
};

/** The answer so far while it streams; ignored once the turn has finished. */
export function streamAnswer(state, { requestId, text }) {
  const turn = state.turns.find(item => item.requestId === requestId);
  if (state.phase !== 'sending' || !turn || turn.status !== 'sending' || typeof text !== 'string' || text === turn.answer) return state;
  return { ...state, turns: updateTurn(state, requestId, { answer: text }) };
}

export function answerQuestion(state, { requestId, text }) {
  const turn = state.turns.find(item => item.requestId === requestId);
  if (state.phase !== 'sending' || !turn || turn.status !== 'sending' || typeof text !== 'string') return state;
  return { ...state, phase: 'answered', turns: updateTurn(state, requestId, { answer: text, status: 'answered' }) };
}

/** No answer: the question goes back into the field with the reason, ready to send again. */
export function failQuestion(state, { requestId, message }) {
  const turn = state.turns.find(item => item.requestId === requestId);
  if (state.phase !== 'sending' || !turn || turn.status !== 'sending') return state;
  const turns = state.turns.filter(item => item.requestId !== requestId);
  return {
    ...state,
    phase: turns.length ? 'follow-up' : 'still',
    question: turn.question,
    turns,
    error: typeof message === 'string' && message.trim() ? message.trim() : 'JARVIS couldn’t answer. Try again.',
  };
}

export const askFollowUp = state => (state.phase === 'answered' ? { ...state, phase: 'follow-up', question: '', error: '' } : state);

export const cancelFollowUp = state => (state.phase === 'follow-up' && state.turns.length ? { ...state, phase: 'answered', question: '', error: '' } : state);

/** Retake, Cancel and Take another: the photo is dropped and the live preview returns. */
export const discardPhoto = state => (state.phase === 'sending' || state === initialShow ? state : initialShow);

/** After five minutes the photo is dropped (never while a question is on its way). */
export function expirePhoto(state, now) {
  if (!state.photo || state.phase === 'sending' || !Number.isFinite(now) || now - state.photo.takenAt < PHOTO_TTL_MS) return state;
  return initialShow;
}

/** Milliseconds until the photo is dropped, or null without one. */
export const photoExpiresIn = (state, now) => (state.photo ? Math.max(0, state.photo.takenAt + PHOTO_TTL_MS - now) : null);

/** The voice capture's error code for a camera session that did not give a frame. */
export function captureFailure(snapshot) {
  if (snapshot?.phase === 'paused') return ['hidden', 'minimized'].includes(snapshot.reason) ? 'hidden' : snapshot.reason === 'locked' ? 'locked' : 'failed';
  if (snapshot?.phase === 'failed') {
    return { NotAllowedError: 'denied', SecurityError: 'denied', NotFoundError: 'unavailable', OverconstrainedError: 'unavailable', NotReadableError: 'busy', AbortError: 'busy' }[snapshot.error] || 'failed';
  }
  if (snapshot?.phase === 'lost') return 'unavailable';
  return 'failed';
}
