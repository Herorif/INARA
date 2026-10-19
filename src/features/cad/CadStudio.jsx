import React, { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { Box, CornerDownRight, PackageOpen, Download, Layers3, Loader2, Sparkles, Square } from 'lucide-react';
import useStore from '../../store';
import socket from '../../services/socket';
import ModelPreview from './ModelPreview';
import DraftPreview from './DraftPreview';
import SceneEditor, { newObject } from './SceneEditor';
import { artifactBytes, mergeJob, pendingJob } from './client';
import { createCadClient } from '../../transport/cadClient.ts';
import { reconcileHistory } from '../../transport/history.ts';
import PanelState from '../../app/PanelState';
import RevisionHistory from '../../app/RevisionHistory';
import JobStatus from '../../app/JobStatus';
import JobLifetime from '../../app/JobLifetime';
import Field from '../../app/Field';
import './cad.css';
import { useRecipeDraft } from '../creative/useRecipeDraft';
import { parentReference } from '../creative/draft';
import RevisionTools, { RecipeComparison } from '../creative/RevisionTools';
const LegacyCad = lazy(() => import('../../components/CadWindow'));
const defaults = {
  name: 'My first design',
  shape: 'box',
  width: 80,
  depth: 60,
  height: 30,
  thickness: 3, objects: null, engine:'offline', presentation:{camera:'isometric',lighting:'studio',quality:'preview',background:'dark'}
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
}, {
  id: 'scene',
  label: 'Scene assembly',
  icon: Layers3
}];
const phases = {
  submitting: 'Sending your build',
  awaiting_approval: 'Waiting for your approval',
  queued: 'Preparing worker',
  building: 'Building geometry',
  validating: 'Checking the solid',
  saving: 'Saving exports',
  blender: 'Blender project and render',
  ready: 'Ready to explore',
  cancelled: 'Build cancelled',
  interrupted: 'Build interrupted',
  stopped: 'Build stopped'
};
export default function CadStudio() {
  const project = useStore((state) => state.currentProject);
  return <CadSession key={project} project={project} />;
}
function CadSession({ project }) {
  const connected = useStore((state) => state.backendConnected),legacyData = useStore((state) => state.cadData);
  const transport = useRef(null),latestRefresh = useRef(0),historyVersion = useRef(0),jobVersions = useRef(new Map());
  const [refreshing, setRefreshing] = useState(true),[uncertain, setUncertain] = useState(false);
  const rpc = (...args) => transport.current.call(...args);
  const draft = useRecipeDraft(defaults);
  const { recipe, setRecipe, resetRecipe } = draft;
  const [base, setBase] = useState(null), [compare, setCompare] = useState(''), [proposal, setProposal] = useState(null);
  const [objectIndex, setObjectIndex] = useState(0), [draftView, setDraftView] = useState(false);
  const [jobs, setJobs] = useState([]),
    [selected, setSelected] = useState(null);
  const [error, setError] = useState(''),
    [prompt, setPrompt] = useState(''),
    [planning, setPlanning] = useState(false),
    [exporting, setExporting] = useState(''),
    [wireframe, setWireframe] = useState(false),
    [legacy, setLegacy] = useState(false);
  const [capabilities, setCapabilities] = useState({
    blender: false
  });
  const selectedRef = useRef(null),
    alive = useRef(false),
    epoch = useRef(0);
  const restoreRecipe = useRef(true), pendingBranch = useRef(null);
  const job = jobs.find((value) => value.request_id === selected),
    busy = pendingJob(job);
  const accept = (incoming) => {
    if (!alive.current || incoming.project !== useStore.getState().currentProject) return;
    useStore.getState().recordActivity('cad', incoming);
    if (incoming.state === 'succeeded' && incoming.request_id === pendingBranch.current) {setBase(incoming);pendingBranch.current=null;}
    jobVersions.current.set(incoming.request_id, ++historyVersion.current);
    setJobs((previous) => {
      const old = previous.find((value) => value.request_id === incoming.request_id);
      return [mergeJob(old, incoming), ...previous.filter((value) => value.request_id !== incoming.request_id)].slice(0, 12);
    });
    if (!selectedRef.current) {
      selectedRef.current = incoming.request_id;
      setSelected(incoming.request_id);
    }
  };
  const refresh = async () => {
    const generation = epoch.current,id = ++latestRefresh.current,version = historyVersion.current;
    setRefreshing(true);
    try {
      const response = await rpc('cad_list', {});
      if (!alive.current || generation !== epoch.current || id !== latestRefresh.current) return;
      setError('');setUncertain(false);
      setCapabilities(response.capabilities || {
        blender: false
      });
      setJobs((previous) => reconcileHistory(previous, response.jobs, new Set([...jobVersions.current].filter(([, updated]) => updated > version).map(([key]) => key))));
      const completed=response.jobs.find(value=>value.request_id===pendingBranch.current && value.state==='succeeded');
      if(completed){setBase(completed);pendingBranch.current=null;}
      if (restoreRecipe.current) {
        const restored = response.jobs.find(value => value.request_id === selectedRef.current) || (!selectedRef.current ? response.jobs[0] : null);
        if (restored) { selectedRef.current = restored.request_id; setSelected(restored.request_id); resetRecipe(restored.recipe); setBase(restored.state === 'succeeded' ? restored : null); }
        else if (selectedRef.current) setError('That revision is outside recent history. Select another saved revision.');
        restoreRecipe.current = false;
      }
    } catch (failure) {
      if (alive.current && generation === epoch.current && id === latestRefresh.current) setError(failure.message);
    } finally {
      if (alive.current && generation === epoch.current && id === latestRefresh.current) setRefreshing(false);
    }
  };
  useEffect(() => {
    const client = createCadClient(socket);transport.current = client;
    epoch.current++;
    restoreRecipe.current = true;
    alive.current = true;
    const selection = useStore.getState().studioSelection;
    selectedRef.current = selection?.feature === 'cad' && selection.project === project ? selection.requestId : null;
    setSelected(selectedRef.current);
    setJobs([]);
    resetRecipe(defaults);
    setBase(null);setCompare('');setProposal(null);setObjectIndex(0);
    setCapabilities({
      blender: false
    });
    setError('');
    setPlanning(false);
    setExporting('');
    const update = (incoming) => accept(incoming);
    client.on('cad_job', update);
    client.on('connect', refresh);
    client.on('disconnect', () => {epoch.current++;setPlanning(false);setExporting('');setRefreshing(false);setUncertain(true);});
    if (socket.connected) refresh();
    return () => {
      alive.current = false;
      client.dispose();
      if (socket.connected) socket.emit('cad_close', {});
      if (['generate_cad', 'plan_cad', 'plan_cad_changes'].includes(useStore.getState().confirmationRequest?.tool)) useStore.setState({
        confirmationRequest: null
      });
    };
  }, [project]);
  const build = async (event) => {
    const generation = epoch.current;
    event.preventDefault();
    setError('');
    const request_id = crypto.randomUUID();
    selectedRef.current = request_id;pendingBranch.current=request_id;
    setSelected(request_id);
    accept({
      request_id,
      recipe,
      project,
      state: 'submitting',
      phase: 'submitting'
    });
    try {
      const response = await rpc('cad_submit', {
        ...recipe,
        ...parentReference(base),
        request_id
      }, 70000);
      if (alive.current && generation === epoch.current) accept(response.job);
    } catch (failure) {
      if (alive.current && generation === epoch.current) {
        setError(failure.message);
        setUncertain(!!failure.uncertain);
        if (!failure.uncertain) accept({
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
    const generation = epoch.current;
    try {
      const response = await rpc('cad_cancel', { request_id: selected });
      if (alive.current && generation === epoch.current) accept(response.job);
    } catch (failure) {
      if (alive.current && generation === epoch.current) setError(failure.message);
    }
  };
  const plan = async () => {
    const generation = epoch.current, version = draft.version.current;
    const reference = parentReference(base);
    setPlanning(true);setError('');setProposal(null);
    try {
      const response = base
        ? await rpc('cad_plan_changes', { ...reference, prompt }, 110000)
        : await rpc('cad_plan', { prompt }, 110000);
      if (!alive.current || generation !== epoch.current) return;
      if (draft.version.current !== version) { setError('The draft changed while planning. Request a new proposal.'); return; }
      setProposal({ recipe: response.proposal?.recipe || response.recipe, version, ...reference });
    } catch (failure) {
      if (alive.current && generation === epoch.current) setError(failure.message);
    } finally {
      if (alive.current && generation === epoch.current) setPlanning(false);
    }
  };
  const applyProposal = () => {
    if (!proposal || proposal.version !== draft.version.current || (proposal.base_request_id !== parentReference(base).base_request_id || proposal.base_fingerprint !== parentReference(base).base_fingerprint)) {
      setError('The draft or base revision changed. Request a new proposal.');setProposal(null);return;
    }
    setRecipe(proposal.recipe);setProposal(null);
  };
  const download = async (format) => {
    const generation = epoch.current;
    setExporting(format);
    setError('');
    try {
      const {
        artifact
      } = await rpc('cad_artifact', {
        request_id: selected,
        format
      });
      const bytes = await artifactBytes(artifact);
      if (!alive.current || generation !== epoch.current) return;
      const url = URL.createObjectURL(new Blob([bytes], {
        type: format === 'png' ? 'image/png' : format === 'blend' ? 'application/octet-stream' : format === 'glb' ? 'model/gltf-binary' : format === 'json' ? 'application/json' : 'model/stl'
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
    {(!connected || refreshing || error) && <PanelState compact kind={!connected ? 'offline' : error ? 'error' : 'loading'}
    title={!connected ? 'Core connection interrupted' : error ? 'Your attention is needed' : 'Syncing your workshop'}
    detail={!connected ? 'Saved builds remain in your project. History refreshes after reconnecting.' : error || 'Checking revisions and available tools.'}
    action={connected && !refreshing && (!busy || uncertain) ? refresh : undefined} actionLabel="Refresh history" />}
    <RevisionTools draft={draft} base={base} jobs={jobs} selected={selected} compare={compare} onCompare={setCompare} disabled={busy || planning} onNew={() => {setBase(null);setProposal(null);}} />
    {proposal && <section className="proposal-review" aria-label="Blueprint proposal review"><h4>Review your proposed changes</h4><p>Edits target the saved base. Applying replaces the current draft; it does not build or execute code.</p><RecipeComparison before={recipe} after={proposal.recipe} title="Proposed field changes" /><button disabled={busy || planning} onClick={applyProposal}>Apply to draft</button> <button onClick={() => setProposal(null)}>Discard proposal</button></section>}
    <div className="cad-layout">
      <aside className="cad-builder">
        <form onSubmit={build}>
          <span className="eyebrow">01 / BLUEPRINT</span>
          <div className="cad-shapes" role="group" aria-label="Shape">{shapes.map(({
              id,
              label,
              icon: Icon
            }) => <button type="button" key={id} className={recipe.shape === id ? 'selected' : ''} aria-pressed={recipe.shape === id} disabled={busy || planning} onClick={() => setRecipe((previous) => ({
              ...previous,
              shape: id,
              objects: id === 'scene' ? previous.objects || [newObject(0), newObject(1)] : null,
              engine: 'offline'
            }))}><Icon size={21} /><span>{label}</span></button>)}</div>
          <Field className="cad-field" label="Design name"><input value={recipe.name} required maxLength={60} disabled={busy || planning} onChange={(event) => setRecipe((previous) => ({
              ...previous,
              name: event.target.value
            }))} /></Field>
          {recipe.shape === 'scene' ? <><SceneEditor selected={objectIndex} onSelect={setObjectIndex} objects={recipe.objects} onChange={(objects) => setRecipe((previous) => ({
              ...previous,
              objects
            }))} disabled={busy || planning} /><label className="cad-field">Build engine<select value={recipe.engine || 'offline'} disabled={busy || planning} onChange={(event) => setRecipe((previous) => ({
                ...previous,
                engine: event.target.value
              }))}><option value="offline">Offline / STL / GLB</option><option value="blender" disabled={!capabilities.blender}>Blender / project + render{!capabilities.blender ? ' (not installed)' : ''}</option></select></label>{recipe.engine === 'blender' && <fieldset className="scene-presentation" disabled={busy || planning}><legend>Blender presentation / CPU only</legend>{[['camera',['isometric','top','front']],['lighting',['soft','studio','contrast']],['quality',['preview','standard']],['background',['dark','neutral']]].map(([key,options]) => <label className="cad-field" key={key}>{key}<select aria-label={`Render ${key}`} value={recipe.presentation?.[key] || defaults.presentation[key]} onChange={event=>setRecipe(previous=>({...previous,presentation:{...defaults.presentation,...previous.presentation,[key]:event.target.value}}))}>{options.map(value=><option key={value} value={value}>{value}</option>)}</select></label>)}</fieldset>}</> : <div className="cad-dimensions">{['width', 'depth', 'height', ...(recipe.shape !== 'box' ? ['thickness'] : [])].map((key) => <label className="cad-field" key={key}>{key === 'thickness' ? 'Wall thickness' : key[0].toUpperCase() + key.slice(1)}<div className="cad-number"><input aria-label={`${key} in millimetres`} type="number" min={key === 'thickness' ? .5 : 1} max={key === 'thickness' ? 100 : 1000} step="any" required value={recipe[key]} disabled={busy || planning} onChange={(event) => setRecipe((previous) => ({
                  ...previous,
                  [key]: event.target.value === '' ? '' : Number(event.target.value)
                }))} /><span>mm</span></div></label>)}</div>}
          <p className="cad-builder-note">{recipe.shape === 'scene' ? 'Compose parts, set their placement and choose a material for each.' : recipe.shape === 'enclosure' ? 'Open top, flat base and uniform walls.' : recipe.shape === 'bracket' ? 'One continuous solid with a base and upright.' : 'A closed rectangular solid, ready for refinement.'}</p>
          <button className="primary-button cad-build" type="submit" disabled={!connected || refreshing || busy || planning}>{busy ? <Loader2 size={16} className="cad-spinner" /> : <Box size={17} />}{busy ? 'Build in progress' : 'Build new revision'}</button>
          {busy && <button className="cad-cancel" type="button" onClick={cancel}><Square size={13} />Cancel build</button>}
        </form>
        <details className="cad-ai"><summary><Sparkles size={15} />AI blueprint<span>OPTIONAL</span></summary><p>Describe a supported solid, or propose edits to the selected saved revision. Review before applying.</p><textarea aria-label="Blueprint description" maxLength={2000} value={prompt} disabled={planning || busy} placeholder="An open enclosure, 80 × 60 × 30 mm, with 3 mm walls…" onChange={(event) => setPrompt(event.target.value)} /><button className="text-button" disabled={!connected || planning || busy || !prompt.trim()} onClick={plan}>{planning ? 'Proposing dimensions…' : 'Propose dimensions'}<Sparkles size={13} /></button></details>
<p className="cad-builder-note">{capabilities.kernel_reason || 'Holes, fillets, booleans and STEP require a validated engineering adapter. No kernel is enabled.'}</p>
        {legacyData && <button className="text-button" onClick={() => setLegacy(true)}>Open previous voice design</button>}
      </aside>
      <section className="cad-workbench" aria-label="Model and exports">
        <div className="cad-preview-top"><span className="eyebrow">02 / EXPLORE</span><button className="text-button" aria-pressed={wireframe} onClick={() => setWireframe((value) => !value)}><Layers3 size={14} />{wireframe ? 'Show solid' : 'Wireframe'}</button></div>
        <div className="draft-view-tools"><button aria-pressed={!draftView} onClick={() => setDraftView(false)}>Saved revision</button><button aria-pressed={draftView} onClick={() => setDraftView(true)}>Draft blockout</button></div>
        {draftView ? <DraftPreview recipe={recipe} selected={Math.min(objectIndex,(recipe.objects?.length || 1)-1)} onSelect={setObjectIndex} disabled={busy || planning} onMove={position => setRecipe(previous => ({...previous, objects:previous.objects.map((object,index) => index === Math.min(objectIndex,previous.objects.length-1) ? {...object,position} : object)}))} /> : <>
        <p className="saved-preview-label">Saved geometry / {job?.request_id?.slice(0, 8) || 'No built revision'}. Build to validate draft changes.</p>
        <div className={compare ? 'revision-visual-compare' : ''}>{compare && <div><h4>Comparison / {compare.slice(0, 8)}</h4><ModelPreview job={jobs.find(value => value.request_id === compare)} wireframe={wireframe} /></div>}<div>{compare && <h4>Selected / {job?.request_id?.slice(0,8)}</h4>}<ModelPreview job={job} wireframe={wireframe} selectedObject={objectIndex} onSelectObject={setObjectIndex} /></div></div>
        {compare && <RecipeComparison before={jobs.find(value => value.request_id === compare)?.recipe} after={job?.recipe} title="Saved revision comparison" />}</>}
        <JobLifetime job={job} connected={connected} onChange={async background => { try { const response = await rpc('cad_lifetime', { request_id: job.request_id, background }); accept(response.job); } catch (failure) { setError(failure.message); } }} /><JobStatus className="cad-status" title={draftView && !busy ? 'Unvalidated draft' : phases[job?.phase] || 'Ready to build'} subtitle={draftView ? 'Saved statistics and exports below belong to the last built revision.' : job?.state === 'succeeded' ? 'Revision saved to your project.' : 'Each build creates a separate revision.'} ready={!draftView && job?.state === 'succeeded'} busy={busy} />
        {job?.stats && <p className="saved-preview-label">Saved revision measurements / build the draft to update these.</p>}
        {job?.stats && <div className="cad-stats"><div><span>Dimensions</span><strong>{job.recipe.shape === 'scene' ? job.stats.bounds_mm[1].map((value, i) => (value - job.stats.bounds_mm[0][i]).toFixed(1)).join(' × ') : `${job.recipe.width} × ${job.recipe.depth} × ${job.recipe.height}`}<small> mm</small></strong></div><div><span>{job.recipe.shape === 'scene' ? 'Parts volume (sum)' : 'Volume'}</span><strong>{(job.stats.volume_mm3 / 1000).toFixed(2)}<small> cm³</small></strong></div><div><span>Mesh</span><strong>{job.stats.triangles}<small> triangles</small></strong></div><div><span>Topology</span><strong>{job.recipe.shape === 'scene' ? `${job.recipe.objects.length} closed parts` : 'Watertight'}</strong></div></div>}
        <div className="cad-export"><div><span className="eyebrow">03 / TAKE IT FURTHER</span><p>STL for fabrication · GLB for Blender and other 3D apps</p></div><div>{['stl', 'glb', 'json', ...(job?.artifacts?.blend ? ['blend', 'png'] : [])].map((format) => <button key={format} disabled={!connected || job?.state !== 'succeeded' || !!exporting} onClick={() => download(format)}>{exporting === format ? <Loader2 size={14} className="cad-spinner" /> : <Download size={14} />}{format === 'json' ? 'Recipe' : format.toUpperCase()}</button>)}</div></div>
      </section>
    </div>
    {job?.error && !error && <PanelState compact kind="error" title="Build stopped" detail={job.error} />}
    <RevisionHistory kind="cad" project={project} jobs={jobs} selected={selected} busy={busy} connected={connected} refreshing={refreshing} uncertain={uncertain} onRefresh={refresh} onSelect={(value) => {
      selectedRef.current = value.request_id;setSelected(value.request_id);if (value.recipe) resetRecipe(value.recipe);setBase(value.state === 'succeeded' ? value : null);setProposal(null);setObjectIndex(0);setCompare('');setError('');
    }} />
  </div>;
}
