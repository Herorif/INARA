import {safeMemorySources} from '../../transport/memorySources.ts';
// A core or saved transcript from before the INARA -> JARVIS rename (5 Nov 2026) signs replies 'INARA';
// show them as JARVIS. Remove one release after the rename, with the other wire fallbacks.
const sender = value => (value === 'INARA' ? 'JARVIS' : value);

/** Conversation/project event scope, including bounded transcription deduplication. */
export function registerConversationEvents({ onSocket, store: useStore, unsubs, resumeConversation, conversationForProject }) {
    const s = useStore.getState;
    const completedTextRequests = new Set();
    const stale = data => (data.conversation_id && data.conversation_id !== s().conversationId)
        || (data.project && data.project !== s().currentProject);
    unsubs.push(onSocket('text_status', data => {
        if (stale(data) || (data.request_id && s().pendingTextRequest && data.request_id !== s().pendingTextRequest)) return;
        const processing = data.state === 'processing';
        const tool = processing && data.phase === 'tool';
        useStore.setState({ textProcessing: processing, textPhase: tool ? 'tool' : null });
        // Text written before a tool call was narration: it moves under the working line.
        if (tool && data.request_id) s().toolStepReply?.(data.request_id);
        // Idle without a final transcription (cancelled or failed): the partial reply is stopped.
        if (!processing && data.request_id && !completedTextRequests.has(data.request_id)) s().stopReplies?.(data.request_id);
    }));
    unsubs.push(onSocket('conversation_restored', data => {
        if (data.conversation_id !== s().conversationId || data.project !== s().currentProject) return;
        useStore.setState({ conversationRestoring: false, messages: data.messages.map(m => ({
            sender: m.role === 'user' ? 'You' : 'JARVIS', text: m.content, time: '', memory_sources: safeMemorySources(m.memory_sources),
        })) });
        // Tray voice talked in another conversation while the workspace was closed: show that one.
        if (data.latest_conversation_id && data.latest_conversation_id !== data.conversation_id) {
            s().adoptConversation?.(data.latest_conversation_id);
        }
    }));
    unsubs.push(onSocket('conversation_restore_failed', data => {
        if (data.conversation_id && data.conversation_id !== s().conversationId) return;
        useStore.setState({ conversationRestoring: false });
        s().addMessage('System', data.msg || 'Conversation could not be restored.');
    }));

    // --- Transcription ---
    // The step's text so far (cumulative) while a typed request streams; the final transcription wins.
    unsubs.push(onSocket('transcription_delta', data => {
        if (stale(data) || typeof data.request_id !== 'string' || completedTextRequests.has(data.request_id)) return;
        s().streamReply?.(data.request_id, data.step, data.text);
    }));
    unsubs.push(onSocket('transcription', (data) => {
        if (stale(data)) return;
        if (data.request_id) {
            if (completedTextRequests.has(data.request_id)) return;
            completedTextRequests.add(data.request_id);
            if (completedTextRequests.size > 64) {
                completedTextRequests.delete(completedTextRequests.values().next().value);
            }
        }
        // A task call's outcome (C4) arrives later as its own message, never joined to the last one.
        if (data.kind === 'task_call_outcome') s().addMessage(sender(data.sender), data.text);
        else if (!(data.request_id && s().finishReply?.(data.request_id, data.text, safeMemorySources(data.memory_sources)))) {
            s().appendTranscription(sender(data.sender), data.text, safeMemorySources(data.memory_sources));
        }
    }));

    // --- Project ---
    unsubs.push(onSocket('project_update', (data) => {
        const changed = data.project !== s().currentProject;
        useStore.setState({ currentProject: data.project, conversationId: conversationForProject(data.project), ...(changed ? { activity: [], studioSelection: null, studioHandoff: null, confirmationRequest: null, pendingTextRequest: null, textProcessing: false } : {}) });
        if (changed && s().backendConnected) resumeConversation(true);
    }));

}
