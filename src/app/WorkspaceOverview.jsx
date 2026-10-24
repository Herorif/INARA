import React, { lazy, Suspense } from 'react';
import { ArrowUpRight, Box, Camera, Globe2, Image, History, Smartphone, Cpu, Zap, ListChecks, Bell, ShieldCheck } from 'lucide-react';
import PanelState from './PanelState';
const ConnectionReadiness = lazy(() => import('./ConnectionReadiness'));

function StudioIllustration({ kind }) {
  return <div className={`studio-illustration illustration-${kind}`} aria-hidden="true">
    {kind === 'cad' ? <svg viewBox="0 0 240 150" fill="none"><path className="illustration-grid" d="M0 120 120 50 240 120M0 90 120 20 240 90M0 150 120 80 240 150M40 150 160 80M80 150 200 80M40 80 160 150M80 80 200 150"/><path className="cube-top" d="m120 24 59 34-59 34-59-34z"/><path className="cube-left" d="m61 58 59 34v59l-59-34z"/><path className="cube-right" d="m120 92 59-34v59l-59 34z"/><path className="cube-line" d="m120 24 59 34v59l-59 34-59-34V58zM61 58l59 34 59-34M120 92v59"/><path className="cube-detail" d="m120 45 23 13-23 13-23-13zM73 80l34 20v31M133 99l33-19v29"/></svg> : kind === 'image' ? <><div className="image-orbit"/><div className="image-planet"/><div className="image-frame"/></> : <><div className="vision-reticle"/><div className="vision-focus"/><div className="vision-crosshair"/></>}
  </div>;
}
export function FeatureCard({ icon: Icon, title, description, tag, onClick, disabled, kind }) {
  return <button type="button" className={`feature-card ${kind ? `feature-card--${kind}` : ''}`} onClick={onClick} disabled={disabled}>
    <span className="feature-card-top"><span className="feature-icon"><Icon size={20}/></span><span className="feature-tag">{tag}</span><ArrowUpRight size={17}/></span>
    {kind && <StudioIllustration kind={kind}/>}
    <span className="feature-card-copy"><strong>{title}</strong><span>{description}</span></span>
  </button>;
}
export default function WorkspaceOverview({ page, gaming, onOpen }) {
  if (page === 'studio') return <div className="studio-overview">
    <div className="section-heading overview-heading"><span className="eyebrow">CREATE / EXPLORE / REFINE</span><button className="text-button" onClick={() => onOpen('activity')}><History size={14}/> Recent artifacts <ArrowUpRight size={14}/></button></div>
    <div className="feature-grid studio-grid">
      <FeatureCard kind="cad" icon={Box} title="3D studio" description="From a first shape to a scene worth exploring. Build, refine and export." tag="OFFLINE TOOLS" disabled={gaming} onClick={() => onOpen('cad')}/>
      <FeatureCard kind="image" icon={Image} title="Image atelier" description="Shape a visual direction. Work with prompts, seeds and saved revisions." tag="LOCAL GENERATION" disabled={gaming} onClick={() => onOpen('image')}/>
      <FeatureCard kind="vision" icon={Camera} title="Vision studio" description="A new perspective. Preview your camera and explore local hand tracking." tag="START ON DEMAND" disabled={gaming} onClick={() => onOpen('camera')}/>
    </div>
    <div className="studio-support"><button onClick={() => onOpen('browser')}><Globe2 size={22}/><span><strong>Web inspector</strong><small>Bring a public page into focus.</small></span><ArrowUpRight size={18}/></button><button onClick={() => onOpen('printer')}><Box size={22}/><span><strong>Print workshop</strong><small>Prepare the next physical creation.</small></span><ArrowUpRight size={18}/></button></div>
    <div className="workspace-note"><ShieldCheck size={16}/><p>Tools load when you open them. Generations and device actions stay under your control.</p></div>
  </div>;
  if (page === 'tasks') return <div className="feature-grid"><FeatureCard icon={ListChecks} title="Reviewed tasks" description="Turn a sequence of file and app actions into a plan you can inspect." tag="ONE STEP AT A TIME" onClick={() => onOpen('tasks')}/><FeatureCard icon={Bell} title="Reminders" description="Give the important things a place in your day." tag="LOCAL SCHEDULES" onClick={() => onOpen('reminder')}/></div>;
  return <div className="connections-overview"><Suspense fallback={<PanelState compact kind="loading" title="Checking local readiness"/>}><ConnectionReadiness compact onOpen={onOpen}/></Suspense>
    <button className="call-lab-launch" onClick={() => onOpen('calls')}><Smartphone size={23}/><span><span className="eyebrow">PERSONAL CALL ASSISTANT / EXPERIMENTAL</span><strong>Build a clearer connection.</strong><small>Inspect readiness and rehearse the bridge locally.</small></span><ArrowUpRight size={19}/></button>
    <div className="section-heading overview-heading"><span className="eyebrow">YOUR CONNECTIONS</span><button className="text-button" onClick={() => onOpen('capabilities')}>All capabilities <ArrowUpRight size={14}/></button></div>
    <div className="feature-grid connections-grid"><FeatureCard icon={Smartphone} title="Android companion" description="A paired connection to your phone, with permissions you choose." tag="PAIR ON DEMAND" onClick={() => onOpen('phone')}/><FeatureCard icon={Cpu} title="Desktop controls" description="Your apps and selected system tools in one place." tag="REVIEWED ACTIONS" onClick={() => onOpen('desktop')}/><FeatureCard icon={Zap} title="Smart home" description="Open your supported lights, plugs and devices." tag="OPTIONAL SETUP" onClick={() => onOpen('kasa')}/></div>
  </div>;
}
