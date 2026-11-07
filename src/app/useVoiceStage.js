import { useEffect, useRef, useState } from 'react';
import useStore from '../store';
import { emitSocket } from '../services/socket';
import { stageVisible } from './stageModel.js';

/** Visibility changes settle for this long before the core hears of them. */
export const STAGE_REPORT_DELAY_MS = 250;

const documentVisible = () => document.visibilityState === 'visible';
const focused = () => typeof document.hasFocus !== 'function' || document.hasFocus();

/**
 * Tells the core whether this window shows the speaking core (`voice_stage`), so tray voice
 * opens the talking overlay only when it does not. Call it from the mounted Conversation view:
 * changes are sent 250 ms after they settle and again after every (re)connect, and unmounting
 * sends `{visible: false}` at once.
 */
export function useVoiceStageReport() {
  const connected = useStore(state => state.backendConnected);
  const locked = useStore(state => state.isLockScreenVisible);
  const [page, setPage] = useState(() => ({ documentVisible: documentVisible(), focused: focused() }));
  const sent = useRef(null);
  const visible = stageVisible({ mounted: true, documentVisible: page.documentVisible, focused: page.focused, locked });

  useEffect(() => {
    const update = () => setPage({ documentVisible: documentVisible(), focused: focused() });
    document.addEventListener('visibilitychange', update);
    window.addEventListener('focus', update);
    window.addEventListener('blur', update);
    return () => {
      document.removeEventListener('visibilitychange', update);
      window.removeEventListener('focus', update);
      window.removeEventListener('blur', update);
    };
  }, []);

  useEffect(() => {
    if (!connected) {
      sent.current = null; // the core forgot this socket's report: send it again on reconnect
      return undefined;
    }
    if (sent.current === visible) return undefined;
    const timer = setTimeout(() => {
      if (emitSocket('voice_stage', { visible })) sent.current = visible;
    }, STAGE_REPORT_DELAY_MS);
    return () => clearTimeout(timer);
  }, [connected, visible]);

  useEffect(() => () => {
    if (sent.current !== false) emitSocket('voice_stage', { visible: false });
    sent.current = null;
  }, []);
}
