import React from 'react';
import { segmentItems } from './segmentedControlModel';

/**
 * A radio-segmented choice for Preferences: visually hidden radio inputs, each with a styled
 * span, so arrow keys move the choice as in any radio group. Pass `aria-label` or
 * `aria-labelledby`; `onChange(id)` runs when an option is checked.
 */
export default function SegmentedControl({ name, options, value, onChange, 'aria-label': ariaLabel, 'aria-labelledby': ariaLabelledBy }) {
  return <div role="radiogroup" aria-label={ariaLabel} aria-labelledby={ariaLabelledBy} className="inline-flex shrink-0 rounded-md border border-line-strong bg-panel p-0.5">
    {segmentItems(options, value).map((entry) =>
      <label key={entry.id} className="relative cursor-pointer">
        <input type="radio" className="peer sr-only" name={name} value={entry.id}
          checked={entry.checked} onChange={() => onChange(entry.id)} />
        <span className="flex min-h-[1.75rem] items-center rounded px-2.5 text-[0.6875rem] text-ink-2 transition-colors hover:text-ink-1 peer-checked:bg-[var(--accent-subtle)] peer-checked:text-accent peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-1 peer-focus-visible:outline-[color:var(--accent)] [@media(pointer:coarse)]:min-h-[2.75rem]">
          {entry.label}
        </span>
      </label>
    )}
  </div>;
}
