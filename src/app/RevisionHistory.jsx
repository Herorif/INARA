import React from 'react';
import { Box, Image, RefreshCw } from 'lucide-react';
import StatusChip from '../shared/ui/StatusChip';
import './panel-parts.css';

/** StatusChip tone for a creative job state. */
export function stateTone(state) {
  if (state === 'succeeded') return 'ok';
  if (state === 'failed') return 'danger';
  if (state === 'interrupted' || state === 'approval') return 'warn';
  if (['submitting', 'queued', 'running'].includes(state)) return 'accent';
  return 'idle';
}

export default function RevisionHistory({ kind, project, jobs, selected, busy, connected, refreshing, uncertain, onRefresh, onSelect }) {
  const Icon = kind === 'cad' ? Box : Image;
  return <section className={`revision-history ${kind}-history`} aria-label="Recent revisions">
    <div className={`revision-history__heading ${kind}-history-heading ${kind}-section-title`}>
      <span className="hud-label">Recent revisions / {project}</span>
      <button type="button" className="btn btn--ghost btn--sm btn--icon" aria-label={`Refresh ${kind === 'cad' ? 'build' : 'image'} history`} disabled={!connected || refreshing || (busy && !uncertain)} onClick={onRefresh}><RefreshCw size={14} aria-hidden="true" /></button>
    </div>
    <div className={`revision-history__list ${kind}-history-list`}>{jobs.length ? jobs.map(value => <button type="button" key={value.request_id} disabled={busy} aria-pressed={value.request_id === selected} className={value.request_id === selected ? 'selected' : ''} onClick={() => onSelect(value)}>
      <Icon size={18} aria-hidden="true" />
      <span className="revision-history__name">{value.recipe?.name || 'New revision'}<small>{kind === 'image' ? `${value.recipe?.width} × ${value.recipe?.height}` : value.recipe?.shape} / {value.request_id.slice(0, 8)}</small>{value.reference && <small>Reference / {value.reference.source_kind} / {value.reference.source_request_id.slice(0, 8)}</small>}</span>
      <em className="revision-history__state"><StatusChip tone={stateTone(value.state)}>{value.state}</StatusChip>{value.base_request_id && <small> from {value.base_request_id.slice(0, 8)}</small>}</em>
    </button>) : <p>No revisions yet. Saved revisions appear here.</p>}</div>
  </section>;
}
