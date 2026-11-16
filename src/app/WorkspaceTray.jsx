import React, { useRef, useState } from 'react';
import { Activity, ArrowUpRight, ChevronUp, Box, Image, ShieldCheck } from 'lucide-react';
import useStore from '../store';
import { pendingJob } from '../features/creative/client';
import HudLabel from '../shared/ui/HudLabel';
import WhatJarvisDid from '../features/activity/WhatJarvisDid';
import ToldYou from '../features/proactive/ToldYou';

const TABS = [{ id: 'jobs', label: 'Jobs' }, { id: 'turns', label: 'What JARVIS did' }, { id: 'told', label: 'Told you' }];

function TrayTabs({ tab, onChange }) {
  const refs = useRef({});
  const key = event => {
    const index = TABS.findIndex(item => item.id === tab);
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
    const next = event.key === 'Home' ? TABS[0] : event.key === 'End' ? TABS[TABS.length - 1] : step ? TABS[(index + step + TABS.length) % TABS.length] : null;
    if (!next) return;
    event.preventDefault();
    onChange(next.id);
    refs.current[next.id]?.focus();
  };
  return <div className="tray-tabs" role="tablist" aria-label="Activity">{TABS.map(item => <button key={item.id} ref={node => { refs.current[item.id] = node; }} type="button" role="tab" id={`tray-tab-${item.id}`} className="tray-tab" aria-selected={tab === item.id} aria-controls={`tray-panel-${item.id}`} tabIndex={tab === item.id ? 0 : -1} onClick={() => onChange(item.id)} onKeyDown={key}>{item.label}</button>)}</div>;
}

export default function WorkspaceTray({ expanded, onToggle, onOpen, gaming }) {
  const activity = useStore(state => state.activity), project = useStore(state => state.currentProject);
  const approvals = useStore(state => state.confirmationQueue.length), processing = useStore(state => state.textProcessing);
  const entries = activity.filter(item => item.project === project), active = entries.filter(pendingJob).length;
  const [tab, setTab] = useState('jobs');
  const status = approvals ? (approvals > 1 ? `${approvals} approvals waiting` : 'Waiting for your approval') : active ? `${active} creative ${active === 1 ? 'job' : 'jobs'} in progress` : processing ? 'JARVIS is working' : 'No creative jobs running';
  return <footer className={`workspace-tray ${expanded ? 'is-expanded' : ''}`}>
    {expanded && <div id="workspace-activity-tray" className="tray-content"><TrayTabs tab={tab} onChange={setTab}/>{tab === 'turns' ? <div role="tabpanel" id="tray-panel-turns" aria-labelledby="tray-tab-turns"><WhatJarvisDid/></div> : tab === 'told' ? <div role="tabpanel" id="tray-panel-told" aria-labelledby="tray-tab-told"><ToldYou/></div> : <div role="tabpanel" id="tray-panel-jobs" aria-labelledby="tray-tab-jobs"><div className="section-heading"><HudLabel>RECENT CREATIVE WORK</HudLabel><button type="button" className="btn btn--ghost btn--sm" onClick={() => onOpen('activity')}>All artifacts</button></div>{entries.length ? <div className="tray-items">{entries.slice(0,4).map(item => {const Icon = item.kind === 'cad' ? Box : Image; return <button type="button" key={item.key} disabled={gaming} onClick={() => onOpen(item.kind, undefined, item.request_id)}><Icon size={16} aria-hidden="true"/><span><strong>{item.name}</strong><small>{item.state.replaceAll('_',' ')}</small></span><ArrowUpRight size={14} aria-hidden="true"/></button>;})}</div> : <p className="tray-empty">3D builds and image revisions appear here. <button type="button" className="text-button" onClick={() => onOpen('activity')}>Open saved history</button></p>}</div>}</div>}
    <div className="tray-bar"><button type="button" className="tray-toggle" aria-label="Toggle activity tray" aria-expanded={expanded} aria-controls="workspace-activity-tray" onClick={onToggle}><Activity size={14} aria-hidden="true"/><span>Activity</span><span className={`tray-status ${approvals ? 'needs-attention' : ''}`}>{!!approvals && <ShieldCheck size={12} aria-hidden="true"/>}{status}</span><ChevronUp size={14} aria-hidden="true"/></button></div>
  </footer>;
}
