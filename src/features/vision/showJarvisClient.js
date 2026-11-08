// Show JARVIS: send one photo and one question as a turn of the current conversation. The
// owner's line ("📷 photo · <question>") goes into the chat as typed text; the answer streams
// into the chat through the usual transcription events and comes back in the ACK.
import { photoLine } from './showJarvisModel.js';

export const ASK_TIMEOUT_MS = 120_000;

/** Resolves {ok: true, text} or {ok: false, code, message}; never rejects. */
export function askAboutPhoto({ socket, store, question, image, requestId, timeout = ASK_TIMEOUT_MS }) {
  const state = store.getState();
  if (!state.backendConnected || !socket.connected) return Promise.resolve({ ok: false, code: 'offline', message: 'Connect to the core, then send the photo.' });
  if (state.textProcessing || state.conversationRestoring) return Promise.resolve({ ok: false, code: 'busy', message: 'JARVIS is still answering. Send the photo when the reply finishes.' });
  return new Promise(resolve => {
    let settled = false;
    const finish = result => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(result);
    };
    const timer = setTimeout(() => finish({ ok: false, code: 'timeout', message: 'JARVIS didn’t answer in time. Try again.' }), timeout);
    store.setState({ pendingTextRequest: requestId });
    state.addMessage('You', photoLine(question));
    store.setState({ textProcessing: true });
    try {
      socket.emit('vision_ask', { conversation_id: state.conversationId, request_id: requestId, question, image }, response => {
        if (response?.ok === true && typeof response.text === 'string') finish({ ok: true, text: response.text });
        else finish({ ok: false, code: typeof response?.code === 'string' ? response.code : 'failed', message: typeof response?.message === 'string' ? response.message : 'JARVIS couldn’t answer. Try again.' });
      });
    } catch {
      finish({ ok: false, code: 'failed', message: 'The photo couldn’t be sent. Try again.' });
    }
  });
}
