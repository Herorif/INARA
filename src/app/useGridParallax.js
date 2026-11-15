import { useEffect } from 'react';
import { parallaxOffset } from './glowModel.js';

/**
 * Pointer parallax for the workspace dot grid (workspace.css `.workspace-canvas--void`): moves the
 * grid up to PARALLAX_MAX px toward the pointer through --grid-x / --grid-y, at most once per
 * animation frame. Disabled means no listener at all and the grid back at rest.
 */
export default function useGridParallax(ref, enabled) {
  useEffect(() => {
    const element = ref.current;
    if (!enabled || !element) return undefined;
    let raf = 0, pointer = null;
    const flush = () => {
      raf = 0;
      const { x, y } = parallaxOffset(pointer, element.getBoundingClientRect());
      element.style.setProperty('--grid-x', `${x}px`);
      element.style.setProperty('--grid-y', `${y}px`);
    };
    const schedule = () => { if (!raf) raf = requestAnimationFrame(flush); };
    const move = event => { pointer = { x: event.clientX, y: event.clientY }; schedule(); };
    const leave = () => { pointer = null; schedule(); };
    element.addEventListener('pointermove', move, { passive: true });
    element.addEventListener('pointerleave', leave, { passive: true });
    return () => {
      if (raf) cancelAnimationFrame(raf);
      element.removeEventListener('pointermove', move);
      element.removeEventListener('pointerleave', leave);
      element.style.removeProperty('--grid-x');
      element.style.removeProperty('--grid-y');
    };
  }, [ref, enabled]);
}
