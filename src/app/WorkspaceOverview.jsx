import React, { lazy, Suspense } from 'react';
import { ArrowUpRight, Bell, Box, Camera, Cpu, Globe2, History, Image, ListChecks, Printer, Repeat, ShieldCheck, Smartphone, Zap } from 'lucide-react';
import PanelState from './PanelState';
import StatusChip from '../shared/ui/StatusChip';
import HudLabel from '../shared/ui/HudLabel';
const ConnectionReadiness = lazy(() => import('./ConnectionReadiness'));

/** Flat tool tile. `status` is shown only when the state is actually known. */
export function FeatureCard({ icon: Icon, title, description, status, tone = 'idle', onClick, disabled }) {
  return <button type="button" className="feature-card tool-tile hud-panel" onClick={onClick} disabled={disabled}>
    <span className="tool-tile__top"><Icon size={20} aria-hidden="true" className="tool-tile__icon"/>{status && <StatusChip tone={tone}>{status}</StatusChip>}</span>
    <span className="tool-tile__title">{title}</span>
    <span className="tool-tile__description">{description}</span>
  </button>;
}

export default function WorkspaceOverview({ page, gaming, onOpen }) {
  if (page === 'studio') return <div className="studio-overview">
    <div className="section-heading overview-heading"><HudLabel>TOOLS</HudLabel><button type="button" className="btn btn--ghost btn--sm" onClick={() => onOpen('activity')}><History size={14} aria-hidden="true"/>Recent artifacts</button></div>
    <div className="tool-grid studio-grid">
      <FeatureCard icon={Box} title="3D studio" description="Build, edit and export 3D models offline." status="OFFLINE" disabled={gaming} onClick={() => onOpen('cad')}/>
      {/* Model availability is only known inside the image tool, so no chip is shown here. */}
      <FeatureCard icon={Image} title="Images" description="Generate and revise images with a local model." disabled={gaming} onClick={() => onOpen('image')}/>
      <FeatureCard icon={Camera} title="Vision" description="Camera preview and hand tracking." status="ON DEMAND" disabled={gaming} onClick={() => onOpen('camera')}/>
      <FeatureCard icon={Globe2} title="Web inspector" description="Read a public page in a sandbox." status="ON DEMAND" onClick={() => onOpen('browser')}/>
      <FeatureCard icon={Printer} title="Print" description="Prepare models for your 3D printer." onClick={() => onOpen('printer')}/>
    </div>
    <div className="workspace-note"><ShieldCheck size={14} aria-hidden="true"/><p>Tools load when you open them. Generations and device actions need your approval.</p></div>
  </div>;
  if (page === 'tasks') return <div className="tool-grid">
    <FeatureCard icon={ListChecks} title="Tasks" description="Turn file and app actions into a plan you review step by step." onClick={() => onOpen('tasks')}/>
    <FeatureCard icon={Bell} title="Reminders" description="Schedule local reminders." onClick={() => onOpen('reminder')}/>
    <FeatureCard icon={Repeat} title="Routines" description="Run a set of steps from a phrase, a time of day or something that happens." onClick={() => onOpen('routines')}/>
  </div>;
  return <div className="connections-overview"><Suspense fallback={<PanelState compact kind="loading" title="Checking local readiness"/>}><ConnectionReadiness compact onOpen={onOpen}/></Suspense>
    <button type="button" className="call-lab-launch hud-panel" onClick={() => onOpen('calls')}><Smartphone size={20} aria-hidden="true" className="tool-tile__icon"/><span><HudLabel>EXPERIMENTAL</HudLabel><strong>Call lab</strong><small>Inspect readiness and rehearse the call bridge locally.</small></span><ArrowUpRight size={16} aria-hidden="true"/></button>
    <div className="section-heading overview-heading"><HudLabel>CONNECTIONS</HudLabel><button type="button" className="btn btn--ghost btn--sm" onClick={() => onOpen('capabilities')}>All capabilities</button></div>
    <div className="tool-grid connections-grid">
      <FeatureCard icon={Smartphone} title="Phone companion" description="Pair your Android phone with the permissions you choose." onClick={() => onOpen('phone')}/>
      <FeatureCard icon={Cpu} title="Desktop" description="Apps and selected system tools." onClick={() => onOpen('desktop')}/>
      <FeatureCard icon={Zap} title="Home" description="Supported lights, plugs and devices." onClick={() => onOpen('kasa')}/>
    </div>
  </div>;
}
