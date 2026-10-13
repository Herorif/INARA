export const createCadSlice = (set) => ({
    cadData: null,
    cadThoughts: '',
    cadRetryInfo: { attempt: 1, maxAttempts: 3, error: null },

    setCadData: (data) => set({ cadData: data }),
    setCadThoughts: (val) => set({ cadThoughts: val }),
    appendCadThought: (text) => set(state => ({ cadThoughts: state.cadThoughts + text })),
    setCadRetryInfo: (info) => set({ cadRetryInfo: info }),
});
