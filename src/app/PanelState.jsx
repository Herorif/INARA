import React from 'react';
import { AlertTriangle, Loader2, Radio, RefreshCw } from 'lucide-react';
import StatusChip from '../shared/ui/StatusChip';
import './panel.css';
import './panel-parts.css';

const chips = {
  loading: ['accent', 'Loading'],
  offline: ['warn', 'Offline'],
  error: ['danger', 'Error'],
};

/** Shared, honest progress and recovery surface for lazy workspace panels. */
export default function PanelState({ kind = 'empty', title, detail, compact = false, action, actionLabel = 'Try again' }) {
  const Icon = kind === 'loading' ? Loader2 : kind === 'error' ? AlertTriangle : Radio;
  const chip = chips[kind];
  return <div className={`panel-state panel-state--${kind} ${compact ? 'panel-state--compact' : ''}`}
    role={kind === 'error' ? 'alert' : 'status'} aria-busy={kind === 'loading'}>
    <div className="panel-state-signal" aria-hidden="true"><Icon size={compact ? 18 : 24} /></div>
    <div className="panel-state-copy">
      {chip && <StatusChip className="panel-state-chip" tone={chip[0]}>{chip[1]}</StatusChip>}
      <strong>{title}</strong>{detail && <p>{detail}</p>}
    </div>
    {action && <button type="button" className="panel-state-action" onClick={action}><RefreshCw size={14} aria-hidden="true" />{actionLabel}</button>}
  </div>;
}
