import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowDown, ArrowUp, Pencil, Play, Plus, Repeat, Trash2, X } from 'lucide-react';
import socket from '../../services/socket';
import PanelState from '../../app/PanelState';
import StatusChip from '../../shared/ui/StatusChip';
import EmptyState from '../../shared/ui/EmptyState';
import { Switch } from '../calls/controls';
import { createRoutinesClient } from './routinesClient';
import {
  DAY_OPTIONS, DELETE_PROMPT, EMPTY_COPY, MAX_STEPS, MINUTE_OPTIONS, NAME_LIMIT, PAGE_DESCRIPTION, PAGE_TITLE, REPEAT_OPTIONS,
  SAY_LIMIT, SIGNAL_OPTIONS, TRIGGER_TYPES, addStep, argumentHint, editorFields, moveStep, outcomeLine, removeStep,
  routinesFailureMessage, stepCount, stepTools, toolTitle, triggerSummary, updateStep, validateEditor, withRoutine, withoutRoutine,
} from './routinesModel';
import './routines.css';

/** One step in the editor: tool, JSON arguments (checked against the tool's schema), a line to say. */
function StepEditor({ step, index, count, tools, error, onChange, onMove, onRemove, prefix }) {
  const id = `${prefix}-step-${step.key}`;
  const tool = tools.find(item => item.name === step.tool);
  const known = !step.tool || tool;
  return <li className="routine-step" data-step={step.key}>
    <div className="routine-step__head">
      <span className="routine-step__number" aria-hidden="true">{index + 1}</span>
      <div className="routine-field routine-field--tool">
        <label htmlFor={`${id}-tool`} className="routine-label">{`Step ${index + 1} tool`}</label>
        <select id={`${id}-tool`} value={step.tool} aria-invalid={!!error('tool')} aria-describedby={`${id}-tool-note`}
          onChange={event => onChange({ tool: event.target.value })}>
          <option value="">Choose a tool…</option>
          {!known && <option value={step.tool}>{`${step.tool} (not available)`}</option>}
          {tools.map(item => <option key={item.name} value={item.name}>{toolTitle(item.name)}</option>)}
        </select>
        <p id={`${id}-tool-note`} className={error('tool') ? 'routine-error' : 'routine-hint'}>{error('tool') || tool?.description || ''}</p>
      </div>
      <div className="routine-step__actions" role="group" aria-label={`Move or remove step ${index + 1}`}>
        <button type="button" className="btn btn--ghost btn--sm btn--icon" data-move="up" aria-label={`Move step ${index + 1} up`} disabled={index === 0} onClick={() => onMove(-1)}>
          <ArrowUp size={14} aria-hidden="true" /></button>
        <button type="button" className="btn btn--ghost btn--sm btn--icon" data-move="down" aria-label={`Move step ${index + 1} down`} disabled={index === count - 1} onClick={() => onMove(1)}>
          <ArrowDown size={14} aria-hidden="true" /></button>
        <button type="button" className="btn btn--ghost btn--sm btn--icon routine-row__delete" aria-label={`Remove step ${index + 1}`} disabled={count <= 1} onClick={onRemove}>
          <X size={14} aria-hidden="true" /></button>
      </div>
    </div>
    <div className="routine-step__body">
      <div className="routine-field routine-field--args">
        <label htmlFor={`${id}-args`} className="routine-label">Arguments (JSON)</label>
        <textarea id={`${id}-args`} rows={4} spellCheck={false} autoComplete="off" placeholder="{}" value={step.argsText}
          aria-invalid={!!error('args')} aria-describedby={`${id}-args-note`}
          onChange={event => onChange({ argsText: event.target.value })} />
        <p id={`${id}-args-note`} className={error('args') ? 'routine-error' : 'routine-hint'}>{error('args') || (tool ? argumentHint(tool) : '')}</p>
      </div>
      <div className="routine-field routine-field--say">
        <label htmlFor={`${id}-say`} className="routine-label">JARVIS says after it (optional)</label>
        <input id={`${id}-say`} type="text" autoComplete="off" maxLength={SAY_LIMIT + 20} value={step.say}
          aria-invalid={!!error('say')} aria-describedby={error('say') ? `${id}-say-error` : undefined}
          onChange={event => onChange({ say: event.target.value })} />
        {error('say') && <p id={`${id}-say-error`} className="routine-error">{error('say')}</p>}
      </div>
    </div>
  </li>;
}

