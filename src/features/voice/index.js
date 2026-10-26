import useStore from '../../store';
import socket from '../../services/socket';
import { VoiceController } from './controller.js';

let controller = null;

/** The renderer's one live voice controller, created on first use (no media at import). */
export function liveVoice() {
  if (controller) return controller;
  controller = new VoiceController({
    socket,
    onChange: voice => useStore.setState({ voice }),
    onCaption: caption => useStore.getState().voiceCaption(caption),
    onEnd: sessionId => {
      // Brain approvals raised by this session cannot be answered once it ends.
      const store = useStore.getState();
      store.confirmationQueue.filter(request => request.voice_session_id === sessionId).forEach(request => store.resolveConfirmation(request.id));
    }
  });
  const stop = () => { if (controller.active()) controller.stop(); };
  // Privacy: hidden, minimised, suspended or locked windows never keep the microphone.
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
  window.addEventListener('blur', () => controller.holdEnd());
  window.electronAPI?.onCapturePause?.(stop);
  useStore.subscribe((state, previous) => {
    if (state.isLockScreenVisible && !previous.isLockScreenVisible) stop();
    if (state.currentProject !== previous.currentProject || state.conversationId !== previous.conversationId) stop();
  });
  return controller;
}

/** Current conversation and microphone for a voice gesture. */
export function voiceTarget() {
  const state = useStore.getState();
  return { conversationId: state.conversationId, deviceId: state.selectedMicId };
}
