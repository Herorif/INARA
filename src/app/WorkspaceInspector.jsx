import React from 'react';
import { X } from 'lucide-react';
import useStore from '../store';
import PresenceRing, { presenceLabel } from './PresenceRing';
import { voiceChip, voicePresence } from '../features/voice/status.js';
import HudLabel from '../shared/ui/HudLabel';
import Kbd from '../shared/ui/Kbd';
import EmptyState from '../shared/ui/EmptyState';

const sameDay = (left, right) => left.getFullYear() === right.getFullYear() && left.getMonth() === right.getMonth() && left.getDate() === right.getDate();
const clock = date => date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });

export default function WorkspaceInspector({ connected, processing, voice, gaming, resource, memory, onOpen, onClose }) {
  const reminders = useStore(state => state.reminders);
  const now = new Date();
  const today = reminders
    .filter(item => (item.status === 'pending' || item.status === 'snoozed') && Number.isFinite(item.trigger_at) && sameDay(new Date(item.trigger_at * 1000), now))
    .sort((left, right) => left.trigger_at - right.trigger_at);
  const presence = voicePresence({ connected, processing, voice });
  return <aside id="workspace-inspector" className="workspace-inspector" aria-label="Workspace context">
    <div className="inspector-heading"><HudLabel>CONTEXT</HudLabel><button type="button" className="btn btn--ghost btn--icon btn--sm" aria-label="Close context inspector" onClick={onClose}><X size={14} aria-hidden="true"/></button></div>
    <section className="inspector-panel inspector-presence hud-panel hud-frame" aria-label="Assistant presence">
      <PresenceRing size={64} state={presence} level={voice?.level ?? 0} lowPower={gaming}/>
      <div className="inspector-presence__copy"><strong className="presence-status hud-label" data-presence={presence}>{presenceLabel(presence)}</strong><span className="inspector-presence__hint"><Kbd>Ctrl Shift Space</Kbd> to&nbsp;talk</span></div>
    </section>
    <section className="inspector-panel hud-panel" aria-labelledby="inspector-system">
      <HudLabel as="h2" id="inspector-system" className="inspector-panel__title">SYSTEM</HudLabel>
      <dl className="system-details">
        <div><dt>Resource mode</dt><dd>{gaming ? 'Gaming' : resource.state === 'studio' ? 'Studio' : 'Lightweight'}</dd></div>
        <div><dt>Voice</dt><dd>{{ OFF: 'Off', READY: 'Ready', LISTENING: 'Listening', SPEAKING: 'Speaking' }[voiceChip({ connected, gaming, voice })]}</dd></div>
        <div><dt>Workspace memory</dt><dd className="tnum">{memory === null ? 'Not measured' : `${Math.round(memory)} MB`}</dd></div>
      </dl>
    </section>
    <section className="inspector-panel hud-panel" aria-labelledby="inspector-today">
      <HudLabel as="h2" id="inspector-today" className="inspector-panel__title">TODAY</HudLabel>
      {today.length ? <ul className="today-list">{today.slice(0, 5).map(item => <li key={item.id}><time className="today-list__time" dateTime={new Date(item.trigger_at * 1000).toISOString()}>{clock(new Date(item.trigger_at * 1000))}</time><span>{item.task}</span></li>)}</ul>
        : <EmptyState className="today-empty" title="No reminders today"/>}
      <button type="button" className="btn btn--ghost btn--sm today-open" onClick={() => onOpen('reminder')}>Open reminders</button>
    </section>
  </aside>;
}
