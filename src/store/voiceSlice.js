/** Live voice status mirrored from the voice controller (src/features/voice). */
export const createVoiceSlice = () => ({
    voice: { state: 'off', mode: null, micOpen: false, playing: false, level: 0, error: '' },
});
