export const createAudioSlice = (set) => ({
    aiAudioData: new Array(64).fill(0),
    micAudioData: new Array(32).fill(0),

    setAiAudioData: (data) => set({ aiAudioData: data }),
    setMicAudioData: (data) => set({ micAudioData: data }),
});
