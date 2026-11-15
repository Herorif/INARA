import { uiSounds } from '../sound/uiSounds.js';
import {
  briefingNoticeKey, createNoticeTracker, localVoiceCue, soundChoice, thinkingActive, vipNoticeKey, voiceCue,
} from '../sound/uiSoundsModel.js';

/**
 * Interface sounds (docs/SOUND.md): `settings.sound` into the engine, and the store changes
 * that sound a cue — a voice session starting (wake), listening starting (listen), JARVIS
 * working (thinking, optional), a new VIP call card or morning briefing card (notify).
 * Approvals and the Live design panel sound from their own components. A (re)connect or an
 * unlock settles the engine, so the state the core re-sends then is silent. Returns the
 * cleanup for the store subscription and the thinking timer (socket listeners leave with
 * the subscription scope).
 */
export function registerSoundEvents({ onSocket, store: useStore, unsubs, engine = uiSounds(), every = 1000 }) {
    engine.start();
    const notices = createNoticeTracker();
    // Cards already on screen when this starts are not news.
    const initial = useStore.getState();
    notices.fresh(vipNoticeKey(initial.callAlerts?.alert));
    notices.fresh(briefingNoticeKey(initial.briefing));

    unsubs.push(onSocket('settings', settings => {
        if (settings && typeof settings === 'object') engine.setSettings(soundChoice(settings.sound));
    }));
    unsubs.push(onSocket('connect', () => engine.settle()));
    unsubs.push(onSocket('auth_status', data => { if (data?.authenticated) engine.settle(); }));

    // Checked every second; the engine's scheduler keeps the pulse at most once per 4 s.
    let thinkingTimer = 0;
    const thinking = on => {
        if (on && !thinkingTimer) {
            engine.play('thinking');
            thinkingTimer = setInterval(() => engine.play('thinking'), every);
        } else if (!on && thinkingTimer) {
            clearInterval(thinkingTimer);
            thinkingTimer = 0;
        }
    };

    const stopStore = useStore.subscribe((state, previous) => {
        if (state.voice !== previous.voice) {
            const cue = voiceCue(previous.voice, state.voice);
            if (cue) engine.play(cue);
        }
        if (state.localVoice !== previous.localVoice) {
            const cue = localVoiceCue(previous.localVoice, state.localVoice);
            if (cue) engine.play(cue);
        }
        if (state.voice !== previous.voice || state.localVoice !== previous.localVoice) {
            thinking(thinkingActive(state.voice, state.localVoice));
        }
        const vip = state.callAlerts?.alert;
        if (vip !== previous.callAlerts?.alert && notices.fresh(vipNoticeKey(vip))) engine.play('notify');
        if (state.briefing !== previous.briefing && notices.fresh(briefingNoticeKey(state.briefing))) engine.play('notify');
    });
    return () => { stopStore(); thinking(false); };
}
