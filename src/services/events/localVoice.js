import { LOCAL_VOICE_CLEARED, localVoicePatch, sanitizeLocalLevel, sanitizeLocalVoice } from '../../features/voice/localVoice.js';

/**
 * Tray voice ("Talk to JARVIS" and "Hey Jarvis") for the workspace's speaking core: the core's
 * validated `local_voice` snapshot and `local_voice_level`, cleared when the core disconnects.
 * Caption text is kept in the store only, never logged.
 */
export function registerLocalVoiceEvents({ onSocket, store: useStore, unsubs, now = () => Date.now() }) {
    const s = useStore.getState;
    unsubs.push(onSocket('local_voice', raw => {
        const snapshot = sanitizeLocalVoice(raw);
        if (!snapshot) return;
        useStore.setState(localVoicePatch(s().localVoice, s().localVoiceEndedAt, snapshot, now()));
    }));
    unsubs.push(onSocket('local_voice_level', raw => {
        const level = sanitizeLocalLevel(raw);
        if (level !== null) useStore.setState({ localVoiceLevel: level });
    }));
    unsubs.push(onSocket('disconnect', () => useStore.setState({ ...LOCAL_VOICE_CLEARED })));
}
