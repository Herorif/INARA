import { useEffect, useRef, useState } from 'react';
import useStore from '../../store';
import { levelFromSamples, smoothLevel } from '../voice/microphoneModel.js';

const ARIA_EVERY_MS = 250;
const REDUCED = '(prefers-reduced-motion: reduce)';

/** Whether `ref`'s element is on screen in a visible, unlocked window. */
function useShown(ref) {
  const locked = useStore((s) => s.isLockScreenVisible);
  const [visible, setVisible] = useState(() => globalThis.document?.visibilityState !== 'hidden');
  const [onScreen, setOnScreen] = useState(() => typeof globalThis.IntersectionObserver !== 'function');

  useEffect(() => {
    const update = () => setVisible(document.visibilityState !== 'hidden');
    document.addEventListener('visibilitychange', update);
    return () => document.removeEventListener('visibilitychange', update);
  }, []);
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof IntersectionObserver !== 'function') return undefined;
    const observer = new IntersectionObserver((entries) => setOnScreen(entries.some((entry) => entry.isIntersecting)));
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return visible && onScreen && !locked;
}

/**
 * The live input level of `deviceId` ('' for the default device) drawn into `fillRef`'s width,
 * only while `rowRef` is shown. Analysis only: the audio is never recorded, played or sent, and
 * the stream stops when the row is hidden or closed. `restartKey` reopens it (a new default).
 * Returns 'off' | 'starting' | 'live' | 'blocked'.
 */
export function useLevelMeter({ deviceId, restartKey, rowRef, fillRef, meterRef }) {
  const shown = useShown(rowRef);
  const [status, setStatus] = useState('off');
  const level = useRef(0);

  useEffect(() => {
    if (!shown) { setStatus('off'); return undefined; }
    const media = globalThis.navigator?.mediaDevices;
    const Context = globalThis.AudioContext;
    let cancelled = false, stream = null, context = null, source = null, frame = 0;
    const draw = (value) => {
      if (fillRef.current) fillRef.current.style.width = `${Math.round(value * 1000) / 10}%`;
    };
    const blocked = () => { if (!cancelled) setStatus('blocked'); };
    setStatus('starting');
    (async () => {
      try {
        if (!media?.getUserMedia || typeof Context !== 'function') throw Error('No microphone access here.');
        const opened = await media.getUserMedia({
          audio: {
            channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true,
            ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
          },
          video: false,
        });
        // Closed while permission or the device was pending: release the late stream at once.
        if (cancelled) { opened.getTracks().forEach((track) => track.stop()); return; }
        stream = opened;
        const track = stream.getAudioTracks()[0];
        if (!track) throw Error('No microphone track.');
        track.addEventListener('ended', blocked);
        context = new Context();
        source = context.createMediaStreamSource(stream);
        const analyser = context.createAnalyser();
        analyser.fftSize = 1024;
        source.connect(analyser); // never connected to the speakers
        await context.resume?.();
        if (cancelled) return;
        const samples = new Float32Array(analyser.fftSize);
        const reduced = globalThis.matchMedia?.(REDUCED);
        let last = performance.now(), spoken = 0;
        level.current = 0;
        const tick = (now) => {
          analyser.getFloatTimeDomainData(samples);
          level.current = smoothLevel(level.current, levelFromSamples(samples), now - last, !!reduced?.matches);
          last = now;
          draw(level.current);
          if (meterRef?.current && now - spoken >= ARIA_EVERY_MS) {
            meterRef.current.setAttribute('aria-valuenow', String(Math.round(level.current * 100)));
            spoken = now;
          }
          frame = requestAnimationFrame(tick);
        };
        setStatus('live');
        frame = requestAnimationFrame(tick);
      } catch {
        blocked();
      }
    })();
    return () => {
      cancelled = true;
      cancelAnimationFrame(frame);
      source?.disconnect();
      stream?.getTracks().forEach((track) => track.stop());
      context?.close().catch(() => {});
      level.current = 0;
      draw(0);
    };
  }, [shown, deviceId, restartKey, fillRef, meterRef]);
  return status;
}
