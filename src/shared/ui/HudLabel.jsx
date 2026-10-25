import React from 'react';

/** Mono uppercase label (same styling as the legacy `.eyebrow`). */
export default function HudLabel({ as: Tag = 'span', className = '', children, ...rest }) {
  return <Tag className={`hud-label ${className}`.trim()} {...rest}>{children}</Tag>;
}
