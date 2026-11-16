import React, { useCallback, useEffect, useLayoutEffect, useReducer, useRef, useState } from 'react';
import { Square } from 'lucide-react';
import PresenceRing from '../app/PresenceRing.jsx';
import { cardOf, initialOverlay, nextDeadline, overlayReducer, overlayView } from './overlayModel.js';
import { createUiSoundEngine } from '../services/sound/uiSounds.js';

const now = () => performance.now();

/** The main caption: newest at the bottom; a top fade only while older lines are clipped. */
function MainSlot({ text, tone }) {
  const box = useRef(null);
  const inner = useRef(null);
  const [clipped, setClipped] = useState(false);
  useLayoutEffect(() => {
    const element = box.current, content = inner.current;
    if (!element || !content) return undefined;
    // Overflow off the top of a flex-end box is not part of scrollHeight: compare the text itself.
    const measure = () => setClipped(content.offsetHeight > element.clientHeight + 1);
    measure();
    if (typeof ResizeObserver !== 'function') return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    observer.observe(content);
    return () => observer.disconnect();
  }, [text]);
  return <div ref={box} className="overlay-main" data-tone={tone} data-clipped={clipped ? 'true' : 'false'}>
    <span ref={inner} className="overlay-main__text">{text}</span>
  </div>;
}

/**
 * The talking overlay panel. `bridge` is window.jarvisOverlay (electron/overlay-preload.js):
 * validated snapshots and levels in; ready, pointer, stop, open and done out.
 */
export default function OverlayApp({ bridge }) {
  const [state, dispatch] = useReducer(overlayReducer, initialOverlay);
  const [level, setLevel] = useState(0);
  const [entered, setEntered] = useState(false);
  const readySent = useRef(false);
  const doneSent = useRef(false);
  const sounds = useRef(null);
  const cardSounded = useRef(null);

  useEffect(() => {
    const offSnapshot = bridge.onSnapshot(snapshot => dispatch({ type: 'snapshot', snapshot, now: now() }));
    const offLevel = bridge.onLevel(value => setLevel(typeof value?.level === 'number' ? value.level : 0));
    return () => { offSnapshot(); offLevel(); };
  }, [bridge]);

  // Ready once the first snapshot has painted; main then shows the window (never focused).
  const hasSnapshot = state.snapshot !== null;
  useEffect(() => {
    if (!hasSnapshot || readySent.current) return undefined;
    let second = 0;
    const first = requestAnimationFrame(() => {
      second = requestAnimationFrame(() => {
        if (readySent.current) return;
        readySent.current = true;
        bridge.ready();
        setEntered(true);
      });
    });
    return () => { cancelAnimationFrame(first); cancelAnimationFrame(second); };
  }, [hasSnapshot, bridge]);

  // The close countdown: one timer for the next deadline.
  const deadline = nextDeadline(state);
  useEffect(() => {
    if (deadline === null) return undefined;
    // Timers can fire a fraction of a millisecond early: the deadline counts as reached.
    const timer = setTimeout(() => dispatch({ type: 'tick', now: Math.max(now(), deadline) }), Math.max(0, deadline - now()));
    return () => clearTimeout(timer);
  }, [deadline, state.phase]);

  useEffect(() => {
    if (state.phase !== 'closed' || doneSent.current) return;
    doneSent.current = true;
    bridge.done();
  }, [state.phase, bridge]);

  // S7.2: a new proactive card sounds the notify cue once (the owner's sound settings ride on it).
  const card = cardOf(state.snapshot);
  useEffect(() => {
    if (!card || cardSounded.current === card.id || !card.sound?.enabled) return;
    cardSounded.current = card.id;
    if (!sounds.current) sounds.current = createUiSoundEngine({ unlocked: true });
    sounds.current.setSettings({ enabled: true, volume: card.sound.volume });
    sounds.current.play('notify', { sample: true });
  }, [card]);
  useEffect(() => () => sounds.current?.dispose(), []);

  const pointer = useCallback(inside => {
    bridge.pointer(inside);
    dispatch({ type: 'pointer', inside, now: now() });
  }, [bridge]);
  const open = useCallback(() => {
    bridge.open();
    dispatch({ type: 'open', now: now() });
  }, [bridge]);

  const view = overlayView(state);
  if (!hasSnapshot) return null;
  return <section className="overlay-panel" aria-label="JARVIS voice" data-visible={entered && view.visible ? 'true' : 'false'}
    data-phase={view.phase} data-end={view.endKind || 'none'}
    onPointerEnter={() => pointer(true)} onPointerLeave={() => pointer(false)}>
    <PresenceRing size={64} state={view.ring} level={view.ring === 'speaking' ? level : 0} />
    <div className="overlay-text" aria-live="polite">
      {view.top && <div className="overlay-top" data-tone={view.top.tone}>{view.top.text}</div>}
      {view.main && <MainSlot text={view.main.text} tone={view.main.tone} />}
    </div>
    {/* Stop always sits at the far right (the approved mockup); Open JARVIS comes before it. */}
    {(view.showStop || view.showOpen) && <div className="overlay-actions">
      {view.showOpen && <button type="button" className="overlay-button overlay-button--text" onClick={open}>Open JARVIS</button>}
      {view.showStop && <button type="button" className="overlay-button overlay-button--icon" aria-label="Stop talking" title="Stop talking" onClick={() => bridge.stop()}>
        <Square size={14} aria-hidden="true" focusable="false" />
      </button>}
    </div>}
  </section>;
}
