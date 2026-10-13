import React, { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { Box, CornerDownRight, PackageOpen, Download, Layers3, Loader2, Sparkles, Square, Check, RefreshCw } from 'lucide-react';
import useStore from '../../store';
import socket from '../../services/socket';
import ModelPreview from './ModelPreview';
import { artifactBytes, cadRpc, mergeJob, pendingJob } from './client';
import './cad.css';
const LegacyCad = lazy(() => import('../../components/CadWindow'));
const defaults = {
  name: 'My first design',
  shape: 'box',
  width: 80,
  depth: 60,
  height: 30,
  thickness: 3
};
const shapes = [{
  id: 'box',
  label: 'Solid box',
  icon: Box
}, {
  id: 'bracket',
  label: 'L bracket',
  icon: CornerDownRight
}, {
  id: 'enclosure',
  label: 'Open enclosure',
  icon: PackageOpen
}];
const phases = {
  submitting: 'Sending your build',
  awaiting_approval: 'Waiting for your approval',
  queued: 'Preparing worker',
  building: 'Building geometry',
  validating: 'Checking the solid',
  saving: 'Saving exports',
  ready: 'Ready to explore',
  cancelled: 'Build cancelled',
  interrupted: 'Build interrupted',
  stopped: 'Build stopped'
};
export default function CadStudio() {
  const project = useStore(state => state.currentProject),
    connected = useStore(state => state.backendConnected),
    legacyData = useStore(state => state.cadData);
  const [recipe, setRecipe] = useState(defaults),
    [jobs, setJobs] = useState([]),
    [selected, setSelected] = useState(null);
  const [error, setError] = useState(''),
    [prompt, setPrompt] = useState(''),
    [planning, setPlanning] = useState(false),
    [exporting, setExporting] = useState(''),
    [wireframe, setWireframe] = useState(false),
    [legacy, setLegacy] = useState(false);
  const selectedRef = useRef(null),
    alive = useRef(false),
    epoch = useRef(0);
  const job = jobs.find(value => value.request_id === selected),
    busy = pendingJob(job);
  const accept = incoming => {
    if (!alive.current || incoming.project !== useStore.getState().currentProject) return;
    setJobs(previous => {
      const old = previous.find(value => value.request_id === incoming.request_id);
      return [mergeJob(old, incoming), ...previous.filter(value => value.request_id !== incoming.request_id)].slice(0, 12);
    });
    if (!selectedRef.current) {
      selectedRef.current = incoming.request_id;
      setSelected(incoming.request_id);
    }
  };
  const refresh = async () => {
    const generation = epoch.current;
    try {
      const response = await cadRpc(socket, 'cad_list');
      if (!alive.current || generation !== epoch.current) return;
      setJobs(previous => response.jobs.map(incoming => mergeJob(previous.find(value => value.request_id === incoming.request_id), incoming)));
      if (!selectedRef.current && response.jobs[0]) {
        selectedRef.current = response.jobs[0].request_id;
        setSelected(response.jobs[0].request_id);
        setRecipe(response.jobs[0].recipe);
      }
    } catch (failure) {
      if (alive.current && generation === epoch.current) setError(failure.message);
    }
  };
  useEffect(() => {
    epoch.current++;
    alive.current = true;
    selectedRef.current = null;
    setSelected(null);
    setJobs([]);
    setError('');
    setPlanning(false);
    setExporting('');
    const update = incoming => accept(incoming);
    socket.on('cad_job', update);
    socket.on('connect', refresh);
    if (socket.connected) refresh();
    return () => {
      alive.current = false;
      socket.off('cad_job', update);
      socket.off('connect', refresh);
      if (socket.connected) cadRpc(socket, 'cad_close').catch(() => {});
      if (useStore.getState().confirmationRequest?.tool === 'generate_cad') useStore.setState({
        confirmationRequest: null
      });
    };
  }, [project]);
  const build = async event => {
    const generation = epoch.current;
    event.preventDefault();
    setError('');
    const request_id = crypto.randomUUID();
    selectedRef.current = request_id;
    setSelected(request_id);
    accept({
      request_id,
      recipe,
      project,
      state: 'submitting',
      phase: 'submitting'
    });
    try {
      const response = await cadRpc(socket, 'cad_submit', {
        ...recipe,
        request_id
      }, 70000);
      accept(response.job);
    } catch (failure) {
      if (alive.current && generation === epoch.current) {
        setError(failure.message);
        accept({
          request_id,
          project,
          state: 'failed',
          phase: 'stopped',
          error: failure.message
        });
      }
    }
  };
  const cancel = async () => {
    try {
      accept((await cadRpc(socket, 'cad_cancel', {
        request_id: selected
      })).job);
    } catch (failure) {
      setError(failure.message);
    }
  };
  const plan = async () => {
    const generation = epoch.current;
    setPlanning(true);
    setError('');
    try {
      const response = await cadRpc(socket, 'cad_plan', {
        prompt
      }, 40000);
      if (alive.current && generation === epoch.current) setRecipe(response.recipe);
    } catch (failure) {
      if (alive.current && generation === epoch.current) setError(failure.message);
    } finally {
      if (alive.current && generation === epoch.current) setPlanning(false);
    }
  };
  const download = async format => {
    const generation = epoch.current;
    setExporting(format);
    setError('');
    try {
      const {
        artifact
      } = await cadRpc(socket, 'cad_artifact', {
        request_id: selected,
        format
      });
      const bytes = await artifactBytes(artifact);
      if (!alive.current || generation !== epoch.current) return;
      const url = URL.createObjectURL(new Blob([bytes], {
        type: format === 'glb' ? 'model/gltf-binary' : format === 'json' ? 'application/json' : 'model/stl'
      }));
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = artifact.filename;
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (failure) {
      if (alive.current && generation === epoch.current) setError(failure.message);
    } finally {
      if (alive.current && generation === epoch.current) setExporting('');
    }
  };
  if (legacy) return <div className="cad-legacy"><button className="text-button" onClick={() => setLegacy(false)}>Return to parametric Studio</button><Suspense fallback={<div className="panel-empty">Loading previous design…</div>}><LegacyCad onClose={() => setLegacy(false)} /></Suspense></div>;
  return <div className="cad-studio">
    <div className="cad-intro"><div><span className="eyebrow">IDEA → SOLID</span><h3>Give your idea dimension<span>.</span></h3><p>Local geometry. Your project. A new revision every build.</p></div><span className="cad-local-badge"><span className="status-dot" />OFFLINE READY</span></div>
    <div className="cad-layout">
      <aside className="cad-builder">
        <form onSubmit={build}>
          <span className="eyebrow">01 / BLUEPRINT</span>
          <div className="cad-shapes" role="group" aria-label="Shape">{shapes.map(({
              id,
              label,
              icon: Icon
            }) => <button type="button" key={id} className={recipe.shape === id ? 'selected' : ''} aria-pressed={recipe.shape === id} disabled={busy || planning} onClick={() => setRecipe(previous => ({
              ...previous,
              shape: id
            }))}><Icon size={21} /><span>{label}</span></button>)}</div>
          <label className="cad-field">Design name<input value={recipe.name} required maxLength={60} disabled={busy || planning} onChange={event => setRecipe(previous => ({
              ...previous,
              name: event.target.value
            }))} /></label>
          <div className="cad-dimensions">{['width', 'depth', 'height', ...(recipe.shape !== 'box' ? ['thickness'] : [])].map(key => <label className="cad-field" key={key}>{key === 'thickness' ? 'Wall thickness' : key[0].toUpperCase() + key.slice(1)}<div className="cad-number"><input aria-label={`${key} in millimetres`} type="number" min={key === 'thickness' ? .5 : 1} max={key === 'thickness' ? 100 : 1000} step="any" required value={recipe[key]} disabled={busy || planning} onChange={event => setRecipe(previous => ({
                  ...previous,
                  [key]: event.target.value === '' ? '' : Number(event.target.value)
                }))} /><span>mm</span></div></label>)}</div>
          <p className="cad-builder-note">{recipe.shape === 'enclosure' ? 'Open top, flat base and uniform walls.' : recipe.shape === 'bracket' ? 'One continuous solid with a base and upright.' : 'A closed rectangular solid, ready for refinement.'}</p>
          <button className="primary-button cad-build" type="submit" disabled={!connected || busy || planning}>{busy ? <Loader2 size={16} className="cad-spinner" /> : <Box size={17} />}{busy ? 'Build in progress' : 'Build new revision'}</button>
          {busy && <button className="cad-cancel" type="button" onClick={cancel}><Square size={13} />Cancel build</button>}
        </form>
        <details className="cad-ai"><summary><Sparkles size={15} />AI blueprint<span>OPTIONAL</span></summary><p>Describe one supported solid. Review its dimensions before building.</p><textarea aria-label="Blueprint description" maxLength={2000} value={prompt} disabled={planning || busy} placeholder="An open enclosure, 80 × 60 × 30 mm, with 3 mm walls…" onChange={event => setPrompt(event.target.value)} /><button className="text-button" disabled={!connected || planning || busy || !prompt.trim()} onClick={plan}>{planning ? 'Proposing dimensions…' : 'Propose dimensions'}<Sparkles size={13} /></button></details>
        {legacyData && <button className="text-button" onClick={() => setLegacy(true)}>Open previous voice design</button>}
      </aside>
      <section className="cad-workbench" aria-label="Model and exports">
        <div className="cad-preview-top"><span className="eyebrow">02 / EXPLORE</span><button className="text-button" aria-pressed={wireframe} onClick={() => setWireframe(value => !value)}><Layers3 size={14} />{wireframe ? 'Show solid' : 'Wireframe'}</button></div>
        <ModelPreview job={job} wireframe={wireframe} />
        <div className={`cad-status ${job?.state === 'succeeded' ? 'ready' : ''}`} role="status">{job?.state === 'succeeded' ? <Check size={16} /> : busy ? <Loader2 className="cad-spinner" size={16} /> : <span className="status-dot" />}<div><strong>{phases[job?.phase] || 'Ready to build'}</strong><span>{job?.state === 'succeeded' ? 'Solid validated · Worker released' : 'Builds run separately from your resident assistant'}</span></div><span className="cad-status-unit">MM</span></div>
        {job?.stats && <div className="cad-stats"><div><span>Dimensions</span><strong>{job.recipe.width} × {job.recipe.depth} × {job.recipe.height}<small> mm</small></strong></div><div><span>Volume</span><strong>{(job.stats.volume_mm3 / 1000).toFixed(2)}<small> cm³</small></strong></div><div><span>Mesh</span><strong>{job.stats.triangles}<small> triangles</small></strong></div><div><span>Topology</span><strong>Watertight</strong></div></div>}
        <div className="cad-export"><div><span className="eyebrow">03 / TAKE IT FURTHER</span><p>STL for fabrication · GLB for Blender and other 3D apps</p></div><div>{['stl', 'glb', 'json'].map(format => <button key={format} disabled={!connected || job?.state !== 'succeeded' || !!exporting} onClick={() => download(format)}>{exporting === format ? <Loader2 size={14} className="cad-spinner" /> : <Download size={14} />}{format === 'json' ? 'Recipe' : format.toUpperCase()}</button>)}</div></div>
      </section>
    </div>
    {(error || job?.error) && <div className="cad-error" role="alert">{error || job.error}</div>}
    <section className="cad-history"><div><span className="eyebrow">RECENT REVISIONS / {project}</span><button className="text-button" aria-label="Refresh build history" onClick={refresh} disabled={!connected || busy}><RefreshCw size={13} /></button></div><div className="cad-history-list">{jobs.length ? jobs.slice(0, 5).map(value => <button key={value.request_id} disabled={busy} className={selected === value.request_id ? 'selected' : ''} onClick={() => {
          selectedRef.current = value.request_id;
          setSelected(value.request_id);
          if (value.recipe) setRecipe(value.recipe);
          setError('');
        }}><Box size={16} /><span>{value.recipe?.name || 'New design'}<small>{value.recipe?.shape || 'Build'} · {value.request_id.slice(0, 8)}</small></span><em>{value.state}</em></button>) : <p>Your saved revisions will appear here.</p>}</div></section>
  </div>;
}
