import React from 'react';
import { Box, Image, RefreshCw } from 'lucide-react';
export default function RevisionHistory({ kind, project, jobs, selected, busy, connected, refreshing, uncertain, onRefresh, onSelect }) {
  const Icon = kind === 'cad' ? Box : Image;
  return <section className={`${kind}-history`}><div className={`${kind}-history-heading ${kind}-section-title`}><span className="eyebrow">RECENT REVISIONS / {project}</span><button className="text-button" aria-label={`Refresh ${kind === 'cad' ? 'build' : 'image'} history`} disabled={!connected || refreshing || (busy && !uncertain)} onClick={onRefresh}><RefreshCw size={14} /></button></div>
    <div className={`${kind}-history-list`}>{jobs.length ? jobs.map(value => <button key={value.request_id} disabled={busy} className={value.request_id === selected ? 'selected' : ''} onClick={() => onSelect(value)}><Icon size={20} /><span>{value.recipe?.name || 'New revision'}<small>{kind === 'image' ? `${value.recipe?.width} × ${value.recipe?.height}` : value.recipe?.shape} / {value.request_id.slice(0, 8)}</small></span><em>{value.state}</em></button>) : <p>Your saved revisions will appear here. Nothing has been created yet.</p>}</div>
  </section>;
}
