import React, { createContext, useContext, useEffect, useMemo, useRef } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { MaterialiseContext, useMaterialise, useMaterialiseLayers } from './materialise.js';
import { playCue } from '../../services/sound/uiSounds.js';
import { panelCue } from '../../services/sound/uiSoundsModel.js';

// AnimatePresence keeps rendering a leaving child's last element; the children come through this
// context instead, so they still get fresh props (for example `visible={false}`) while they leave.
const ChildrenContext = createContext(null);
function LatestChildren() { return useContext(ChildrenContext); }

/**
 * Materialises its children on show and reverses on hide (timings: ./materialise.js, ./motionModel.js). Put a
 * <HudFrame> inside to get the border draw; other children simply fade and rise with it.
 * Reduced motion and low battery give a plain opacity fade, gaming mode no animation at all.
 * `sound` (Stage panels): the panelOpen / panelClose interface cue as it enters and leaves
 * (docs/SOUND.md); the sound engine keeps it silent while the page settles after a restore.
 */
export default function Materialise({ show = true, gaming = false, sound = false, as = 'div', className = '', onExitComplete, children, ...rest }) {
  const { mode, variants } = useMaterialise({ gaming });
  const shown = useRef(undefined);
  useEffect(() => {
    const cue = sound ? panelCue(shown.current, show) : null;
    shown.current = show;
    if (cue) playCue(cue);
  }, [show, sound]);
  const Root = useMemo(() => (typeof as === 'string' ? motion[as] : motion.create(as)), [as]);
  return <ChildrenContext.Provider value={children}>
    <AnimatePresence initial={mode !== 'instant'} onExitComplete={onExitComplete}>
      {show && <Root key="materialise" className={className || undefined} data-motion-mode={mode}
        variants={variants.root} initial="hidden" animate="shown" exit="gone" {...rest}>
        <MaterialiseContext.Provider value={variants}><LatestChildren /></MaterialiseContext.Provider>
      </Root>}
    </AnimatePresence>
  </ChildrenContext.Provider>;
}

/** One child of a staggered list inside a materialising frame (each starts --stagger after the last). */
export function MaterialiseItem({ as = 'div', className = '', children, ...rest }) {
  const layers = useMaterialiseLayers();
  const Tag = useMemo(() => (typeof as === 'string' ? motion[as] : motion.create(as)), [as]);
  if (!layers) { const Plain = as; return <Plain className={className || undefined} {...rest}>{children}</Plain>; }
  return <Tag className={className || undefined} variants={layers.item} {...rest}>{children}</Tag>;
}
