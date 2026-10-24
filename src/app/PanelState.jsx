import React from 'react';
import { AlertTriangle, Loader2, Radio, RefreshCw } from 'lucide-react';
import './panel.css';

/** Shared, honest progress and recovery surface for lazy workspace panels. */
export default function PanelState({ kind = 'empty', title, detail, compact = false, action, actionLabel = 'Try again' }) {
  const Icon = kind === 'loading' ? Loader2 : kind === 'error' ? AlertTriangle : Radio;
  return <div className={`panel-state panel-state--${kind} ${compact ? 'panel-state--compact' : ''}`}
    role={kind === 'error' ? 'alert' : 'status'} aria-busy={kind === 'loading'}>
    <div className="panel-state-signal" aria-hidden="true"><Icon size={compact ? 19 : 26} /></div>
    <div className="panel-state-copy"><span className="eyebrow">INARA / {kind === 'loading' ? 'PREPARING' : kind === 'offline' ? 'CONNECTION' : kind === 'error' ? 'RECOVERY' : 'WORKSPACE'}</span>
      <strong>{title}</strong>{detail && <p>{detail}</p>}</div>
    {action && <button type="button" className="panel-state-action" onClick={action}><RefreshCw size={14} />{actionLabel}</button>}
  </div>;
}
