import React, { useEffect, useRef, useState } from 'react';
import { Cpu, RefreshCw, ShieldCheck, Layers3 } from 'lucide-react';
import socket from '../services/socket';
import useStore from '../store';
import { createCapabilityClient } from '../transport/capabilityClient.ts';
import PanelState from './PanelState';
import './capabilities.css';
const amount = (value, unit = '') => value == null ? 'Unknown' : `${value.toLocaleString()}${unit}`;
export default function CapabilityCenter() {
  const connected = useStore(state => state.backendConnected);
  const project = useStore(state => state.currentProject);
  const [report, setReport] = useState(null), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const refresh = useRef(() => {});
  useEffect(() => {
    const client = createCapabilityClient(socket);
    let live = true, version = 0;
    setReport(null);
    refresh.current = async () => {
      const current = ++version;
      setBusy(true); setError('');
      try { const value = await client.inspect(); if (live && current === version) setReport(value); }
      catch (failure) { if (live && current === version) setError(failure.message); }
      finally { if (live && current === version) setBusy(false); }
    };
    client.on('connect', refresh.current);
    client.on('disconnect', () => { version++; setBusy(false); setReport(null); });
    if (socket.connected) refresh.current();
    return () => { live = false; client.dispose(); };
  }, [project]);
  return <div className="capability-center tool-panel">
    <header className="capability-intro"><div><span className="eyebrow">SYSTEM / READINESS</span><h2>Your core, in focus.</h2><p>Know what is available before you create.</p></div><button className="text-button" disabled={!connected || busy} onClick={() => refresh.current()}><RefreshCw size={16} className={busy ? 'panel-progress-spinner' : ''} />{busy ? 'Checking' : 'Refresh diagnostics'}</button></header>
    {error && <PanelState kind="error" title="Diagnostics unavailable" detail={error} />}
    {!connected && <PanelState kind="offline" title="Core offline" detail="Reconnect to inspect capabilities." />}
    {report && <>
      <div className="capability-telemetry" aria-label="Resource diagnostics">
        <div><Cpu size={18} /><span>CPU threads</span><strong>{amount(report.hardware.cpu_count)}</strong></div>
        <div><Layers3 size={18} /><span>Available RAM</span><strong>{amount(report.hardware.ram_available_mb, ' MB')}</strong></div>
        <div><ShieldCheck size={18} /><span>GPU memory</span><strong>{amount(report.hardware.vram_mb, ' MB')}</strong></div>
        <div><span className="status-dot" /><span>{report.resources.state.toUpperCase()} / QUEUE</span><strong>{report.resources.running} running / {report.resources.waiting} waiting</strong></div>
      </div>
      <p className="capability-note">Fixed CPU budget: {report.resources.budget.cpu} threads / {report.resources.budget.ram_mb} MB RAM / {report.resources.budget.vram_mb} MB VRAM. One worker, three waiting. Estimates guide admission; they are not hard memory limits. Hardware counters refresh at most every 10 seconds, on demand.</p>
      <div className="capability-grid">{report.capabilities.map(card => <article key={card.id} className={`capability-card ${card.status}`}>
        <div className="capability-card-heading"><h3>{card.title}</h3><span className="capability-badge">{card.status.replaceAll('_', ' ')}</span></div>
        <div className="capability-evidence"><span>Adapter <b>{card.installed ? 'Detected' : 'Missing'}</b></span><span>Configuration <b>{card.configured ? 'Present' : 'Missing'}</b></span><span>Integration <b>{card.verified ? 'Saved successful job' : 'Unverified'}</b></span></div>
        <p>{card.blocked || card.reason}</p>{card.blocked && <small>{card.reason}</small>}
        {card.model && <small className="capability-model">Model / {card.model}</small>}
        {card.profile && <small>Estimate / {card.profile.cpu} CPU / {card.profile.ram_mb} MB RAM / {card.profile.vram_mb} MB VRAM</small>}
        <footer>{card.last_duration_seconds == null ? 'Performance: unmeasured' : `Last saved job: ${card.last_duration_seconds}s including queue wait`}</footer>
      </article>)}</div>
      <p className="capability-note">Verified results refer to recent jobs in this project, not a hardware benchmark. GPU information stays unknown until supported detection is added. No adapters, devices or models are started by this panel. Setup remains manual; Android pairing and WhatsApp replies remain deferred.</p>
      <small>Snapshot / {new Date(report.checked_at * 1000).toLocaleTimeString()} / Refresh to see changed jobs or resource mode.</small>
    </>}
  </div>;
}
