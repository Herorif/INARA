import React, { useEffect, useRef, useState } from 'react';
import { Activity, AudioLines, Bell, BookOpen, Box, Cable, Camera, Cpu, Gauge, Globe2, Image, Inbox, ListChecks, Monitor, PhoneCall, Printer, Repeat, Search, Settings2, Smartphone, Wrench, X, Zap } from 'lucide-react';
import { searchCommands } from './features';
import { useDialogFocus } from './useDialogFocus';
import HudLabel from '../shared/ui/HudLabel';
import Kbd from '../shared/ui/Kbd';
import './workspace-tools.css';

const icons = {
  calls: PhoneCall, inbox: Inbox, connections: Cable, tasks: ListChecks, usage: Gauge, memory: BookOpen,
  quick: AudioLines, capabilities: Wrench, activity: Activity, cad: Box, image: Image, camera: Camera,
  browser: Globe2, reminder: Bell, routines: Repeat, desktop: Monitor, kasa: Zap, device: Cpu,
  printer: Printer, phone: Smartphone, settings: Settings2,
};

export default function CommandPalette({ onClose, onSelect, gaming }) {
  const ref = useRef(null), [query, setQuery] = useState(''), [index, setIndex] = useState(0);
  useDialogFocus(ref, onClose);
  const results = searchCommands(query, gaming), active = Math.min(index, Math.max(0, results.length - 1));
  useEffect(() => { ref.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' }); }, [active, query]);
  const choose = item => { if (item && !item.disabled) { onClose(); onSelect(item.id); } };
  return <div className="dialog-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="command-palette" ref={ref} role="dialog" aria-modal="true" aria-label="Command palette" tabIndex={-1}>
      <div className="palette-search"><Search size={16} aria-hidden="true" /><input data-dialog-autofocus role="combobox" aria-label="Search commands" aria-expanded="true" aria-controls="command-results" aria-activedescendant={results.length ? `command-${results[active].id}` : undefined}
        value={query} placeholder="Find a tool or action" onChange={event => { setQuery(event.target.value); setIndex(0); }} onKeyDown={event => {
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); setIndex((active + (event.key === 'ArrowDown' ? 1 : -1) + results.length) % (results.length || 1)); }
          if (event.key === 'Enter') { event.preventDefault(); choose(results[active]); }
        }} /><button type="button" className="btn btn--ghost btn--icon" aria-label="Close commands" onClick={onClose}><X size={16} aria-hidden="true" /></button></div>
      <HudLabel className="palette-caption">NOTHING RUNS UNTIL YOU CHOOSE</HudLabel>
      <div className="palette-results" id="command-results" role="listbox" aria-label="Available commands">
        {results.length ? results.map((item, position) => { const Icon = icons[item.id] || Search; return <button type="button" role="option" aria-selected={position === active} aria-disabled={item.disabled} id={`command-${item.id}`} key={item.id} onMouseEnter={() => setIndex(position)} onClick={() => choose(item)}>
          <Icon size={16} aria-hidden="true" /><strong className="palette-result__title">{item.title}</strong><HudLabel className="palette-result__group">{item.disabled ? 'PAUSED IN GAMING MODE' : item.group}</HudLabel></button>; }) : <p>No matching tools. Try “3D”, “reminders” or “settings”.</p>}
      </div><footer><span><Kbd>↑</Kbd><Kbd>↓</Kbd> to browse</span><span><Kbd>Enter</Kbd> to open <Kbd>Esc</Kbd> to close</span></footer>
    </section></div>;
}
