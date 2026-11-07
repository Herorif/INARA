/**
 * Streamed typed replies. While JARVIS writes, one JARVIS message per request carries the
 * answer being written (`requestKey` = the request_id, `streaming: true`): the text of the
 * newest tool-loop `step` only. Text written before a tool call is narration: it moves to
 * `narration` (shown under the working line) and the message starts empty for the next step.
 * The final transcription replaces the text and clears the flag; a stream that ends without
 * one is `stopped`. Pure functions over the messages array: each returns the same array when
 * nothing changes.
 */

const indexOf = (messages, requestId) => messages.findIndex(message => message.requestKey === requestId);
const stepOf = value => (Number.isInteger(value) && value >= 0 ? value : 0);
const replace = (messages, index, message) => {
    const next = [...messages];
    next[index] = message;
    return next;
};

/** A `transcription_delta`: create the streaming message, or update its step's text. Late deltas are ignored. */
export function streamReply(messages, { requestId, step = 0, text, time = '' }) {
    if (typeof requestId !== 'string' || !requestId || typeof text !== 'string') return messages;
    const current = stepOf(step);
    const index = indexOf(messages, requestId);
    if (index === -1) {
        return [...messages, { sender: 'JARVIS', text, time, memory_sources: [], requestKey: requestId, streaming: true, step: current, narration: null }];
    }
    const message = messages[index];
    // Finished or stopped: a delta after the final (or after a cancel) changes nothing, and
    // an older step's text never comes back.
    if (!message.streaming || current < message.step) return messages;
    if (current === message.step && message.text === text) return messages;
    // A newer step's text starts the answer again from empty, and the narration clears.
    return replace(messages, index, { ...message, step: current, text, narration: null });
}

/** A tool step starts: the step's text so far becomes narration, the message empties and
 * waits for the next step. */
export function toolStepReply(messages, { requestId }) {
    if (typeof requestId !== 'string' || !requestId) return messages;
    const index = indexOf(messages, requestId);
    const message = messages[index];
    // No text before the first tool call: nothing streamed yet, so nothing to move.
    if (!message?.streaming || !message.text) return messages;
    return replace(messages, index, { ...message, narration: message.text, text: '', step: message.step + 1 });
}

/** The final transcription for a streamed request: authoritative text, streaming and narration cleared. Null when nothing streamed. */
export function finishReply(messages, { requestId, text, memory_sources = [] }) {
    if (typeof requestId !== 'string' || !requestId) return null;
    const index = indexOf(messages, requestId);
    if (index === -1) return null;
    return replace(messages, index, { ...messages[index], text, memory_sources, streaming: false, stopped: false, narration: null });
}

/** End streams that got no final (cancelled, failed or disconnected): marked stopped. An empty
 * message shows its last narration instead; otherwise its text is kept. */
export function stopReplies(messages, requestId = null) {
    let changed = false;
    const next = messages.map(message => {
        if (!message.streaming || (requestId && message.requestKey !== requestId)) return message;
        changed = true;
        return { ...message, text: message.text || message.narration || '', narration: null, streaming: false, stopped: true };
    });
    return changed ? next : messages;
}

/** True while the last message is a reply still being written. */
export const replyStreaming = messages => Boolean(messages.length && messages[messages.length - 1].streaming);

/** The narration of the reply still being written, or null. */
export const replyNarration = messages => {
    const last = messages[messages.length - 1];
    return last?.streaming && last.narration ? last.narration : null;
};

/** The chat slice's stream actions (a zustand `set`/`get` pair), kept here so they test without a socket. */
export const replyActions = (set, get) => ({
    /** The text being written for a typed request (transcription_delta). */
    streamReply: (requestId, step, text) => {
        set(state => {
            const messages = streamReply(state.messages, { requestId, step, text, time: new Date().toLocaleTimeString() });
            return messages === state.messages ? state : { messages, textPhase: null };
        });
    },

    /** A tool step started for a streamed request: its text so far becomes narration. */
    toolStepReply: requestId => {
        set(state => {
            const messages = toolStepReply(state.messages, { requestId });
            return messages === state.messages ? state : { messages };
        });
    },

    /** The final transcription replaces a streamed reply; false when nothing streamed for it. */
    finishReply: (requestId, text, memory_sources = []) => {
        const messages = finishReply(get().messages, { requestId, text, memory_sources });
        if (!messages) return false;
        set({ messages, textPhase: null });
        return true;
    },

    /** Streams that ended without a final keep their text, marked stopped. */
    stopReplies: (requestId = null) => {
        set(state => {
            const messages = stopReplies(state.messages, requestId);
            return messages === state.messages ? state : { messages };
        });
    },
});
