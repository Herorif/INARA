import { useEffect } from 'react';
import { uiSounds } from './uiSounds.js';

/**
 * Tells the interface sounds what silences them right now (docs/SOUND.md): gaming mode and a
 * call in progress. Call it once from the app shell (CommandDeck), which owns both values.
 */
export default function useUiSoundContext({ gaming = false, onCall = false } = {}) {
  useEffect(() => { uiSounds().setContext({ gaming: !!gaming, onCall: !!onCall }); }, [gaming, onCall]);
}
