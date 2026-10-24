import React, {useEffect, useRef, useState} from 'react';
import {PhoneCall, ShieldCheck, FlaskConical, RefreshCw, Square, ArrowUpRight, Bluetooth, AudioLines} from 'lucide-react';
import useStore from '../store';
import socket from '../services/socket';
import {createCallLabClient} from '../transport/callLabClient.ts';
import PanelState from './PanelState';
import ControlledCallTest from './ControlledCallTest';
import './call-lab.css';

export default function CallLab() {
  const project = useStore(state => state.currentProject);
  const connected = useStore(state => state.backendConnected);
  const [report, setReport] = useState(null), [record, setRecord] = useState(null);
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const client = useRef(null), epoch = useRef(0), active = useRef(null), refresh = useRef(() => {});
  const readVersion = useRef(0), mutating = useRef(false);
  useEffect(() => {
    const generation = ++epoch.current, api = createCallLabClient(socket, project);
    mutating.current = false; readVersion.current++;
    client.current = api; active.current = null;
    setReport(null); setRecord(null); setError(''); setBusy(false);
    let reading = false;
    refresh.current = async () => {
      if (reading || mutating.current || !socket.connected) return;
      reading = true;
      const version = ++readVersion.current;
      try {
        const next = await api.state();
        if (epoch.current === generation && version === readVersion.current) {
          setReport(next);
          active.current = next.runs.find(item => item.state === 'running')?.id || null;
        }
      } catch (failure) { if (epoch.current === generation && version === readVersion.current) { setError(failure.message); setReport(null); setRecord(null); } }
      finally { reading = false; }
    };
    refresh.current();
    const timer = setInterval(() => { if (!document.hidden) refresh.current(); }, 1000);
    return () => {
      epoch.current++; clearInterval(timer);
      if (active.current && socket.connected) api.stop(active.current).catch(() => {});
      active.current = null; api.dispose();
    };
  }, [project, connected]);
  const act = async operation => {
    const generation = epoch.current;
    readVersion.current++; mutating.current = true;
    setBusy(true); setError('');
    try {
      const next = await operation();
      if (epoch.current !== generation) return;
      if (next.runs) {
        setReport(next); active.current = next.runs.find(item => item.state === 'running')?.id || null;
      } else setRecord(next);
    } catch (failure) { if (epoch.current === generation) setError(failure.message); }
    finally { if (epoch.current === generation) { readVersion.current++; mutating.current = false; setBusy(false); } }
  };
  const running = report?.runs.find(item => item.state === 'running');
  return <div className="call-lab tool-panel">
    <header className="call-lab__hero"><div className="call-lab__emblem"><PhoneCall size={27}/></div>
      <span className="eyebrow">INARA / CALL BRIDGE LAB</span><h2>A voice at your side.</h2>
      <p>Prepare your personal call assistant. Explore the bridge with an isolated local simulation in <b>{project}</b>.</p>
      <span className="call-lab__badge"><ShieldCheck size={14}/>Unattended answering off / controlled tests gated</span>
    </header>
    <div className="call-lab__routes"><article><Bluetooth size={21}/><span className="eyebrow">SIM / PHONE LINK</span><h3>Your number. Your carrier.</h3><p>Windows Bluetooth is the candidate route. Phone pairing, call controls and isolated audio still need a real-device test.</p></article>
      <article><PhoneCall size={21}/><span className="eyebrow">WHATSAPP / PERSONAL ACCOUNT</span><h3>Keep your conversations yours.</h3><p>The official Windows client is the candidate bridge. Automatic answering is experimental and remains unverified.</p></article></div>
    <section className="call-lab__readiness" aria-label="Call bridge readiness"><header><strong>Local readiness</strong><button disabled={!connected || busy} onClick={() => {setError('');refresh.current();}} aria-label="Refresh call bridge readiness"><RefreshCw size={15}/></button></header>
      <dl>{[['Native control helper', report?.helper_built], ['Dedicated audio adapter', report?.audio_installed], ['Local English speech components', report?.voice_configured]].map(([label, ready]) => <div key={label}><dt>{label}</dt><dd>{ready == null ? 'Unknown' : ready ? 'Present / unverified' : 'Setup needed'}</dd></div>)}</dl>
      <dl><div><dt>Shared session admission</dt><dd>{!report ? 'Unknown' : report.admission.admission_ready ? 'Software ready / device test pending' : 'Not ready'}</dd></div>
        <div><dt>Optional conversational model</dt><dd>{!report ? 'Unknown' : report.model_accepted ? 'Local evaluation passed' : report.model_installed ? 'Installed / evaluation needed' : 'Not installed'}</dd></div>
        <div><dt>Speech processing</dt><dd>Local only / no cloud fallback</dd></div></dl>
      {report && <p role="status">{report.admission.blockers.map(code => ({call_components_missing: 'Local components need setup', call_resources_busy: 'Another worker owns the resources', resource_policy: 'Leave resident or gaming mode', resource_fault: 'Resource checks need attention', resource_capacity: 'Not enough available capacity', call_physical_unverified: 'Controlled phone and audio acceptance pending'}[code])).join(' · ')}.</p>}
      <p>Presence is not proof of live calling. This panel opens no phone app, microphone or provider.</p></section>
    <ControlledCallTest project={project} connected={connected}/>
    {error && <PanelState compact kind="error" title="Bridge check interrupted" detail={error}/>}
    <section className="call-lab__check"><div><FlaskConical size={23}/><h3>Rehearse the bridge.</h3><p>A disposable worker exercises the call lifecycle using synthetic controls, audio and speech. It saves a labeled test transcript, then exits.</p></div>
      <div className="call-lab__actions"><button className="primary-button" disabled={!connected || busy || !report?.worker_supported || report?.worker_busy} onClick={() => {
        const id = crypto.randomUUID(); active.current = id; setRecord(null);
        return act(() => client.current.check(id));
      }}><FlaskConical size={16}/>Run isolated bridge check</button>
      {running && <button disabled={busy || !connected} onClick={() => act(() => client.current.stop(running.id))}><Square size={14}/>Stop check</button>}</div>
      {running && <p className="call-lab__progress" role="status"><AudioLines size={16}/>Simulation running · No live call</p>}
    </section>
    <section className="call-lab__history"><h3>Bridge check history</h3><p>These are software diagnostics, not a history of real callers.</p>
      {!report?.runs.length && <PanelState compact kind="empty" title="A clear line to begin" detail="Run a local check to inspect the supervised lifecycle. Real call acceptance is a separate step."/>}
      {report?.runs.map(item => <article key={item.id}><div><strong>Offline simulation</strong><small>{new Date(item.started_at * 1000).toLocaleString()}</small></div><span className={`call-lab__state is-${item.state}`}>{item.state}</span>
        {item.record_id && item.state !== 'running' && <button disabled={busy || !connected} onClick={() => act(() => client.current.record(item.id, item.record_id))}>Review test record <ArrowUpRight size={13}/></button>}
        {item.code && <small className="call-lab__code">{item.code.replaceAll('_', ' ')}</small>}</article>)}
    </section>
    {record && <section className="call-lab__transcript" aria-label="Synthetic call transcript"><header><div><span className="eyebrow">SYNTHETIC / LOCAL RECORD</span><h3>Inside the rehearsal.</h3></div><button onClick={() => setRecord(null)}>Close record</button></header>
      {record.transcript.map((item, index) => <div className={`call-lab__segment is-${item.role}`} key={index}><strong>{item.role === 'caller' ? 'Simulated caller' : 'Simulated INARA'}</strong><p>{item.text}</p></div>)}
      {!record.transcript.length && <p>No transcript was captured before this check stopped.</p>}</section>}
    <footer><ShieldCheck size={16}/><p>Checks stay with this owner and project. Closing the panel, disconnecting, locking, changing project or entering gaming mode stops its worker. Personal WhatsApp text replies stay off.</p></footer>
  </div>;
}
