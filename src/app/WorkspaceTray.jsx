import React from 'react';
import { Activity, ArrowUpRight, ChevronUp, Box, Image, ShieldCheck } from 'lucide-react';
import useStore from '../store';
import { pendingJob } from '../features/creative/client';

export default function WorkspaceTray({ expanded, onToggle, onOpen, gaming }) {
  const activity = useStore(state => state.activity), project = useStore(state => state.currentProject);
  const connected = useStore(state => state.backendConnected), approval = useStore(state => state.confirmationRequest), processing = useStore(state => state.textProcessing);
  const entries = activity.filter(item => item.project === project), active = entries.filter(pendingJob).length;
  const status = approval ? 'Waiting for your approval' : active ? `${active} creative ${active === 1 ? 'job' : 'jobs'} in progress` : processing ? 'INARA is thinking' : 'No creative jobs running';
  return <footer className={`workspace-tray ${expanded ? 'is-expanded' : ''}`}>
    {expanded && <div id="workspace-activity-tray" className="tray-content"><div className="section-heading"><span className="eyebrow">RECENT CREATIVE WORK</span><button className="text-button" onClick={() => onOpen('activity')}>All artifacts <ArrowUpRight size={14}/></button></div>{entries.length ? <div className="tray-items">{entries.slice(0,4).map(item => {const Icon = item.kind === 'cad' ? Box : Image; return <button key={item.key} disabled={gaming} onClick={() => onOpen(item.kind, undefined, item.request_id)}><Icon size={17}/><span><strong>{item.name}</strong><small>{item.state.replaceAll('_',' ')}</small></span><ArrowUpRight size={14}/></button>;})}</div> : <p className="tray-empty">Your 3D builds and image revisions will appear here. <button className="text-button" onClick={() => onOpen('activity')}>Open saved history <ArrowUpRight size={13}/></button></p>}</div>}
    <div className="tray-bar"><button className="tray-toggle" aria-label="Toggle activity tray" aria-expanded={expanded} aria-controls="workspace-activity-tray" onClick={onToggle}><Activity size={15}/><span>Activity</span><span className={`tray-status ${approval ? 'needs-attention' : ''}`}>{approval && <ShieldCheck size={12}/>} {status}</span><ChevronUp size={14}/></button><span className="tray-connection"><span className={`status-dot ${connected ? '' : 'offline'}`}/>{connected ? 'CORE CONNECTED' : 'CORE OFFLINE'}</span></div>
  </footer>;
}
