import React from 'react';
import { Check, Loader2 } from 'lucide-react';
export default function JobStatus({ className, title, subtitle, ready, busy }) {
  return <div className={`${className} ${ready ? 'ready' : ''}`} role="status">
    {ready ? <Check size={16} /> : busy ? <Loader2 className="panel-progress-spinner" size={16} /> : <span className="status-dot" />}
    <div><strong>{title}</strong><span>{subtitle}</span></div>
  </div>;
}
