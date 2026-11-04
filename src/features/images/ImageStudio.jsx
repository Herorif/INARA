import React, { useEffect, useRef, useState } from 'react';
import { Image, ImagePlus, Download, Shuffle, Square, Loader2, ShieldCheck } from 'lucide-react';
import useStore from '../../store';
import socket from '../../services/socket';
import { artifactBytes, mergeJob, pendingJob } from '../creative/client';
import { createImageClient } from '../../transport/imageClient.ts';
import { reconcileHistory } from '../../transport/history.ts';
import PanelState from '../../app/PanelState';
import RevisionHistory from '../../app/RevisionHistory';
import JobStatus from '../../app/JobStatus';
import JobLifetime from '../../app/JobLifetime';
import Field from '../../app/Field';
import StatusChip from '../../shared/ui/StatusChip';
import EmptyState from '../../shared/ui/EmptyState';
import './images.css';
import { useRecipeDraft } from '../creative/useRecipeDraft';
import { parentReference } from '../creative/draft';
import RevisionTools, { RecipeComparison } from '../creative/RevisionTools';
import HandoffReview, {ReferenceNotice} from '../creative/HandoffReview';
const defaults = {
  name: 'Untitled visual',
  prompt: '',
  negative_prompt: '',
  width: 512,
  height: 512,
  steps: 24,
  seed: 1234,
  guidance: 7
};
const frames = [['Square', 512, 512], ['Landscape', 768, 512], ['Portrait', 512, 768], ['Large square', 1024, 1024]];
const phases = {
  submitting: 'Sending your request',
  awaiting_approval: 'Waiting for approval',
  queued: 'Preparing your worker',
  building: 'Starting the worker',
  loading: 'Loading the local model',
  generating: 'Bringing your idea into focus',
  validating: 'Checking your image',
  saving: 'Saving this revision',
  ready: 'Ready to explore',
  stopped: 'Generation stopped',
  cancelled: 'Generation cancelled',
  interrupted: 'Generation interrupted'
};
function Preview({
  job,
  connected,
  available = true
}) {
  const [preview, setPreview] = useState(null),
    [error, setError] = useState('');
  useEffect(() => {
    const client = createImageClient(socket);
    let active = true,
      url;
    setPreview(null);
    setError('');
    if (job?.state === 'succeeded' && connected) client.call('image_artifact', {
      request_id: job.request_id,
      format: 'png'
    }).then(async ({
      artifact
    }) => {
      const bytes = await artifactBytes(artifact);
      if (!active) return;
      url = URL.createObjectURL(new Blob([bytes], {
        type: 'image/png'
      }));
      setPreview({
        id: job.request_id,
        url
      });
    }).catch((failure) => {
      if (active) setError(failure.message);
    });
    return () => {
      active = false;
      client.dispose();
      if (url) URL.revokeObjectURL(url);
    };
  }, [job?.request_id, job?.state, connected]);
  const visible = preview?.id === job?.request_id && job?.state === 'succeeded';
  return <div className="image-canvas" data-image-loaded={!!visible}>
    <div className="image-canvas-label hud-label"><span className={`status-dot ${visible ? 'status-dot--ok' : ''}`} aria-hidden="true" />{visible ? 'Saved revision / PNG' : 'Canvas'}</div>
    {visible ? <img src={preview.url} alt={job.recipe.name} onError={() => setError('The saved PNG could not be displayed.')} />
      : error ? <EmptyState className="image-empty" icon={<Image strokeWidth={1.5} />} title="Preview unavailable" body={error} />
      : pendingJob(job) ? <EmptyState className="image-empty" icon={<Loader2 className="image-spin" strokeWidth={1.5} />} title="Generating" body="The worker is running. You can cancel at any time." />
      : !available ? <EmptyState className="image-empty" icon={<Image strokeWidth={1.5} />} title="No image model installed" body="Set up a local image model to generate images." />
      : <EmptyState className="image-empty" icon={<Image strokeWidth={1.5} />} title="No image yet" body="Describe a visual, choose a frame and generate a revision." />}
    {job?.stats?.backend === 'verification_fixture' && <div className="image-fixture hud-label">Verification fixture / NO IMAGE MODEL RAN</div>}
    {visible && error && <p role="alert" className="image-preview-error">{error}</p>}
  </div>;
}
export default function ImageStudio() {
  const project = useStore((state) => state.currentProject);
  return <ImageSession key={project} project={project} />;
}
function ImageSession({ project }) {
  const connected = useStore((state) => state.backendConnected);
  const transport = useRef(null);
  const rpc = (...args) => transport.current.call(...args);
  const [refreshing, setRefreshing] = useState(true);
  const latestRefresh = useRef(0);
  const historyVersion = useRef(0),jobVersions = useRef(new Map());
  const [uncertain, setUncertain] = useState(false);
  const draft = useRecipeDraft(defaults);
  const {recipe, setRecipe, resetRecipe} = draft;
  const [base, setBase] = useState(null), [compare, setCompare] = useState(''), [gallery, setGallery] = useState(false);
  const [reference,setReference] = useState(null);
  const [jobs, setJobs] = useState([]),
    [selected, setSelected] = useState(null),
    [capability, setCapability] = useState(null),
    [error, setError] = useState(''),
    [exporting, setExporting] = useState('');
  const current = useRef(null),
    alive = useRef(false),
    epoch = useRef(0);
  const restoreRecipe = useRef(true), pendingBranch = useRef(null);
  const job = jobs.find((value) => value.request_id === selected),
    busy = pendingJob(job);
  const patch = (value) => setRecipe((previous) => ({
    ...previous,
    ...value
  }));
  const accept = (value) => {
    if (!alive.current || value.project !== useStore.getState().currentProject) return;
    useStore.getState().recordActivity('image', value);
    if (value.state === 'succeeded' && value.request_id === pendingBranch.current) {setBase(value);pendingBranch.current=null;}
    jobVersions.current.set(value.request_id, ++historyVersion.current);
    setJobs((previous) => [mergeJob(previous.find((item) => item.request_id === value.request_id), value), ...previous.filter((item) => item.request_id !== value.request_id)].slice(0, 12));
    if (!current.current) {
      current.current = value.request_id;
      setSelected(value.request_id);
    }
  };
  const refresh = async () => {
    const generation = epoch.current,refreshId = ++latestRefresh.current,version = historyVersion.current;
    setRefreshing(true);
    try {
      const response = await rpc('image_list', {});
      if (!alive.current || generation !== epoch.current || refreshId !== latestRefresh.current) return;
      setError('');
      setCapability(response.capabilities);
      setUncertain(false);
      setJobs((previous) => reconcileHistory(previous, response.jobs, new Set(
        [...jobVersions.current].filter(([, updated]) => updated > version).map(([id]) => id)
      )));
      const completed=response.jobs.find(value=>value.request_id===pendingBranch.current && value.state==='succeeded');
      if(completed){setBase(completed);pendingBranch.current=null;}
      if (restoreRecipe.current) {
        const restored = response.jobs.find(value => value.request_id === current.current) || (!current.current ? response.jobs[0] : null);
        if (restored) { current.current = restored.request_id; setSelected(restored.request_id); resetRecipe(restored.recipe); setReference(restored.reference || null); setBase(restored.state === 'succeeded' ? restored : null); }
        else if (current.current) setError('That revision is outside recent history. Select another saved revision.');
        restoreRecipe.current = false;
      }
    } catch (failure) {
      if (alive.current && generation === epoch.current && refreshId === latestRefresh.current) setError(failure.message);
    } finally {
      if (alive.current && generation === epoch.current && refreshId === latestRefresh.current) setRefreshing(false);
    }
  };
  useEffect(() => {
    const client = createImageClient(socket);
    transport.current = client;
    epoch.current++;
    restoreRecipe.current = true;
    alive.current = true;
    const selection = useStore.getState().studioSelection;
    current.current = selection?.feature === 'image' && selection.project === project ? selection.requestId : null;
    resetRecipe(defaults);setBase(null);setCompare('');setGallery(false);
    setReference(null);
    setJobs([]);
    setSelected(current.current);
    setCapability(null);
    setError('');
    setExporting('');
    const update = (value) => accept(value);
    client.on('image_job', update);
    client.on('connect', refresh);
    client.on('disconnect', () => {
      epoch.current++;
      setRefreshing(false);
      setExporting('');
      setUncertain(true);
    });
    if (socket.connected) refresh();
    return () => {
      alive.current = false;
      client.dispose();
      // Server owns job cancellation; local scope drops ACKs immediately.
      if (socket.connected) socket.emit('image_close', {});
      if (useStore.getState().confirmationRequest?.tool === 'generate_image') useStore.setState({
        confirmationRequest: null
      });
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps -- subscribes once per mount (keyed by project); refresh and resetRecipe only use refs and stable setters
  }, [project]);
  const submit = async (event) => {
    event.preventDefault();
    setError('');
    setUncertain(false);
    const generation = epoch.current,
      request_id = crypto.randomUUID();
    current.current = request_id;pendingBranch.current=request_id;
    setSelected(request_id);
    accept({
      request_id,
      project,
      recipe,
      state: 'submitting',
      phase: 'submitting'
    });
    try {
      const response = await rpc('image_submit', {
        ...recipe,
        ...parentReference(base),
        reference,
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
      const response = await rpc('image_cancel', {
        request_id: selected
      });
      if (alive.current && generation === epoch.current) accept(response.job);
    } catch (failure) {
      if (alive.current && generation === epoch.current) setError(failure.message);
    }
  };
  const download = async (format) => {
    const generation = epoch.current;
    setExporting(format);
    setError('');
    try {
      const {
        artifact
      } = await rpc('image_artifact', {
        request_id: selected,
        format
      });
      const bytes = await artifactBytes(artifact);
      if (!alive.current || generation !== epoch.current) return;
      const url = URL.createObjectURL(new Blob([bytes], {
        type: format === 'png' ? 'image/png' : 'application/json'
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
  return <div className="image-studio">
    <div className="image-intro"><div><h3>Image generation</h3><p>Local model, loaded only for a generation. Each one saves a new revision in {project}.</p></div><StatusChip className={`image-backend-badge ${capability?.available ? 'available' : ''}`} tone={capability?.available ? 'ok' : 'idle'}>{capability?.available ? 'Local model ready' : 'No model installed'}</StatusChip></div>
    {(!connected || refreshing || error) && <PanelState compact
    kind={!connected ? 'offline' : error ? 'error' : 'loading'}
    title={!connected ? 'Core offline' : error ? 'Request failed' : 'Loading history'}
    detail={!connected ? 'Your saved revisions are safe. History refreshes when the core reconnects.' : error || 'Checking saved revisions and local model availability.'}
    action={connected && !refreshing ? refresh : undefined} actionLabel="Refresh history" />}
    <RevisionTools draft={draft} base={base} jobs={jobs} selected={selected} compare={compare} onCompare={setCompare} disabled={busy} onNew={() => setBase(null)} />
    <HandoffReview destination="image" project={project} version={draft.version} disabled={busy || refreshing} onApply={value=>{patch({name:value.name,prompt:value.prompt});setReference(value.reference);}}/>
    <ReferenceNotice reference={reference} disabled={busy} onClear={()=>setReference(null)}/>
    <div className="image-layout"><form className="image-director" onSubmit={submit}>
      <div className="image-section-title"><span className="hud-label">Prompt</span></div>
      <Field className="image-field" label="Visual name"><input value={recipe.name} required maxLength={60} disabled={busy} onChange={(event) => patch({
            name: event.target.value
          })} /></Field>
      <Field className="image-field" label="Prompt" hint={`${recipe.prompt.length}/2000. Describe subject, materials, light and mood.`}><textarea value={recipe.prompt} minLength={3} maxLength={2000} required disabled={busy} placeholder="An architectural pavilion floating above a misty lake, soft dawn light, warm timber and glass…" onChange={(event) => patch({
            prompt: event.target.value
          })} /></Field>
      <div className="image-field panel-field"><span className="panel-field__label">Frame</span><div className="image-frames" role="group" aria-label="Image frame">{frames.map(([name, width, height]) => <button key={name} type="button" disabled={busy} aria-pressed={recipe.width === width && recipe.height === height} onClick={() => patch({
              width,
              height
            })}><span className={`frame-icon ${width > height ? 'wide' : width < height ? 'tall' : ''}`} aria-hidden="true" />{name}<small>{width} × {height}</small></button>)}</div></div>
      <details className="image-tuning"><summary>Advanced settings<span className="hud-label">Seed / quality</span></summary><Field className="image-field" label="Avoid in the image"><textarea className="negative-prompt" value={recipe.negative_prompt} maxLength={1000} disabled={busy} onChange={(event) => patch({
              negative_prompt: event.target.value
            })} /></Field><div className="image-tuning-grid"><Field className="image-field" label="Steps"><input type="number" aria-label="Generation steps" min={1} max={40} required value={recipe.steps} disabled={busy} onChange={(event) => patch({
                steps: event.target.value === '' ? '' : Number(event.target.value)
              })} /></Field><Field className="image-field" label="Guidance"><input type="number" min={1} max={15} step=".1" required value={recipe.guidance} disabled={busy} onChange={(event) => patch({
                guidance: event.target.value === '' ? '' : Number(event.target.value)
              })} /></Field></div><Field className="image-field" label="Seed"><div className="image-seed"><input type="number" min={0} max={2147483647} required value={recipe.seed} disabled={busy} onChange={(event) => patch({
                seed: event.target.value === '' ? '' : Number(event.target.value)
              })} /><button type="button" className="btn btn--secondary btn--icon" aria-label="Randomize seed" title="Randomize seed" disabled={busy} onClick={() => patch({
                seed: crypto.getRandomValues(new Uint32Array(1))[0] % 2147483648
              })}><Shuffle size={16} aria-hidden="true" /></button></div></Field><p>Same settings help reproduce a direction. Larger frames and more steps take more memory and time.</p></details>
      <button className="btn btn--primary image-generate" disabled={!connected || refreshing || !capability?.available || busy} type="submit">{busy ? <Loader2 size={16} className="image-spin" aria-hidden="true" /> : <ImagePlus size={16} aria-hidden="true" />}{busy ? 'Generation in progress' : 'Generate new revision'}</button>
      {busy && <button className="btn btn--danger image-cancel" type="button" onClick={cancel}><Square size={12} aria-hidden="true" />Cancel generation</button>}
      <div className="image-availability hud-panel" role="status"><ShieldCheck size={16} aria-hidden="true" /><div><strong>{capability?.available ? capability.model || 'Local worker ready' : 'Not configured'}</strong><p>{!connected ? 'Connect to the core to check model availability.' : capability?.reason || 'Checking local model availability…'}</p><small>Models load only for a generation.</small></div></div>
    </form><section className="image-workbench" aria-label="Image preview and exports"><div className="image-section-title"><span className="hud-label">Preview</span><span className="image-size">{recipe.width} × {recipe.height} / PNG</span></div><div className={compare ? 'revision-visual-compare' : ''}>{compare && <div><h4 className="hud-label">Comparison / {compare.slice(0,8)}</h4><Preview job={jobs.find(value => value.request_id === compare)} connected={connected} /></div>}<div>{compare && <h4 className="hud-label">Selected / {job?.request_id?.slice(0,8)}</h4>}<Preview job={job} connected={connected} available={!!capability?.available || refreshing || !connected} /></div></div>{compare && <RecipeComparison before={jobs.find(value => value.request_id === compare)?.recipe} after={job?.recipe} title="Saved image recipe comparison" />}<JobLifetime job={job} connected={connected} onChange={async background => { try { const response = await rpc('image_lifetime', { request_id: job.request_id, background }); accept(response.job); } catch (failure) { setError(failure.message); } }} /><JobStatus className="image-result-status" title={phases[job?.phase] || 'Waiting for a direction'} subtitle={job?.stats ? `${job.stats.width} × ${job.stats.height} / Seed ${job.stats.seed} / ${job.stats.device.toUpperCase()}` : 'Each generation saves a separate revision.'} ready={job?.state === 'succeeded'} busy={busy} /><div className="image-export"><div><span className="hud-label">Export</span><p>PNG image, plus a recipe with prompt, settings and provenance.</p></div><div>{['png', 'json'].map((format) => <button type="button" className="btn btn--secondary btn--sm" key={format} disabled={!connected || job?.state !== 'succeeded' || !!exporting} onClick={() => download(format)}>{exporting === format ? <Loader2 size={14} className="image-spin" aria-hidden="true" /> : <Download size={14} aria-hidden="true" />}{format === 'json' ? 'Recipe' : 'PNG'}</button>)}</div></div></section></div>
    {job?.error && !error && <PanelState compact kind="error" title="Revision stopped" detail={job.error} />}
    <details className="image-gallery" open={gallery} onToggle={event => setGallery(event.currentTarget.open)}><summary>Gallery <span className="hud-label">Last four saved images</span></summary>{gallery && <div className="image-gallery-grid">{jobs.filter(value => value.state === 'succeeded').slice(0,4).map(value => <article className="hud-panel" key={value.request_id}><Preview job={value} connected={connected} /><button type="button" className="btn btn--ghost btn--sm" disabled={busy} onClick={() => {current.current=value.request_id;setSelected(value.request_id);resetRecipe(value.recipe);setReference(value.reference || null);setBase(value);setCompare('');}}>Reuse recipe / {value.request_id.slice(0,8)}</button></article>)}</div>}</details>
    <RevisionHistory kind="image" project={project} jobs={jobs} selected={selected} busy={busy} connected={connected} refreshing={refreshing} uncertain={uncertain} onRefresh={refresh} onSelect={(value) => {
      current.current = value.request_id;setSelected(value.request_id);if (value.recipe) resetRecipe(value.recipe);setReference(value.reference || null);setBase(value.state === 'succeeded' ? value : null);setCompare('');setError('');
    }} />
  </div>;
}
