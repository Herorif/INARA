import { emitSocket } from '../services/socket';

export const createChatSlice = (set, get) => ({
    messages: [],
    inputValue: '',

    setInputValue: (val) => set({ inputValue: val }),

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
        if (e.key === 'Enter' && get().inputValue.trim()) {
            emitSocket('user_input', { text: get().inputValue });
            get().addMessage('You', get().inputValue);
            set({ inputValue: '' });
        }
    },
});
