import {safeMemorySources} from '../../transport/memorySources.ts';
/** Conversation/project event scope, including bounded transcription deduplication. */
export function registerConversationEvents({ onSocket, store: useStore, unsubs, resumeConversation, conversationForProject }) {
    const s = useStore.getState;
    const completedTextRequests = new Set();
    const stale = data => (data.conversation_id && data.conversation_id !== s().conversationId)
        || (data.project && data.project !== s().currentProject);
    unsubs.push(onSocket('text_status', data => {
        if (stale(data) || (data.request_id && s().pendingTextRequest && data.request_id !== s().pendingTextRequest)) return;
        useStore.setState({ textProcessing: data.state === 'processing' });
    }));
    unsubs.push(onSocket('conversation_restored', data => {
        if (data.conversation_id !== s().conversationId || data.project !== s().currentProject) return;
        useStore.setState({ conversationRestoring: false, messages: data.messages.map(m => ({
            sender: m.role === 'user' ? 'You' : 'INARA', text: m.content, time: '', memory_sources: safeMemorySources(m.memory_sources),
        })) });
    }));
    unsubs.push(onSocket('conversation_restore_failed', data => {
        if (data.conversation_id && data.conversation_id !== s().conversationId) return;
        useStore.setState({ conversationRestoring: false });
        s().addMessage('System', data.msg || 'Conversation could not be restored.');
    }));

    // --- Transcription ---
    unsubs.push(onSocket('transcription', (data) => {
        if (stale(data)) return;
        if (data.request_id) {
            if (completedTextRequests.has(data.request_id)) return;
            completedTextRequests.add(data.request_id);
            if (completedTextRequests.size > 64) {
                completedTextRequests.delete(completedTextRequests.values().next().value);
            }
        }
        s().appendTranscription(data.sender, data.text, safeMemorySources(data.memory_sources));
    }));

    // --- Project ---
    unsubs.push(onSocket('project_update', (data) => {
        const changed = data.project !== s().currentProject;
        useStore.setState({ currentProject: data.project, conversationId: conversationForProject(data.project), ...(changed ? { activity: [], studioSelection: null, studioHandoff: null, confirmationRequest: null, pendingTextRequest: null, textProcessing: false } : {}) });
        if (changed && s().backendConnected) resumeConversation(true);
    }));

}
