import React from 'react';
import { Layers, X } from 'lucide-react';
import StatusChip from '../shared/ui/StatusChip';
import { features } from './features';
import './panel.css';

const groups = Object.fromEntries(features.map(feature => [feature.id, feature.group]));

/**
 * Panel title bar. `eyebrow` overrides the HUD label; otherwise it is the feature's group
 * when the caller passes `feature`, and omitted when nothing identifies the panel.
 * `status` renders a StatusChip (tone: ok | warn | danger | accent | idle).
 */
export default function PanelHeader({ title, onClose, closeLabel = 'Close panel', titleId = 'feature-title', feature, eyebrow, status, tone = 'idle' }) {
  const label = eyebrow ?? (feature ? groups[feature] : undefined);
  return <header className="panel-header">
    <div className="panel-header-mark" aria-hidden="true"><Layers size={20} strokeWidth={1.3} /></div>
    <div className="panel-header-title">{label && <span className="eyebrow">{label}</span>}<h2 id={titleId}>{title}</h2></div>
    {status && <StatusChip className="panel-header-status" tone={tone}>{status}</StatusChip>}
    <button type="button" className="icon-button" aria-label={closeLabel} onClick={onClose}><X size={20} aria-hidden="true" /></button>
  </header>;
}
