import React from 'react';

/** Segmented single choice (same look as the Preferences brain and permission controls). */
export function Segmented({ label, labelledBy, name, options, value, disabled, onChange }) {
  return <div role="radiogroup" aria-label={labelledBy ? undefined : label} aria-labelledby={labelledBy} className="inline-flex shrink-0 flex-wrap rounded-md border border-line-strong bg-panel p-0.5">
    {options.map(entry =>
      <label key={entry.id} className="relative cursor-pointer">
        <input type="radio" className="peer sr-only" name={name} value={entry.id} disabled={disabled}
          checked={value === entry.id} onChange={() => onChange(entry.id)} />
        <span className="flex min-h-[1.75rem] items-center rounded px-2.5 text-[0.75rem] text-ink-2 transition-colors hover:text-ink-1 peer-checked:bg-[var(--accent-subtle)] peer-checked:text-accent peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-1 peer-focus-visible:outline-[color:var(--accent)] [@media(pointer:coarse)]:min-h-[2.75rem]">
          {entry.label}
        </span>
      </label>
    )}
  </div>;
}

/** On/off switch (same look as the Preferences switches). */
export function Switch({ checked, label, disabled, onClick, describedBy }) {
  return <button type="button" role="switch" aria-checked={checked} aria-label={label} aria-describedby={describedBy} disabled={disabled} onClick={onClick}
    className={`relative h-5 w-9 shrink-0 rounded-full border transition-colors duration-150 ${checked ? 'border-transparent bg-accent' : 'border-line-strong bg-panel'}`}>
    <span aria-hidden="true" className={`absolute left-0.5 top-0.5 h-3.5 w-3.5 rounded-full transition-transform duration-150 ${checked ? 'translate-x-4 bg-[var(--text-on-accent)]' : 'translate-x-0 bg-ink-2'}`} />
  </button>;
}
