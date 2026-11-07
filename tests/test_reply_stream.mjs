import assert from 'node:assert/strict';
import test from 'node:test';
import { EventEmitter } from 'node:events';
import { createSubscriptions } from '../src/services/subscriptions.js';
import { registerConversationEvents } from '../src/services/events/conversation.js';
import { finishReply, replyActions, replyNarration, replyStreaming, stopReplies, streamReply, toolStepReply } from '../src/store/replyStream.js';

/** A zustand-shaped store holding the chat slice's real stream actions. */
function desk() {
  let state;
  const store = {
    getState: () => state,
    setState: partial => {
      const next = typeof partial === 'function' ? partial(state) : partial;
      if (next !== state) state = { ...state, ...next };
    },
  };
  const appended = [];
  state = {
    currentProject: 'temp', conversationId: 'conv', messages: [{ sender: 'You', text: 'Hi', time: '' }],
    textProcessing: true, textPhase: null, pendingTextRequest: 'req',
    appendTranscription: (sender, text, memory_sources) => {
      appended.push(text);
      store.setState(current => ({ messages: [...current.messages, { sender, text, time: '', memory_sources }] }));
    },
    addMessage: (sender, text) => store.setState(current => ({ messages: [...current.messages, { sender, text, time: '' }] })),
    ...replyActions(store.setState, store.getState),
  };
  const socket = new EventEmitter(), scope = createSubscriptions(socket);
  registerConversationEvents({ onSocket: scope.on, store, unsubs: [], resumeConversation: () => {}, conversationForProject: () => 'conv' });
  return { socket, state: () => state, reply: () => state.messages[1], appended };
}

const scope = { request_id: 'req', conversation_id: 'conv' };
const delta = (text, step = 0, request_id = 'req') => ({ ...scope, request_id, step, text });
const final = (text, request_id = 'req') => ({ sender: 'JARVIS', text, ...scope, request_id, project: 'temp' });
const status = (state, phase) => ({ state, ...(phase ? { phase } : {}), ...scope, project: 'temp' });

test('reducers create, update, replace and stop one message per request', () => {
  const start = [{ sender: 'You', text: 'Hi' }];
  const one = streamReply(start, { requestId: 'r', step: 0, text: 'Hel' });
  assert.equal(one.length, 2);
  assert.deepEqual({ ...one[1], time: '' }, { sender: 'JARVIS', text: 'Hel', time: '', memory_sources: [], requestKey: 'r', streaming: true, step: 0, narration: null });
  assert.equal(replyStreaming(one), true);
  const two = streamReply(one, { requestId: 'r', step: 0, text: 'Hello' });
  assert.equal(two.length, 2); assert.equal(two[1].text, 'Hello');
  assert.equal(streamReply(two, { requestId: 'r', step: 0, text: 'Hello' }), two, 'same text changes nothing');
  assert.equal(streamReply(two, { requestId: 'r', text: 42 }), two, 'non-text is ignored');
  const done = finishReply(two, { requestId: 'r', text: 'Hello there.', memory_sources: [{ title: 'Notes' }] });
  assert.equal(done[1].text, 'Hello there.'); assert.equal(done[1].streaming, false); assert.deepEqual(done[1].memory_sources, [{ title: 'Notes' }]);
  assert.equal(replyStreaming(done), false);
  assert.equal(streamReply(done, { requestId: 'r', step: 0, text: 'Hello th' }), done, 'a late delta is ignored');
  assert.equal(finishReply(two, { requestId: 'other', text: 'x' }), null, 'nothing streamed for it');
  const stopped = stopReplies(two, 'r');
  assert.equal(stopped[1].text, 'Hello'); assert.equal(stopped[1].stopped, true); assert.equal(stopped[1].streaming, false);
  assert.equal(streamReply(stopped, { requestId: 'r', step: 1, text: 'Hello again' }), stopped, 'nothing streams after a stop');
  assert.equal(stopReplies(done), done, 'finished replies are not stopped');
  assert.equal(stopReplies(two, 'other'), two);
});

