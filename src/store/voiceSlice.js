/** Live voice status mirrored from the voice controller (src/features/voice). */
export const createVoiceSlice = () => ({
    voice: { state: 'off', mode: null, micOpen: false, playing: false, level: 0, error: '' },
    // settings.voice.mode: how the Quick assistant opens (Preferences > Voice).
    voiceDefaultMode: 'push_to_talk',
    // settings.voice.local_microphone: 'default' (Automatic, follows Windows) or { name, host_api };
    // every voice uses it (Preferences > Voice > Microphone).
    voiceMicrophone: 'default',
    // Tray voice and "Hey Jarvis" (src/services/events/localVoice.js): the core's latest
    // validated local_voice snapshot (or null), the speaker level while JARVIS speaks, and when
    // that session's end arrived (Date.now() ms, or null while it runs).
    localVoice: null,
    localVoiceLevel: 0,
    localVoiceEndedAt: null,
});
