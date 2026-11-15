import React from 'react';
import { motion } from 'motion/react';
import { useMaterialiseLayers } from '../motion/materialise.js';
import { frameLabel } from '../motion/motionModel.js';
import './hud.css';

/**
 * HUD frame for Stage panels and overlays only, never ordinary cards or forms (9NovWork audit B):
 * 8 px chamfers on the top-left and bottom-right corners, a 1 px --line-strong border, 12 px
 * --accent corner brackets, an optional tick ruler along the top edge and an optional index
 * label ("01 · WORLD"). `glow` adds --glow-accent to the frame lines.
 *
 * Inside a <Materialise> the border layer draws and the content fills (src/shared/motion/);
 * on its own it is static. The surface is a flex column, so a child with `height: 100%` or
 * `flex: 1` fills the frame.
 */
export default function HudFrame({ as: Tag = 'div', className = '', index, title, ruler = false, glow = false, children, ...rest }) {
  const layers = useMaterialiseLayers();
  const label = frameLabel(index, title);
  const Chrome = layers ? motion.span : 'span';
  const Layer = layers ? motion.div : 'div';
  const chromeProps = layers ? { variants: layers.border } : {};
  const layerProps = layers ? { variants: layers.content } : {};
  return <Tag className={`hudframe ${className}`.trim()} data-glow={glow ? 'true' : undefined} data-ruler={ruler ? 'true' : undefined} {...rest}>
    <div className="hudframe__surface">
      {label && <Layer className="hudframe__index" {...layerProps}>{label}</Layer>}
      <Layer className="hudframe__body" {...layerProps}>{children}</Layer>
    </div>
    <span className="hudframe__chrome" aria-hidden="true">
      <Chrome className="hudframe__draw" {...chromeProps}>
        <span className="hudframe__border" />
        {ruler && <span className="hudframe__ruler" />}
        <span className="hudframe__bracket hudframe__bracket--tl" />
        <span className="hudframe__bracket hudframe__bracket--tr" />
        <span className="hudframe__bracket hudframe__bracket--bl" />
        <span className="hudframe__bracket hudframe__bracket--br" />
      </Chrome>
    </span>
  </Tag>;
}