test('reducers turn text before a tool call into narration and start the next step empty', () => {
  const start = [{ sender: 'You', text: 'Hi' }];
  const said = streamReply(start, { requestId: 'r', step: 0, text: 'Checking the notes.' });
  const tool = toolStepReply(said, { requestId: 'r' });
  assert.equal(tool[1].text, ''); assert.equal(tool[1].narration, 'Checking the notes.');
  assert.equal(replyNarration(tool), 'Checking the notes.');
  assert.equal(toolStepReply(tool, { requestId: 'r' }), tool, 'a second tool step with no new text keeps the narration');
  assert.equal(streamReply(tool, { requestId: 'r', step: 0, text: 'Checking' }), tool, 'an older step is ignored');
  const answer = streamReply(tool, { requestId: 'r', step: 1, text: 'It is' });
  assert.equal(answer[1].text, 'It is'); assert.equal(answer[1].narration, null); assert.equal(answer[1].step, 1);
  assert.equal(replyNarration(answer), null);
  // A higher step without a tool status first still starts from empty.
  const skipped = streamReply(said, { requestId: 'r', step: 2, text: 'Done' });
  assert.equal(skipped[1].text, 'Done'); assert.equal(skipped[1].narration, null);
  // No text before the first tool call: nothing to move, as before streaming.
  assert.equal(toolStepReply(start, { requestId: 'r' }), start);
  // Stopped while empty: the last narration becomes the message.
  const stopped = stopReplies(tool, 'r');
  assert.equal(stopped[1].text, 'Checking the notes.'); assert.equal(stopped[1].narration, null); assert.equal(stopped[1].stopped, true);
  // The final clears the narration.
  const done = finishReply(tool, { requestId: 'r', text: 'It is 40 mm.' });
  assert.equal(done[1].narration, null); assert.equal(done[1].text, 'It is 40 mm.');
});

test('a streamed request shows one message, the final replaces it, and a late delta is ignored', () => {
  const { socket, state, reply, appended } = desk();
  socket.emit('transcription_delta', delta('The bracket'));
  socket.emit('transcription_delta', delta('The bracket is 40'));
  assert.equal(state().messages.length, 2);
  assert.equal(reply().text, 'The bracket is 40');
  assert.equal(reply().streaming, true);
  socket.emit('transcription', final('The bracket is 40 mm.'));
  assert.equal(state().messages.length, 2);
  assert.equal(reply().text, 'The bracket is 40 mm.');
  assert.equal(reply().streaming, false);
  assert.deepEqual(appended, [], 'the final replaced the streamed text instead of appending');
  socket.emit('transcription_delta', delta('The bracket is'));
  assert.equal(reply().text, 'The bracket is 40 mm.');
  assert.equal(state().messages.length, 2);
  // Dedupe still works: a repeated final changes nothing.
  socket.emit('transcription', final('The bracket is 40 mm.'));
  assert.equal(state().messages.length, 2);
  socket.emit('text_status', status('idle'));
  assert.equal(reply().stopped, false, 'a finished reply is never marked stopped');
  assert.equal(state().textProcessing, false);
});

test('a tool step moves the text to narration under the working line until the answer starts', () => {
  const { socket, state, reply } = desk();
  socket.emit('transcription_delta', delta('Checking the notes.'));
  assert.equal(state().textPhase, null);
  socket.emit('text_status', status('processing', 'tool'));
  assert.equal(state().textProcessing, true);
  assert.equal(state().textPhase, 'tool');
  assert.equal(reply().text, '');
  assert.equal(replyNarration(state().messages), 'Checking the notes.');
  socket.emit('transcription_delta', delta('It is', 1));
  assert.equal(state().textPhase, null);
  assert.equal(reply().text, 'It is');
  assert.equal(replyNarration(state().messages), null);
  socket.emit('transcription_delta', delta('It is 40 mm.', 1));
  socket.emit('transcription', final('It is 40 mm.'));
  assert.equal(reply().text, 'It is 40 mm.', 'the final never shrinks the answer');
});

test('a cancelled or failed stream keeps its text and is marked stopped', () => {
  const { socket, state, reply } = desk();
  socket.emit('transcription_delta', delta('Working on'));
  socket.emit('text_status', status('idle'));
  assert.equal(reply().text, 'Working on');
  assert.equal(reply().stopped, true);
  assert.equal(reply().streaming, false);
  assert.equal(state().textProcessing, false);
  socket.emit('transcription_delta', delta('Working on more'));
  assert.equal(reply().text, 'Working on');
});

test('a stream stopped during a tool step shows the last narration with STOPPED', () => {
  const { socket, reply } = desk();
  socket.emit('transcription_delta', delta('Reading your notes.'));
  socket.emit('text_status', status('processing', 'tool'));
  socket.emit('text_status', status('idle'));
  assert.equal(reply().text, 'Reading your notes.');
  assert.equal(reply().narration, null);
  assert.equal(reply().stopped, true);
});

test('a reply that did not stream still arrives through the existing transcription path', () => {
  const { socket, state, appended } = desk();
  socket.emit('text_status', status('processing', 'tool'));
  assert.equal(state().messages.length, 1, 'a tool step before any text adds no message');
  socket.emit('transcription', final('Ready.'));
  assert.deepEqual(appended, ['Ready.']);
  assert.equal(state().messages.at(-1).text, 'Ready.');
  socket.emit('transcription', final('Ready.'));
  assert.deepEqual(appended, ['Ready.'], 'dedupe by request_id');
});

test('deltas for another conversation are ignored', () => {
  const { socket, state } = desk();
  socket.emit('transcription_delta', { request_id: 'req', conversation_id: 'old', step: 0, text: 'Stale' });
  socket.emit('transcription_delta', { conversation_id: 'conv', step: 0, text: 'No request' });
  assert.equal(state().messages.length, 1);
});
