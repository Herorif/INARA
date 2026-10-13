import { emitSocket } from '../services/socket';

export const conversationForProject = (project) => {
    const key = `inara_conversation:${project}`;
    let id = localStorage.getItem(key);
    if (!id || !/^[0-9a-f-]{36}$/i.test(id)) {
        id = crypto.randomUUID();
        localStorage.setItem(key, id);
    }
    return id;
};

export const createChatSlice = (set, get) => ({
    messages: [],
    inputValue: '',
    textProcessing: false,
    conversationId: conversationForProject('temp'),
    conversationRestoring: false,

    setInputValue: (val) => set({ inputValue: val }),

    startNewConversation: () => {
        const id = crypto.randomUUID();
        localStorage.setItem(`inara_conversation:${get().currentProject}`, id);
        set({ conversationId: id, messages: [], conversationRestoring: true });
        emitSocket('resume_conversation', { conversation_id: id });
    },

    addMessage: (sender, text) => {
        set(state => ({
            messages: [...state.messages, { sender, text, time: new Date().toLocaleTimeString() }]
        }));
    },

    appendTranscription: (sender, text) => {
        set(state => {
            const prev = state.messages;
            const lastMsg = prev[prev.length - 1];
            if (lastMsg && lastMsg.sender === sender) {
                return {
                    messages: [
                        ...prev.slice(0, -1),
                        { ...lastMsg, text: lastMsg.text + text }
                    ]
                };
            }
            return {
                messages: [...prev, { sender, text, time: new Date().toLocaleTimeString() }]
            };
        });
    },

    handleSend: (e) => {
        if (e.key === 'Enter' && !e.isComposing && get().inputValue.trim()
            && get().backendConnected && !get().textProcessing && !get().conversationRestoring) {
            emitSocket('user_input', { text: get().inputValue,
                conversation_id: get().conversationId, request_id: crypto.randomUUID() });
            get().addMessage('You', get().inputValue);
            set({ inputValue: '', textProcessing: true });
        }
    },
});
