import React from 'react';

/**
 * The on/off switch used across Preferences. The button keeps the panel's 32 px minimum
 * click height (`.tool-panel button`); the 36 x 20 px track is drawn inside it, so the
 * switch reads as a pill rather than stretching to the button's height.
 */
const Switch = ({ checked, label, onClick }) =>
<button type="button" role="switch" aria-checked={checked} aria-label={label} onClick={onClick}
className="relative inline-flex h-8 w-9 shrink-0 items-center rounded-full">
    <span aria-hidden="true" className={`relative block h-5 w-9 rounded-full border transition-colors duration-150 ${checked ? 'border-transparent bg-accent' : 'border-line-strong bg-panel'}`}>
        <span className={`absolute left-0.5 top-0.5 h-3.5 w-3.5 rounded-full transition-transform duration-150 ${checked ? 'translate-x-4 bg-[var(--text-on-accent)]' : 'translate-x-0 bg-ink-2'}`} />
    </span>
</button>;

export default Switch;
