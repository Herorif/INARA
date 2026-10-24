import React from 'react';
import { ArrowUpRight, Bell, BookOpen, Gauge, ListChecks, ShieldCheck, X, Zap } from 'lucide-react';
import useStore from '../store';
import CoreOrb from './CoreOrb';

export default function WorkspaceInspector({ connected, processing, gaming, resource, memory, visible, onOpen, onClose }) {
  const reminders = useStore(state => state.reminders);
  const voice = useStore(state => state.aiConnected);
  const pending = reminders.filter(item => item.status === 'pending' || item.status === 'snoozed');
  return <aside id="workspace-inspector" className="workspace-inspector" aria-label="Workspace context">
    <div className="inspector-heading"><span className="eyebrow">CONTEXT</span><button className="icon-button" aria-label="Close context inspector" onClick={onClose}><X size={15}/></button></div>
    <section className="system-card"><CoreOrb active={processing || voice} quiet={gaming || !visible || !(processing || voice)}/><div className="pulse-status"><span className={`status-dot ${connected ? '' : 'offline'}`}/><strong>{connected ? 'At your service' : 'Waiting for connection'}</strong></div>
      <dl className="system-details"><div><dt>Resource mode</dt><dd>{gaming ? 'Gaming' : resource.state === 'studio' ? 'Studio' : 'Lightweight'}</dd></div><div><dt>Voice session</dt><dd>{voice ? 'Active' : 'Off'}</dd></div><div><dt>Workspace memory</dt><dd>{memory === null ? 'Not measured' : `${Math.round(memory)} MB`}</dd></div></dl><button className="text-button" onClick={() => onOpen('capabilities')}><Zap size={13}/> Capability center / diagnostics <ArrowUpRight size={13}/></button>
    </section>
    <section className="reminders-card"><div className="section-heading"><span className="eyebrow">ON YOUR RADAR</span><Bell size={15}/></div><h2>{pending.length ? `${pending.length} upcoming` : 'A clear horizon'}<span className="heading-dot">.</span></h2>
      {pending.length ? pending.slice(0,3).map(item => <div className="radar-reminder" key={item.id}><span className="radar-dot"/><div><strong>{item.task}</strong><span>{new Date(item.trigger_at*1000).toLocaleString([], { month:'short',day:'numeric',hour:'2-digit',minute:'2-digit' })}</span></div></div>) : <p>Nothing scheduled. A little more space for your next idea.</p>}<button className="text-button" onClick={() => onOpen('reminder')}>Open reminders <ArrowUpRight size={14}/></button>
    </section>
    <div className="quick-launch"><span className="eyebrow">PROJECT TOOLS</span><button onClick={() => onOpen('memory')}><BookOpen size={15}/> Project memory <ArrowUpRight size={13}/></button><button onClick={() => onOpen('usage')}><Gauge size={15}/> Usage & quality <ArrowUpRight size={13}/></button><button onClick={() => onOpen('tasks')}><ListChecks size={15}/> Reviewed tasks <ArrowUpRight size={13}/></button></div><div className="inspector-footer"><ShieldCheck size={13}/><span>Your project. Your permission.</span></div>
  </aside>;
}
