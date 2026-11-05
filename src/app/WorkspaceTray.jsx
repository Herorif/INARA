import React from 'react';
import { Activity, ArrowUpRight, ChevronUp, Box, Image, ShieldCheck } from 'lucide-react';
import useStore from '../store';
import { pendingJob } from '../features/creative/client';
import HudLabel from '../shared/ui/HudLabel';

export default function WorkspaceTray({ expanded, onToggle, onOpen, gaming }) {
  const activity = useStore(state => state.activity), project = useStore(state => state.currentProject);
  const approvals = useStore(state => state.confirmationQueue.length), processing = useStore(state => state.textProcessing);
  const entries = activity.filter(item => item.project === project), active = entries.filter(pendingJob).length;
  const status = approvals ? (approvals > 1 ? `${approvals} approvals waiting` : 'Waiting for your approval') : active ? `${active} creative ${active === 1 ? 'job' : 'jobs'} in progress` : processing ? 'JARVIS is working' : 'No creative jobs running';
  return <footer className={`workspace-tray ${expanded ? 'is-expanded' : ''}`}>
    {expanded && <div id="workspace-activity-tray" className="tray-content"><div className="section-heading"><HudLabel>RECENT CREATIVE WORK</HudLabel><button type="button" className="btn btn--ghost btn--sm" onClick={() => onOpen('activity')}>All artifacts</button></div>{entries.length ? <div className="tray-items">{entries.slice(0,4).map(item => {const Icon = item.kind === 'cad' ? Box : Image; return <button type="button" key={item.key} disabled={gaming} onClick={() => onOpen(item.kind, undefined, item.request_id)}><Icon size={16} aria-hidden="true"/><span><strong>{item.name}</strong><small>{item.state.replaceAll('_',' ')}</small></span><ArrowUpRight size={14} aria-hidden="true"/></button>;})}</div> : <p className="tray-empty">3D builds and image revisions appear here. <button type="button" className="text-button" onClick={() => onOpen('activity')}>Open saved history</button></p>}</div>}
    <div className="tray-bar"><button type="button" className="tray-toggle" aria-label="Toggle activity tray" aria-expanded={expanded} aria-controls="workspace-activity-tray" onClick={onToggle}><Activity size={14} aria-hidden="true"/><span>Activity</span><span className={`tray-status ${approvals ? 'needs-attention' : ''}`}>{!!approvals && <ShieldCheck size={12} aria-hidden="true"/>}{status}</span><ChevronUp size={14} aria-hidden="true"/></button></div>
  </footer>;
}
