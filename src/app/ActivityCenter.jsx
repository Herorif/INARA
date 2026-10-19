import React, { useEffect, useRef, useState } from 'react';
import { Box, Image, ArrowUpRight, RefreshCw, Download } from 'lucide-react';
import socket from '../services/socket';
import useStore from '../store';
import { createCadClient } from '../transport/cadClient.ts';
import { createImageClient } from '../transport/imageClient.ts';
import { artifactBytes, pendingJob } from '../features/creative/client';
import PanelState from './PanelState';
import './workspace-tools.css';
export default function ActivityCenter({ onOpen, gaming }) {
  const project = useStore(state => state.currentProject), connected = useStore(state => state.backendConnected);
  const activity = useStore(state => state.activity);
  const [filter, setFilter] = useState('all'), [loading, setLoading] = useState(true), [errors, setErrors] = useState([]), [exporting, setExporting] = useState('');
  const clients = useRef(null), generation = useRef(0);
  const refresh = async () => {
    const version = ++generation.current, startedAt = Date.now() / 1000;
    setLoading(true); setErrors([]);
    const results = await Promise.allSettled(['cad', 'image'].map(async kind => {
      const response = await clients.current[kind].call(`${kind}_list`, {});
      if (version !== generation.current) return;
      // Old snapshot entries merge beneath already observed terminal state.
      useStore.getState().restoreActivity(kind, response.jobs, startedAt);
    }));
    if (version !== generation.current) return;
    setErrors(results.filter(value => value.status === 'rejected').map(value => value.reason.message));
    setLoading(false);
  };
  useEffect(() => {
    const cad = createCadClient(socket), image = createImageClient(socket);
    clients.current = { cad, image };
    cad.on('connect', refresh);
    cad.on('disconnect', () => { generation.current++; setLoading(false); setExporting(''); });
    if (socket.connected) refresh(); else setLoading(false);
    return () => { generation.current++; cad.dispose(); image.dispose(); };
  }, [project]);
  const download = async item => {
    const version = generation.current, format = item.kind === 'image' ? 'png' : 'glb';
    setExporting(item.key); setErrors([]);
    try {
      const { artifact } = await clients.current[item.kind].call(`${item.kind}_artifact`, { request_id: item.request_id, format });
      const bytes = await artifactBytes(artifact);
      if (version !== generation.current) return;
      const url = URL.createObjectURL(new Blob([bytes], { type: format === 'png' ? 'image/png' : 'model/gltf-binary' }));
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = artifact.filename; anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { if (version === generation.current) setErrors([error.message]); }
    finally { if (version === generation.current) setExporting(''); }
  };
  const entries = activity.filter(item => item.project === project && (filter === 'all' || item.kind === filter));
  return <section className="activity-center" aria-labelledby="activity-title">
    <div className="page-intro"><span className="eyebrow">YOUR IDEAS / IN MOTION</span><h1 id="activity-title">Work, collected<span className="heading-dot">.</span></h1><p>3D builds, images and saved exports in {project}. Workers start only when you ask.</p></div>
    <div className="activity-toolbar"><div role="group" aria-label="Filter activity">{[['all', 'All work'], ['cad', '3D builds'], ['image', 'Images']].map(([key, label]) => <button key={key} aria-pressed={filter === key} onClick={() => setFilter(key)}>{label}</button>)}</div><button disabled={!connected || loading} onClick={refresh}><RefreshCw size={15} />Refresh history</button></div>
    {!connected ? <PanelState compact kind="offline" title="Core offline" detail="Showing revisions observed in this workspace. Reconnect to refresh saved history." /> : loading ? <PanelState compact kind="loading" title="Collecting your revisions" detail="Reading saved history. No model is loading." /> : null}
    {errors.length > 0 && <PanelState compact kind="error" title="Some history could not be loaded" detail={errors.join(' ')} action={connected && !loading ? refresh : undefined} actionLabel="Retry history" />}
    {entries.length ? <div className="activity-grid">{entries.map(item => { const Icon = item.kind === 'cad' ? Box : Image; return <article key={item.key} className={`activity-card ${pendingJob(item) ? 'activity-working' : ''}`}>
      <div className="activity-card-top"><span className="activity-icon"><Icon size={23} /></span><span className={`activity-state state-${item.state}`}>{item.state}</span></div>
      <span className="eyebrow">{item.kind === 'cad' ? '3D STUDIO' : 'IMAGE ATELIER'} / {item.request_id.slice(0, 8)}</span><h2>{item.name}</h2>
      <p>{item.error || (item.state === 'succeeded' ? 'Saved revision. Ready to explore or export.' : item.phase?.replaceAll('_', ' ') || 'Waiting for an update.')}</p>
      <div className="activity-formats">{pendingJob(item) && <span>{item.background ? 'BACKGROUND / WORKSPACE LIFETIME' : 'PANEL LIFETIME'}</span>}{item.artifacts.map(format => <span key={format}>{format.toUpperCase()}</span>)}</div>
      <footer><button disabled={gaming || loading} title={gaming ? 'Paused in gaming mode' : undefined} onClick={() => onOpen(item.kind, item.request_id)}>Open revision<ArrowUpRight size={15} /></button>{item.state === 'succeeded' && item.artifacts.includes(item.kind === 'image' ? 'png' : 'glb') && <button aria-label={`Download ${item.name}`} disabled={!connected || !!exporting} onClick={() => download(item)}><Download size={15} />{exporting === item.key ? 'Preparing…' : 'Export'}</button>}</footer>
    </article>; })}</div> : !loading && <PanelState title="A space for your next idea" detail="Your saved 3D builds and image revisions will appear here. Open Studio when you are ready." />}
  </section>;
}
