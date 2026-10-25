import React from 'react';

const TONES = new Set(['ok', 'warn', 'danger', 'accent', 'idle']);

/** Compact mono status chip with a leading dot. tone: ok | warn | danger | accent | idle. */
export default function StatusChip({ tone = 'idle', className = '', children, ...rest }) {
  const safeTone = TONES.has(tone) ? tone : 'idle';
  const dot = safeTone === 'idle' ? 'status-dot' : `status-dot status-dot--${safeTone}`;
  return <span className={`status-chip ${className}`.trim()} data-tone={safeTone} {...rest}>
    <span className={dot} aria-hidden="true" />
    {children}
  </span>;
}
