import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Box, Check, Download, Loader2, X } from 'lucide-react';
import useStore from '../../store';
import socket, { emitSocket } from '../../services/socket';
import { createRpcScope } from '../../transport/rpc.ts';
import { createCadClient } from '../../transport/cadClient.ts';
import { artifactBytes } from '../cad/client';
import ModelPreview from '../cad/ModelPreview';
import HudLabel from '../../shared/ui/HudLabel';
import LiveDesignCanvas from './LiveDesignCanvas';
import {
  ERROR_MS, REVEAL_MS, approvalCard, approvalLines, calloutView, chipView, emptyTimeline, footerKind, ghostAlive,
  hudLine, latestStep, matchingApproval, nextTimeline, pendingSteps, phaseRows, projectNote, revealProgress,
  snapshotPatch, studioDraft, summaryLine, unseenSteps, whoLabel,
} from './model.js';
import './liveDesign.css';

const REDUCED_MOTION = '(prefers-reduced-motion: reduce)';

function useReducedMotion() {
  const [reduced, setReduced] = useState(() => typeof window.matchMedia === 'function' && window.matchMedia(REDUCED_MOTION).matches);
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined;
    const query = window.matchMedia(REDUCED_MOTION);
    const change = () => setReduced(query.matches);
    query.addEventListener('change', change);
    return () => query.removeEventListener('change', change);
  }, []);
  return reduced;
}

const MIME = { stl: 'model/stl', glb: 'model/gltf-binary' };

/**
 * The owner's live design beside the conversation (docs/LIVE_DESIGN.md, "Workspace panel"):
 * the header, the 3D canvas, the steps and the footer. `visible` is false while the narrow
 * layout shows the conversation instead; only a visible panel marks steps seen and answers
 * its own build approvals (the global popup shows them otherwise).
 */
