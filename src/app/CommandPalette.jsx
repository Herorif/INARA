import React, { useEffect, useRef, useState } from 'react';
import { Search, ArrowUpRight, X } from 'lucide-react';
import { searchCommands } from './features';
import { useDialogFocus } from './useDialogFocus';
import './workspace-tools.css';
export default function CommandPalette({ onClose, onSelect, gaming }) {
  const ref = useRef(null), [query, setQuery] = useState(''), [index, setIndex] = useState(0);
  useDialogFocus(ref, onClose);
  const results = searchCommands(query, gaming), active = Math.min(index, Math.max(0, results.length - 1));
  useEffect(() => { ref.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' }); }, [active, query]);
  const choose = item => { if (item && !item.disabled) { onClose(); onSelect(item.id); } };
  return <div className="dialog-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="command-palette" ref={ref} role="dialog" aria-modal="true" aria-label="Command palette" tabIndex={-1}>
      <div className="palette-search"><Search size={20} /><input data-dialog-autofocus role="combobox" aria-label="Search commands" aria-expanded="true" aria-controls="command-results" aria-activedescendant={results.length ? `command-${results[active].id}` : undefined}
        value={query} placeholder="Find a tool or workspace…" onChange={event => { setQuery(event.target.value); setIndex(0); }} onKeyDown={event => {
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); setIndex((active + (event.key === 'ArrowDown' ? 1 : -1) + results.length) % (results.length || 1)); }
          if (event.key === 'Enter') { event.preventDefault(); choose(results[active]); }
        }} /><button className="icon-button" aria-label="Close commands" onClick={onClose}><X size={18} /></button></div>
      <div className="palette-caption eyebrow">OPEN A WORKSPACE / NO ACTION RUNS UNTIL YOU CHOOSE</div>
      <div className="palette-results" id="command-results" role="listbox" aria-label="Available commands">
        {results.length ? results.map((item, position) => <button type="button" role="option" aria-selected={position === active} aria-disabled={item.disabled} id={`command-${item.id}`} key={item.id} onMouseEnter={() => setIndex(position)} onClick={() => choose(item)}>
          <span><strong>{item.title}</strong><small>{item.disabled ? 'Paused in gaming mode' : item.group}</small></span><ArrowUpRight size={17} /></button>) : <p>No matching tools. Try “3D”, “reminders” or “settings”.</p>}
      </div><footer>↑ ↓ to browse <span>ENTER to open / ESC to close</span></footer>
    </section></div>;
}
