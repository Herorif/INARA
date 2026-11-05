import React, { useEffect, useRef, useState } from 'react';
import { WebGLRenderer } from 'three';
import { loadCoreScene } from './coreAsset.js';
import { createCore } from './coreScene.js';
import { coreLod, coreTarget, frameInterval, initialPose, isSettled, levelEnvelope, stepPose } from './coreModel.js';

const CONTEXT = { alpha: true, antialias: true, powerPreference: 'low-power', premultipliedAlpha: true, depth: true, stencil: false };
const pixelRatio = () => Math.min(window.devicePixelRatio || 1, 2);
/** The flat ring fades out over 160 ms (presence.css) and unmounts this long after the first frame. */
const FALLBACK_UNMOUNT_MS = 200;

const disposeTree = root => root.traverse(node => {
  node.geometry?.dispose();
  [node.material].flat().forEach(item => item?.dispose());
});

/**
 * Live three.js core (loaded lazily by PresenceRing). Owns its <canvas>, the WebGLRenderer and
 * the rAF loop. Shows `fallback` until the first frame is drawn, then crossfades it out while
 * the canvas fades in, and calls onReady; calls onFail once on any failure.
 */
export default function JarvisCore({ size, state, level = 0, fallback = null, onReady, onFail }) {
  const host = useRef(null);
  const [ready, setReady] = useState(false);
  const [fallbackGone, setFallbackGone] = useState(false);
  const live = useRef({ size, state, level, levelAt: -Infinity, onReady, onFail });
  const engine = useRef(null);

  useEffect(() => { live.current.onReady = onReady; live.current.onFail = onFail; }, [onReady, onFail]);
  useEffect(() => { live.current.state = state; engine.current?.wake(); }, [state]);
  useEffect(() => {
    if (Object.is(live.current.level, level)) return;
    live.current.level = level;
    live.current.levelAt = performance.now();
    engine.current?.wake();
  }, [level]);
  useEffect(() => { live.current.size = size; engine.current?.resize(); }, [size]);
  useEffect(() => {
    if (!ready) return undefined;
    const timer = setTimeout(() => setFallbackGone(true), FALLBACK_UNMOUNT_MS);
    return () => clearTimeout(timer);
  }, [ready]);

  useEffect(() => {
    // A fresh canvas per mount: a context lost on unmount can never be reused (StrictMode remounts).
    const canvas = document.createElement('canvas');
    canvas.className = 'presence-core';
    canvas.setAttribute('aria-hidden', 'true');
    host.current.append(canvas);
    let disposed = false, failed = false, drawn = false, raf = 0, last = null, onScreen = true, settling = true;
    let gl = null, renderer = null, core = null;
    let pose = initialPose(live.current.state), envelope = 0, clock = 0;

    const stop = () => {
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
      last = null;
    };
    const frame = now => {
      raf = 0;
      if (disposed || failed || !core || document.hidden || !onScreen) { last = null; return; }
      const props = live.current;
      const interval = frameInterval(props.state, settling);
      if (interval === null) { last = null; return; }
      if (last !== null && now - last < interval - 1) { raf = requestAnimationFrame(frame); return; }
      const dt = last === null ? 0 : Math.min(100, now - last);
      last = now;
      clock += dt / 1000;
      envelope = levelEnvelope(envelope, props.level, dt);
      const target = coreTarget(props.state, { envelope, levelAge: now - props.levelAt, time: clock });
      pose = stepPose(pose, target, dt);
      core.apply(pose);
      renderer.render(core.scene, core.camera);
      settling = !isSettled(pose, target);
      if (!drawn) {
        drawn = true;
        canvas.dataset.ready = 'true';
        setReady(true);
        props.onReady?.();
      }
      raf = requestAnimationFrame(frame);
    };
    const wake = () => {
      settling = true;
      if (!raf && !disposed && !failed && core && !document.hidden && onScreen) raf = requestAnimationFrame(frame);
    };
    const resize = () => {
      if (!renderer || !core) return;
      const value = live.current.size;
      renderer.setPixelRatio(pixelRatio());
      renderer.setSize(value, value, false);
      canvas.style.width = canvas.style.height = `${value}px`;
      core.setCssSize(value);
      core.setLod(coreLod(value));
      wake();
    };
    const fail = reason => {
      if (failed || disposed) return;
      failed = true;
      stop();
      console.warn(`JARVIS core: ${reason}; showing the flat presence ring.`);
      live.current.onFail?.(reason);
    };
    const onLost = () => fail('the WebGL context was lost');
    // Moving to a monitor with another scale: re-register for the new ratio and resize, so lines
    // stay 1 CSS px and the buffer stays sharp.
    let resolution = null;
    const onResolution = () => { watchResolution(); resize(); };
    const watchResolution = () => {
      resolution?.removeEventListener('change', onResolution);
      resolution = typeof window.matchMedia === 'function' ? window.matchMedia(`(resolution: ${window.devicePixelRatio || 1}dppx)`) : null;
      resolution?.addEventListener('change', onResolution);
    };
    const onVisibility = () => { if (document.hidden) stop(); else wake(); };
    const observer = typeof IntersectionObserver === 'function' ? new IntersectionObserver(entries => {
      onScreen = entries[entries.length - 1].isIntersecting;
      if (onScreen) wake(); else stop();
    }) : null;

    canvas.addEventListener('webglcontextlost', onLost);
    document.addEventListener('visibilitychange', onVisibility);
    observer?.observe(canvas);
    watchResolution();
    engine.current = { wake, resize };

    try { gl = canvas.getContext('webgl2', CONTEXT) || canvas.getContext('webgl', CONTEXT); } catch { gl = null; }
    if (!gl) fail('WebGL is unavailable');
    else {
      try {
        renderer = new WebGLRenderer({ canvas, context: gl, alpha: true, antialias: true, powerPreference: 'low-power' });
        renderer.setPixelRatio(pixelRatio());
        renderer.setSize(live.current.size, live.current.size, false);
        canvas.style.width = canvas.style.height = `${live.current.size}px`;
      } catch (error) {
        fail(`the WebGL renderer could not start (${error?.message || error})`);
      }
    }
    if (renderer) {
      loadCoreScene().then(root => {
        if (disposed || failed) { disposeTree(root); return; }
        const value = live.current.size;
        try {
          core = createCore(root, { lod: coreLod(value), cssSize: value });
        } catch (error) {
          disposeTree(root);
          throw error;
        }
        wake();
      }).catch(error => fail(`the core model could not be loaded (${error?.message || error})`));
    }

    return () => {
      disposed = true;
      stop();
      engine.current = null;
      observer?.disconnect();
      resolution?.removeEventListener('change', onResolution);
      document.removeEventListener('visibilitychange', onVisibility);
      canvas.removeEventListener('webglcontextlost', onLost);
      core?.dispose();
      core = null;
      if (renderer) {
        renderer.dispose();
        renderer.forceContextLoss();
      } else gl?.getExtension('WEBGL_lose_context')?.loseContext();
      canvas.remove();
    };
  }, []);

  return <>
    {!fallbackGone && fallback && <span className="presence-fallback" data-fading={ready ? 'true' : 'false'}>{fallback}</span>}
    <span ref={host} className="presence-core-host" aria-hidden="true" />
  </>;
}
