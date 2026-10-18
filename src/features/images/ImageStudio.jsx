import React, { useEffect, useRef, useState } from 'react';
import { Sparkles, Image, SlidersHorizontal, Download, RefreshCw, Shuffle, Square, Loader2, ArrowUpRight, ShieldCheck } from 'lucide-react';
import useStore from '../../store';
import socket from '../../services/socket';
import { artifactBytes, mergeJob, pendingJob } from '../creative/client';
import { createImageClient, reconcileImageHistory } from '../../transport/imageClient.ts';
import PanelState from '../../app/PanelState';
import './images.css';
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
  connected
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
    }).catch(failure => {
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
    <div className="image-canvas-label"><span className="status-dot" /> {visible ? 'YOUR REVISION / PNG' : 'CANVAS / WAITING FOR YOUR IDEA'}</div>
    {visible ? <img src={preview.url} alt={job.recipe.name} onError={() => setError('The saved PNG could not be displayed.')} /> : <div className="image-empty"><div className="image-aperture"><Image size={42} strokeWidth={1} /></div><span className="eyebrow">A SPACE FOR WHAT COMES NEXT</span><h3>Your imagination,<br /><span>given light.</span></h3><p>{error || (pendingJob(job) ? 'Your worker is running. You can cancel at any time.' : 'Describe a visual. Choose its frame. Generate when your local model is connected.')}</p><div className="image-empty-mark">01 — CONCEIVE / 02 — EXPLORE / 03 — KEEP</div></div>}
    {job?.stats?.backend === 'verification_fixture' && <div className="image-fixture">VERIFICATION FIXTURE · NO IMAGE MODEL RAN</div>}
    {visible && error && <p role="alert" className="image-preview-error">{error}</p>}
  </div>;
}
export default function ImageStudio() {
  const project = useStore(state => state.currentProject);
  return <ImageSession key={project} project={project} />;
}
function ImageSession({ project }) {
  const connected = useStore(state => state.backendConnected);
  const transport = useRef(null);
  const rpc = (...args) => transport.current.call(...args);
  const [refreshing, setRefreshing] = useState(true);
  const latestRefresh = useRef(0);
  const historyVersion = useRef(0), jobVersions = useRef(new Map());
  const [uncertain, setUncertain] = useState(false);
  const [recipe, setRecipe] = useState(defaults),
    [jobs, setJobs] = useState([]),
    [selected, setSelected] = useState(null),
    [capability, setCapability] = useState(null),
    [error, setError] = useState(''),
    [exporting, setExporting] = useState('');
  const current = useRef(null),
    alive = useRef(false),
    epoch = useRef(0);
  const job = jobs.find(value => value.request_id === selected),
    busy = pendingJob(job);
  const patch = value => setRecipe(previous => ({
    ...previous,
    ...value
  }));
  const accept = value => {
    if (!alive.current || value.project !== useStore.getState().currentProject) return;
    jobVersions.current.set(value.request_id, ++historyVersion.current);
    setJobs(previous => [mergeJob(previous.find(item => item.request_id === value.request_id), value), ...previous.filter(item => item.request_id !== value.request_id)].slice(0, 12));
    if (!current.current) {
      current.current = value.request_id;
      setSelected(value.request_id);
    }
  };
  const refresh = async () => {
    const generation = epoch.current, refreshId = ++latestRefresh.current, version = historyVersion.current;
    setRefreshing(true);
    try {
      const response = await rpc('image_list', {});
      if (!alive.current || generation !== epoch.current || refreshId !== latestRefresh.current) return;
      setError('');
      setCapability(response.capabilities);
      setUncertain(false);
      setJobs(previous => reconcileImageHistory(previous, response.jobs, new Set(
        [...jobVersions.current].filter(([, updated]) => updated > version).map(([id]) => id)
      )));
      if (!current.current && response.jobs[0]) {
        current.current = response.jobs[0].request_id;
        setSelected(current.current);
        setRecipe(response.jobs[0].recipe);
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
    alive.current = true;
    current.current = null;
    setRecipe(defaults);
    setJobs([]);
    setSelected(null);
    setCapability(null);
    setError('');
    setExporting('');
    const update = value => accept(value);
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
  }, [project]);
  const submit = async event => {
    event.preventDefault();
    setError('');
    setUncertain(false);
    const generation = epoch.current,
      request_id = crypto.randomUUID();
    current.current = request_id;
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
  const download = async format => {
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
    <div className="image-intro"><div><span className="eyebrow">INARA / IMAGE ATELIER</span><h3>Imagine beyond<br /><span>the ordinary.</span></h3><p>A focused space for your next visual direction.</p></div><div className={`image-backend-badge ${capability?.available ? 'available' : ''}`}><span className="status-dot" />{capability?.available ? 'LOCAL / ON DEMAND' : 'MODEL SETUP LATER'}</div></div>
    {(!connected || refreshing || error) && <PanelState compact
      kind={!connected ? 'offline' : error ? 'error' : 'loading'}
      title={!connected ? 'Core connection interrupted' : error ? 'Your attention is needed' : 'Syncing your atelier'}
      detail={!connected ? 'Your saved revisions are safe. History refreshes when the core reconnects.' : error || 'Checking saved revisions and local model availability.'}
      action={connected && !refreshing ? refresh : undefined} actionLabel="Refresh history" />}
    <div className="image-layout"><form className="image-director" onSubmit={submit}>
      <div className="image-section-title"><span className="eyebrow">01 / ART DIRECTION</span><SlidersHorizontal size={15} /></div>
      <label className="image-field">Visual name<input value={recipe.name} required maxLength={60} disabled={busy} onChange={event => patch({
            name: event.target.value
          })} /></label>
      <label className="image-field">Your prompt<textarea value={recipe.prompt} minLength={3} maxLength={2000} required disabled={busy} placeholder="An architectural pavilion floating above a misty lake, soft dawn light, warm timber and glass…" onChange={event => patch({
            prompt: event.target.value
          })} /><small>{recipe.prompt.length}/2000 · Describe subject, materials, light and mood.</small></label>
      <div className="image-field"><span>Frame</span><div className="image-frames" role="group" aria-label="Image frame">{frames.map(([name, width, height]) => <button key={name} type="button" disabled={busy} aria-pressed={recipe.width === width && recipe.height === height} onClick={() => patch({
              width,
              height
            })}><span className={`frame-icon ${width > height ? 'wide' : width < height ? 'tall' : ''}`} />{name}<small>{width} × {height}</small></button>)}</div></div>
      <details className="image-tuning"><summary>Fine-tune your direction<span>SEED / QUALITY</span></summary><label className="image-field">Avoid in the image<textarea className="negative-prompt" value={recipe.negative_prompt} maxLength={1000} disabled={busy} onChange={event => patch({
              negative_prompt: event.target.value
            })} /></label><div className="image-tuning-grid"><label className="image-field">Steps<input type="number" aria-label="Generation steps" min={1} max={40} required value={recipe.steps} disabled={busy} onChange={event => patch({
                steps: event.target.value === '' ? '' : Number(event.target.value)
              })} /></label><label className="image-field">Guidance<input type="number" min={1} max={15} step=".1" required value={recipe.guidance} disabled={busy} onChange={event => patch({
                guidance: event.target.value === '' ? '' : Number(event.target.value)
              })} /></label></div><label className="image-field">Seed<div className="image-seed"><input type="number" min={0} max={2147483647} required value={recipe.seed} disabled={busy} onChange={event => patch({
                seed: event.target.value === '' ? '' : Number(event.target.value)
              })} /><button type="button" aria-label="Randomize seed" disabled={busy} onClick={() => patch({
                seed: crypto.getRandomValues(new Uint32Array(1))[0] % 2147483648
              })}><Shuffle size={16} /></button></div></label><p>Same settings help reproduce a direction. Larger frames and more steps take more memory and time.</p></details>
      <button className="primary-button image-generate" disabled={!connected || refreshing || !capability?.available || busy} type="submit">{busy ? <Loader2 size={17} className="image-spin" /> : <Sparkles size={17} />} {busy ? 'Generation in progress' : 'Generate new revision'}<ArrowUpRight size={16} /></button>
      {busy && <button className="image-cancel" type="button" onClick={cancel}><Square size={12} />Cancel generation</button>}
      <div className="image-availability" role="status"><ShieldCheck size={17} /><div><strong>{capability?.available ? capability.model || 'Local worker ready' : 'Your canvas is ready'}</strong><p>{!connected ? 'Connect to the core to check model availability.' : capability?.reason || 'Checking local model availability…'}</p><small>Models load only for a generation. Setup can wait.</small></div></div>
    </form><section className="image-workbench" aria-label="Image preview and exports"><div className="image-section-title"><span className="eyebrow">02 / EXPLORE</span><span>{recipe.width} × {recipe.height} / PNG</span></div><Preview job={job} connected={connected} /><div className="image-result-status" role="status"><span className="status-dot" /><div><strong>{phases[job?.phase] || 'Waiting for a direction'}</strong><span>{job?.stats ? `${job.stats.width} × ${job.stats.height} / Seed ${job.stats.seed} / ${job.stats.device.toUpperCase()}` : 'One image. A separate revision. Your project.'}</span></div></div><div className="image-export"><div><span className="eyebrow">03 / KEEP YOUR WORK</span><p>PNG image + prompt, settings and provenance</p></div><div>{['png', 'json'].map(format => <button key={format} disabled={!connected || job?.state !== 'succeeded' || !!exporting} onClick={() => download(format)}>{exporting === format ? <Loader2 size={14} className="image-spin" /> : <Download size={14} />} {format === 'json' ? 'Recipe' : 'PNG'}</button>)}</div></div></section></div>
    {job?.error && !error && <PanelState compact kind="error" title="Revision stopped" detail={job.error} />}
    <section className="image-history"><div className="image-section-title"><span className="eyebrow">RECENT REVISIONS / {project}</span><button className="text-button" aria-label="Refresh image history" disabled={!connected || refreshing || (busy && !uncertain)} onClick={refresh}><RefreshCw size={14} /></button></div><div className="image-history-list">{jobs.length ? jobs.map(value => <button key={value.request_id} disabled={busy} className={value.request_id === selected ? 'selected' : ''} onClick={() => {
          current.current = value.request_id;
          setSelected(value.request_id);
          if (value.recipe) setRecipe(value.recipe);
          setError('');
        }}><Image size={20} /><span>{value.recipe?.name || 'New visual'}<small>{value.recipe?.width} × {value.recipe?.height} / {value.request_id.slice(0, 8)}</small></span><em>{value.state}</em></button>) : <p>Your saved image revisions will appear here. Nothing has been generated yet.</p>}</div></section>
  </div>;
}