export default function LiveDesignPanel({ design, visible, gaming = false, onOpen }) {
  const connected = useStore(state => state.backendConnected);
  const currentProject = useStore(state => state.currentProject);
  const queue = useStore(state => state.confirmationQueue);
  const seen = useStore(state => state.liveDesignSeen);
  const reducedMotion = useReducedMotion();
  const [timeline, setTimeline] = useState(() => emptyTimeline(design.id));
  const [clock, setClock] = useState(() => performance.now());
  const [confirming, setConfirming] = useState(false);
  const [ending, setEnding] = useState(false);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const alive = useRef(true), rpc = useRef(null), cad = useRef(null), list = useRef(null);

  useEffect(() => {
    alive.current = true;
    rpc.current = createRpcScope(socket);
    cad.current = createCadClient(socket);
    return () => { alive.current = false; rpc.current.dispose(); cad.current.dispose(); };
  }, []);

  // The global approval popup skips this design's build while the panel is on screen.
  useEffect(() => {
    useStore.setState({ liveDesignPanelVisible: visible });
    return () => useStore.setState({ liveDesignPanelVisible: false });
  }, [visible]);

  // New steps while on screen: reveal new parts, highlight changes, ghost the old parts.
  useEffect(() => {
    if (!visible) return;
    const batch = unseenSteps(design, seen);
    if (!batch.length) return;
    const now = performance.now();
    setTimeline(previous => nextTimeline(previous, batch, design, { now, reducedMotion }));
    setClock(now);
    useStore.getState().setLiveDesignSeen({ id: design.id, n: latestStep(design) });
  }, [design, visible, seen, reducedMotion]);

  // Wake at the next reveal slot or ghost expiry, so the chip and rows follow the canvas.
  useEffect(() => {
    const times = [...timeline.reveal.flatMap(item => [item.at, item.at + REVEAL_MS]), timeline.ghost?.until ?? 0].filter(time => time > clock);
    if (!times.length) return undefined;
    const timer = setTimeout(() => setClock(performance.now()), Math.max(0, Math.min(...times) - performance.now()) + 16);
    return () => clearTimeout(timer);
  }, [timeline, clock]);

  useEffect(() => {
    if (!error) return undefined;
    const timer = setTimeout(() => setError(''), ERROR_MS);
    return () => clearTimeout(timer);
  }, [error]);

  useEffect(() => { if (design.status !== 'draft') setEnding(false); }, [design.status]);

  const live = timeline.id === design.id ? timeline : emptyTimeline(design.id);
  const reveal = revealProgress(live.reveal, clock);
  const waiting = pendingSteps(live.reveal, clock);
  const rows = design.steps.filter(step => !waiting.has(step.n));
  const ghost = ghostAlive(live.ghost, design, clock) ? live.ghost : null;
  const request = matchingApproval(queue, design.id);
  const card = approvalCard({ request, confirming, status: design.status });
  const chip = chipView({ status: design.status, reveal, approval: !!card });
  const kind = footerKind({ connected, status: design.status, approval: !!card });
  const callout = calloutView(design, { step: reveal.active ? reveal.step : null });
  const note = projectNote(design, currentProject);
  const offline = !connected;

  useLayoutEffect(() => {
    const element = list.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [rows.length, design.id]);

  const apply = useCallback(reply => {
    const patch = snapshotPatch(useStore.getState(), reply);
    if (patch) useStore.setState(patch);
  }, []);

  const run = useCallback(async (name, action) => {
    setBusy(name);
    setError('');
    try {
      await action();
    } catch (failure) {
      if (alive.current) setError(failure?.message || 'The live design action could not complete.');
    } finally {
      if (alive.current) setBusy('');
    }
  }, []);

  const call = useCallback((event, data, timeout) => rpc.current.call(event, data, timeout).then(apply), [apply]);
  const build = () => { setConfirming(false); run('build', () => call('cad_design_build', { design_id: design.id }, 70000)); };
  const answer = confirmed => {
    if (!request) return;
    emitSocket('confirm_tool', { id: request.id, confirmed });
    useStore.getState().resolveConfirmation(request.id);
  };
  const end = () => { setEnding(false); run('end', () => call('cad_design_end', { design_id: design.id })); };
  const undo = n => run(`undo:${n}`, () => call('cad_design_undo', { design_id: design.id, step: n }));
  const cancel = () => run('cancel', () => cad.current.call('cad_cancel', { request_id: design.job.request_id }));
  const download = format => run(format, async () => {
    const { artifact } = await cad.current.call('cad_artifact', { request_id: design.job.request_id, format });
    const bytes = await artifactBytes(artifact);
    if (!alive.current) return;
    const url = URL.createObjectURL(new Blob([bytes], { type: MIME[format] }));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = artifact.filename;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  const openStudio = () => {
    // A saved revision of this project opens selected; anything else goes over as the working draft.
    if (design.status === 'saved' && design.job?.request_id && !note) { onOpen?.('cad', undefined, design.job.request_id); return; }
    useStore.setState({ cadDraftHandoff: { recipe: studioDraft(design) } });
    onOpen?.('cad');
  };
  const requestEnd = () => { if (design.status === 'draft') setEnding(true); else end(); };

  const savedJob = useMemo(() => (design.status === 'saved' && design.job ? { request_id: design.job.request_id, state: 'succeeded', project: design.project, recipe: design.recipe } : null), [design]);
  const lines = approvalLines(design);
  const solid = <LiveDesignCanvas key={`${design.id}:solid`} objects={design.recipe.objects} mode="solid" reducedMotion={reducedMotion} />;

  return <section className="live-design" aria-labelledby="live-design-name" data-status={design.status} data-footer={kind}>
    <header className="live-design__header">
      <div className="live-design__heading">
        <HudLabel className="live-design__label">LIVE DESIGN</HudLabel>
        <h2 id="live-design-name" className="live-design__name" title={design.name}>{design.name}</h2>
        {note && <span className="live-design__project" title={`This design belongs to ${design.project}`}>{note}</span>}
        <span className="live-design__chip" data-tone={chip.tone} role="status">{chip.text}</span>
      </div>
      {ending
        ? <div className="live-design__confirm" role="group" aria-label="End live design">
          <span>End without building?</span>
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => setEnding(false)}>Keep designing</button>
          <button type="button" className="btn btn--danger btn--sm" disabled={offline || !!busy} onClick={end}>End</button>
        </div>
        : <div className="live-design__actions">
          <button type="button" className="btn btn--ghost btn--icon btn--sm" aria-label="Open in 3D studio" title={gaming ? 'Leave gaming mode to open the 3D studio' : 'Open in 3D studio'} disabled={offline || gaming} onClick={openStudio}><Box size={15} aria-hidden="true" /></button>
          <button type="button" className="btn btn--ghost btn--icon btn--sm" aria-label="End live design" title="End live design" disabled={offline || !!busy} onClick={requestEnd}><X size={15} aria-hidden="true" /></button>
        </div>}
    </header>

    <div className="live-design__stage">
      {savedJob
        ? <ModelPreview key={savedJob.request_id} job={savedJob} bare fallback={solid} />
        : <LiveDesignCanvas key={design.id} objects={design.recipe.objects} timeline={live} ghost={ghost} hold={reveal.active} reducedMotion={reducedMotion} />}
      {callout && <div className="live-design__callout" data-tone={callout.tone} title={callout.text}>{callout.text}</div>}
      <HudLabel className="live-design__hud live-design__hud--left">{hudLine(design.status)}</HudLabel>
      <HudLabel className="live-design__hud live-design__hud--right">Drag to orbit</HudLabel>
    </div>

    <ol ref={list} className="live-design__steps" aria-label="Design steps">
      {rows.map((step, index) => <li key={step.n} className={`live-design__step${index === rows.length - 1 ? ' is-newest' : ''}`} data-kind={step.kind}>
        <span className="live-design__who" data-who={step.who}>{whoLabel(step.who)}</span>
        <span className="live-design__step-title" title={step.title}>{step.title}</span>
        <span className="live-design__step-detail" title={step.detail}>{step.detail}</span>
        {step.undoable && <button type="button" className="btn btn--ghost btn--sm live-design__undo" disabled={offline || !!busy} onClick={() => undo(step.n)}>Undo</button>}
      </li>)}
    </ol>
    {error && <p className="live-design__error" role="alert">{error}</p>}

    <footer className="live-design__footer" data-kind={kind}>
      {kind === 'offline' && <>
        <div className="live-design__summary"><span className="status-dot status-dot--danger" aria-hidden="true" /><strong>Core offline</strong><span className="live-design__muted">{summaryLine(design, design.status === 'saved' ? 'saved' : 'draft')}</span></div>
        {(design.status === 'draft' || design.status === 'failed') && <div className="live-design__buttons"><button type="button" className="btn btn--primary btn--sm" disabled>Build it</button></div>}
      </>}
      {kind === 'approval' && <>
        <div className="live-design__approval"><strong>{lines.title}</strong><span>{lines.detail}</span></div>
        <div className="live-design__buttons">
          <button type="button" className="btn btn--secondary btn--sm" onClick={() => (card.source === 'request' ? answer(false) : setConfirming(false))}>Not now</button>
          <button type="button" className="btn btn--primary btn--sm" disabled={!!busy} onClick={() => (card.source === 'request' ? answer(true) : build())}>Build</button>
        </div>
      </>}
      {kind === 'draft' && <>
        <div className="live-design__summary">{summaryLine(design)}</div>
        <div className="live-design__buttons"><button type="button" className="btn btn--primary btn--sm" disabled={!!busy} onClick={() => setConfirming(true)}>Build it</button></div>
      </>}
      {kind === 'building' && <>
        <div className="live-design__building">
          <ol className="live-design__phases" aria-label="Build progress">{phaseRows(design.job).map(row => <li key={row.label} data-state={row.state}>{row.state === 'done' ? <Check size={13} aria-hidden="true" /> : row.state === 'active' ? <Loader2 size={13} className="live-design__spin" aria-hidden="true" /> : <span className="live-design__phase-dot" aria-hidden="true" />}<span>{row.label}</span></li>)}</ol>
          <span className="progress-line live-design__progress" aria-hidden="true" />
        </div>
        <div className="live-design__buttons"><button type="button" className="btn btn--secondary btn--sm" disabled={!!busy || !design.job} onClick={cancel}>Cancel</button></div>
      </>}
      {kind === 'saved' && <>
        <div className="live-design__summary">{summaryLine(design, 'saved')}</div>
        <div className="live-design__buttons">
          {['stl', 'glb'].map(format => <button type="button" key={format} className="btn btn--secondary btn--sm" disabled={!!busy} onClick={() => download(format)}>{busy === format ? <Loader2 size={13} className="live-design__spin" aria-hidden="true" /> : <Download size={13} aria-hidden="true" />}{format.toUpperCase()}</button>)}
          <button type="button" className="btn btn--ghost btn--sm" disabled={gaming} onClick={openStudio}><Box size={13} aria-hidden="true" />Open in 3D studio</button>
        </div>
      </>}
      {kind === 'failed' && <>
        <div className="live-design__summary live-design__failure" title={design.job?.error || ''}>{design.job?.error || 'The build stopped before it finished.'}</div>
        <div className="live-design__buttons"><button type="button" className="btn btn--primary btn--sm" disabled={!!busy} onClick={() => setConfirming(true)}>Try again</button></div>
      </>}
    </footer>
  </section>;
}