/** Name, trigger and steps. Escape cancels; Save checks everything the core will check. */
function RoutineEditor({ routine, tools, busy, serverError, onSave, onCancel }) {
  const [fields, setFields] = useState(() => editorFields(routine));
  const [tried, setTried] = useState(false);
  const nameRef = useRef(null);
  const stepsRef = useRef(null);
  const prefix = `routine-edit-${routine?.id || 'new'}`;
  const choices = useMemo(() => stepTools(tools), [tools]);
  const checked = validateEditor(fields, choices);
  useEffect(() => { nameRef.current?.focus(); }, []);
  const set = changes => setFields(current => ({ ...current, ...changes }));
  const error = key => (tried ? checked.errors[key] || '' : '');
  const stepError = step => key => error(`step-${step.key}-${key}`);
  const submit = event => {
    event.preventDefault();
    setTried(true);
    if (checked.ok) onSave(checked.value);
  };
  const move = (index, delta) => {
    const key = fields.steps[index].key;
    set({ steps: moveStep(fields.steps, index, delta) });
    requestAnimationFrame(() => {
      const row = stepsRef.current?.querySelector(`[data-step="${key}"]`);
      // Keep focus on the moved step: the same arrow, or the other one at the top or bottom.
      const same = row?.querySelector(`[data-move="${delta < 0 ? 'up' : 'down'}"]`);
      const other = row?.querySelector(`[data-move="${delta < 0 ? 'down' : 'up'}"]`);
      (same && !same.disabled ? same : other && !other.disabled ? other : row?.querySelector('select'))?.focus();
    });
  };
  const add = () => {
    const steps = addStep(fields.steps);
    set({ steps });
    const key = steps[steps.length - 1].key;
    requestAnimationFrame(() => stepsRef.current?.querySelector(`[data-step="${key}"] select`)?.focus());
  };
  const remove = index => {
    set({ steps: removeStep(fields.steps, index) });
    requestAnimationFrame(() => stepsRef.current?.querySelector('select')?.focus());
  };
  const title = routine ? `Edit ${routine.name}` : 'New routine';
  return <form className="routine-editor hud-panel" aria-label={title} onSubmit={submit} noValidate
    onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); onCancel(); } }}>
    <h2 className="routine-editor__title">{title}</h2>
    <div className="routine-editor__row">
      <div className="routine-field routine-field--name">
        <label htmlFor={`${prefix}-name`} className="routine-label">Name</label>
        <input ref={nameRef} id={`${prefix}-name`} type="text" autoComplete="off" maxLength={NAME_LIMIT + 20} value={fields.name}
          aria-invalid={!!error('name')} aria-describedby={error('name') ? `${prefix}-name-error` : undefined}
          onChange={event => set({ name: event.target.value })} />
        {error('name') && <p id={`${prefix}-name-error`} className="routine-error">{error('name')}</p>}
      </div>
      <div className="routine-field routine-field--type">
        <label htmlFor={`${prefix}-type`} className="routine-label">Runs</label>
        <select id={`${prefix}-type`} value={fields.type} onChange={event => set({ type: event.target.value })}>
          {TRIGGER_TYPES.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
        </select>
      </div>
    </div>

    {fields.type === 'phrase' && <div className="routine-field">
      <label htmlFor={`${prefix}-phrases`} className="routine-label">Phrases</label>
      <input id={`${prefix}-phrases`} type="text" autoComplete="off" spellCheck={false} placeholder="movie time, masa wayang" value={fields.phrases}
        aria-invalid={!!error('phrases')} aria-describedby={`${prefix}-phrases-note`}
        onChange={event => set({ phrases: event.target.value })} />
      <p id={`${prefix}-phrases-note`} className={error('phrases') ? 'routine-error' : 'routine-hint'}>
        {error('phrases') || 'Separate phrases with commas. Say one on its own and JARVIS runs this routine instead of answering.'}</p>
    </div>}

    {fields.type === 'schedule' && <div className="routine-editor__row">
      <div className="routine-field routine-field--time">
        <label htmlFor={`${prefix}-at`} className="routine-label">Time</label>
        <input id={`${prefix}-at`} type="time" value={fields.at} aria-invalid={!!error('at')}
          aria-describedby={error('at') ? `${prefix}-at-error` : undefined} onChange={event => set({ at: event.target.value })} />
        {error('at') && <p id={`${prefix}-at-error`} className="routine-error">{error('at')}</p>}
      </div>
      <div className="routine-field routine-field--repeat">
        <label htmlFor={`${prefix}-repeat`} className="routine-label">Repeats</label>
        <select id={`${prefix}-repeat`} value={fields.repeat} onChange={event => set({ repeat: event.target.value })}>
          {REPEAT_OPTIONS.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
        </select>
      </div>
      {fields.repeat === 'weekly' && <div className="routine-field routine-field--day">
        <label htmlFor={`${prefix}-day`} className="routine-label">Day</label>
        <select id={`${prefix}-day`} value={fields.day} onChange={event => set({ day: event.target.value })}>
          {DAY_OPTIONS.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
        </select>
      </div>}
    </div>}

    {fields.type === 'signal' && <div className="routine-editor__row">
      <div className="routine-field routine-field--kind">
        <label htmlFor={`${prefix}-kind`} className="routine-label">What happens</label>
        <select id={`${prefix}-kind`} value={fields.kind} onChange={event => set({ kind: event.target.value })}>
          {SIGNAL_OPTIONS.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
        </select>
      </div>
      {fields.kind === 'calendar.soon' && <div className="routine-field routine-field--minutes">
        <label htmlFor={`${prefix}-minutes`} className="routine-label">When</label>
        <select id={`${prefix}-minutes`} value={fields.minutes} onChange={event => set({ minutes: event.target.value })}>
          {MINUTE_OPTIONS.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
        </select>
      </div>}
      <div className="routine-field routine-field--filter">
        <label htmlFor={`${prefix}-filter`} className="routine-label">Only when (JSON, optional)</label>
        <input id={`${prefix}-filter`} type="text" autoComplete="off" spellCheck={false} placeholder='{"state": "failed"}' value={fields.filterText}
          aria-invalid={!!error('filter')} aria-describedby={error('filter') ? `${prefix}-filter-error` : undefined}
          onChange={event => set({ filterText: event.target.value })} />
        {error('filter') && <p id={`${prefix}-filter-error`} className="routine-error">{error('filter')}</p>}
      </div>
    </div>}

    <div className="routine-steps">
      <h3 className="routine-steps__title" id={`${prefix}-steps`}>{`Steps · ${stepCount(fields.steps.length)} of ${MAX_STEPS}`}</h3>
      <ol ref={stepsRef} className="routine-steps__list" aria-labelledby={`${prefix}-steps`}>
        {fields.steps.map((step, index) => <StepEditor key={step.key} step={step} index={index} count={fields.steps.length}
          tools={choices} error={stepError(step)} prefix={prefix}
          onChange={changes => set({ steps: updateStep(fields.steps, index, changes) })}
          onMove={delta => move(index, delta)} onRemove={() => remove(index)} />)}
      </ol>
      {error('steps') && <p className="routine-error">{error('steps')}</p>}
      <button type="button" className="btn btn--ghost btn--sm routine-steps__add" disabled={fields.steps.length >= MAX_STEPS} onClick={add}>
        <Plus size={14} aria-hidden="true" />Add step</button>
    </div>
    {serverError && <p className="routine-error" role="alert">{serverError}</p>}
    {tried && !checked.ok && <p className="routine-error" role="alert">Fix the marked fields, then save.</p>}
    <div className="routine-editor__actions">
      <button type="submit" className="btn btn--primary btn--sm" disabled={busy}>Save</button>
      <button type="button" className="btn btn--ghost btn--sm" disabled={busy} onClick={onCancel}>Cancel</button>
    </div>
  </form>;
}

function RoutineRow({ routine, client, tools, onSaved, onDeleted }) {
  const [mode, setMode] = useState('view');  // view | edit | confirm
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const editRef = useRef(null), deleteRef = useRef(null), confirmRef = useRef(null);
  const outcome = outcomeLine(routine);
  const running = outcome.state === 'running';
  useEffect(() => { if (mode === 'confirm') confirmRef.current?.focus(); }, [mode]);
  const back = ref => { setMode('view'); requestAnimationFrame(() => ref.current?.focus()); };
  const act = async action => {
    setBusy(true); setError('');
    try { await action(); return true; }
    catch (failure) { setError(routinesFailureMessage(failure)); return false; }
    finally { setBusy(false); }
  };
  const toggle = () => act(async () => onSaved(await client.toggle(routine.id, !routine.enabled)));
  const run = () => act(() => client.run(routine.id));
  const save = async value => { if (await act(async () => onSaved(await client.save(value, routine.id)))) back(editRef); };
  const remove = () => act(async () => { await client.remove(routine.id); onDeleted(routine.id); });
  const labelId = `routine-${routine.id}-name`;

  if (mode === 'edit') return <li className="routine-row is-open">
    <RoutineEditor routine={routine} tools={tools} busy={busy} serverError={error} onSave={save} onCancel={() => { setError(''); back(editRef); }} />
  </li>;
  return <li className={`routine-row ${mode !== 'view' ? 'is-open' : ''}`} data-routine={routine.id} data-enabled={routine.enabled || undefined}>
    <div className="routine-row__copy">
      <div className="routine-row__head">
        <strong id={labelId} className="routine-row__name">{routine.name}</strong>
        {!routine.enabled && <StatusChip tone="idle" className="routine-row__chip">Off</StatusChip>}
      </div>
      <p className="routine-row__trigger">{triggerSummary(routine.trigger)}<span aria-hidden="true"> · </span>{stepCount(routine.steps.length)}</p>
      <p className="routine-row__outcome"><StatusChip tone={outcome.tone}>{outcome.text}</StatusChip></p>
    </div>
    <div className="routine-row__controls">
      <span className="routine-row__switch">
        <span className="routine-row__switch-label" aria-hidden="true">{routine.enabled ? 'On' : 'Off'}</span>
        <Switch checked={routine.enabled} label={`${routine.name} on`} disabled={busy} onClick={toggle} />
      </span>
      {mode === 'view' && <div className="routine-row__actions" role="group" aria-label={`Actions for ${routine.name}`}>
        <button type="button" className="btn btn--secondary btn--sm" disabled={busy || running} onClick={run}>
          <Play size={14} aria-hidden="true" />{running ? 'Running' : 'Run now'}</button>
        <button ref={editRef} type="button" className="btn btn--ghost btn--sm" disabled={busy} onClick={() => { setError(''); setMode('edit'); }}>
          <Pencil size={14} aria-hidden="true" />Edit</button>
        <button ref={deleteRef} type="button" className="btn btn--ghost btn--sm routine-row__delete" disabled={busy || running} onClick={() => { setError(''); setMode('confirm'); }}>
          <Trash2 size={14} aria-hidden="true" />Delete</button>
      </div>}
    </div>
    {mode === 'confirm' && <div className="routine-confirm" role="group" aria-label={`Delete ${routine.name}`}
      onKeyDown={event => { if (event.key === 'Escape') back(deleteRef); }}>
      <span className="routine-confirm__prompt">{DELETE_PROMPT}</span>
      <span aria-hidden="true" className="routine-confirm__dot">·</span>
      <button ref={confirmRef} type="button" className="btn btn--danger btn--sm" disabled={busy} onClick={remove}>Delete</button>
      <span aria-hidden="true" className="routine-confirm__dot">·</span>
      <button type="button" className="btn btn--ghost btn--sm" disabled={busy} onClick={() => back(deleteRef)}>Cancel</button>
    </div>}
    {error && <p className="routine-error routine-row__error" role="alert">{error}</p>}
  </li>;
}

/** Routines under Tasks (S7.4, docs/ROUTINES.md). */
export default function RoutinesPage() {
  const client = useMemo(() => createRoutinesClient(socket), []);
  useEffect(() => () => client.dispose(), [client]);
  const [routines, setRoutines] = useState(null);
  const [tools, setTools] = useState([]);
  const [loadError, setLoadError] = useState('');
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [createError, setCreateError] = useState('');
  const newRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const [items, available] = await Promise.all([client.list(), client.tools()]);
      setRoutines(items); setTools(available); setLoadError('');
    } catch (failure) {
      if (failure?.code !== 'scope_closed') setLoadError(routinesFailureMessage(failure));
    }
  }, [client]);
  useEffect(() => {
    load();
    const offChanged = client.on('routines_changed', () => { load(); });
    const offConnect = client.on('connect', () => { load(); });
    return () => { offChanged(); offConnect(); };
  }, [client, load]);

  const saved = useCallback(routine => setRoutines(current => withRoutine(current || [], routine)), []);
  const deleted = useCallback(id => setRoutines(current => withoutRoutine(current || [], id)), []);
  const closeNew = () => { setCreating(false); setCreateError(''); requestAnimationFrame(() => newRef.current?.focus()); };
  const create = async value => {
    setBusy(true); setCreateError('');
    try { saved(await client.save(value)); closeNew(); }
    catch (failure) { setCreateError(routinesFailureMessage(failure)); }
    finally { setBusy(false); }
  };

  return <section className="routines-page" aria-labelledby="routines-title">
    <div className="workspace-heading routines-heading">
      <div className="workspace-heading__copy">
        {/* The panel header already shows the title; this one is for screen readers. */}
        <h1 id="routines-title" className="sr-only">{PAGE_TITLE}</h1>
        <p>{PAGE_DESCRIPTION}</p>
      </div>
      <button ref={newRef} type="button" className="btn btn--primary btn--sm" disabled={creating || routines === null} onClick={() => setCreating(true)}>
        <Plus size={14} aria-hidden="true" />New routine</button>
    </div>
    {creating && <RoutineEditor tools={tools} busy={busy} serverError={createError} onSave={create} onCancel={closeNew} />}
    {loadError && routines === null ? <PanelState kind="error" title="Could not load routines" detail={loadError} action={load} actionLabel="Refresh" />
      : routines === null ? <PanelState kind="loading" title="Loading routines" />
        : routines.length === 0 ? (!creating && <EmptyState className="routines-empty" icon={<Repeat />} body={EMPTY_COPY} />)
          : <ul className="routines-list" aria-label="Your routines">{routines.map(routine => <RoutineRow key={routine.id} routine={routine}
            client={client} tools={tools} onSaved={saved} onDeleted={deleted} />)}</ul>}
  </section>;
}
