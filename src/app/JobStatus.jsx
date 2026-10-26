import React from 'react';
import { Check, Loader2 } from 'lucide-react';
import './panel-parts.css';

/** One-line job state: icon, phase title and a single meta line. */
export default function JobStatus({ className = '', title, subtitle, ready, busy }) {
  const tone = ready ? 'ok' : busy ? 'accent' : 'idle';
  return <div className={`job-status ${className} ${ready ? 'ready' : ''}`.trim()} data-tone={tone} role="status">
    <span className="job-status__icon" aria-hidden="true">{ready ? <Check size={16} /> : busy ? <Loader2 className="panel-progress-spinner" size={16} /> : <span className="status-dot" />}</span>
    <div><strong>{title}</strong><span>{subtitle}</span></div>
  </div>;
}
