import React, { useState } from 'react';
import './capabilities.css';
export default function JobLifetime({ job, connected, onChange }) {
  const [saving, setSaving] = useState(false);
  if (!job || !['queued', 'running'].includes(job.state)) return null;
  const estimate = job.resources?.estimate;
  return <div className="job-lifetime">
    <label><input type="checkbox" checked={!!job.background} disabled={!connected || saving} onChange={async event => {
      const enabled = event.target.checked;
      setSaving(true);
      try { await onChange(enabled); } finally { setSaving(false); }
    }} /> Continue this job after closing this panel</label>
    <small>{job.background ? 'Background continuation enabled.' : 'Closing this panel cancels this job.'} Workspace closure, loss of the last UI connection, or gaming mode stops it.</small>
    {estimate && <small>Admission estimate: {estimate.cpu} CPU threads / {estimate.ram_mb} MB RAM / {estimate.vram_mb} MB VRAM. One creative worker at a time.</small>}
  </div>;
}
