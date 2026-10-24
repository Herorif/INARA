import React from 'react';
import { Layers, X } from 'lucide-react';
import './panel.css';

export default function PanelHeader({ title, onClose, closeLabel = 'Close panel', titleId = 'feature-title' }) {
  return <header className="panel-header">
    <div className="panel-header-mark" aria-hidden="true"><Layers size={20} strokeWidth={1.3} /></div>
    <div className="panel-header-title"><span className="eyebrow">INARA / WORKSPACE</span><h2 id={titleId}>{title}</h2></div>
    <span className="panel-header-mode">ON DEMAND</span>
    <button className="icon-button" aria-label={closeLabel} onClick={onClose}><X size={20} /></button>
  </header>;
}
