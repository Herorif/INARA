import React, { useState } from 'react';
import './panel-parts.css';
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
    <small>{job.background ? 'Background continuation is on.' : 'Closing this panel cancels this job.'} Closing the workspace, losing the last UI connection or starting gaming mode stops it.</small>
    {estimate && <dl className="job-lifetime__estimate">
      <div><dt className="hud-label">CPU</dt><dd>{estimate.cpu} threads</dd></div>
      <div><dt className="hud-label">RAM</dt><dd>{estimate.ram_mb} MB</dd></div>
      <div><dt className="hud-label">VRAM</dt><dd>{estimate.vram_mb} MB</dd></div>
    </dl>}
    {estimate && <small>Admission estimate. One creative worker runs at a time.</small>}
  </div>;
}
