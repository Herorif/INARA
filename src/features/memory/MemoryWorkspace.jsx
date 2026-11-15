import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Brain, Download, Pencil, Pin, PinOff, Search, Trash2 } from 'lucide-react';
import socket from '../../services/socket';
import PanelState from '../../app/PanelState';
import StatusChip from '../../shared/ui/StatusChip';
import EmptyState from '../../shared/ui/EmptyState';
import { Switch } from '../calls/controls';
import { createMemoryClient } from './memoryClient';
import {
  DELETE_PROMPT, EMPTY_COPY, EXPORT_FILENAME, KIND_OPTIONS, NO_MATCH_COPY, PAGE_DESCRIPTION, PAGE_TITLE, PAUSED_LINE,
  SUBJECT_LIMIT, TEXT_LIMIT, editChanges, editFields, factCount, filterFacts, groupFacts, learnedLine,
  memoryFailureMessage, sensitivityChip, validateEdit, withFact, withoutFact,
} from './memoryModel';
import './memory.css';

/** Inline editor: subject, text and kind; Save / Cancel. Escape cancels. */
function FactEditor({ fact, busy, onSave, onCancel }) {
  const [fields, setFields] = useState(() => editFields(fact));
  const [tried, setTried] = useState(false);
  const subjectRef = useRef(null);
  const checked = validateEdit(fields);
  const prefix = `memory-edit-${fact.id}`;
  useEffect(() => { subjectRef.current?.focus(); }, []);
  const submit = event => {
    event.preventDefault();
    setTried(true);
    if (checked.ok) onSave(checked.value);
  };
  const error = key => (tried ? checked.errors[key] : '');
  return <form className="memory-editor" aria-label={`Edit ${fact.subject}`} onSubmit={submit}
    onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); onCancel(); } }}>
    <div className="memory-editor__row">
      <div className="memory-field memory-field--subject">
        <label htmlFor={`${prefix}-subject`} className="memory-label">Subject</label>
        <input ref={subjectRef} id={`${prefix}-subject`} type="text" autoComplete="off" maxLength={SUBJECT_LIMIT + 20} value={fields.subject}
          aria-invalid={!!error('subject')} aria-describedby={`${prefix}-subject-error`}
          onChange={event => setFields(current => ({ ...current, subject: event.target.value }))} />
        {error('subject') && <p id={`${prefix}-subject-error`} className="memory-error">{error('subject')}</p>}
      </div>
      <div className="memory-field memory-field--kind">
        <label htmlFor={`${prefix}-kind`} className="memory-label">Group</label>
        <select id={`${prefix}-kind`} value={fields.kind} onChange={event => setFields(current => ({ ...current, kind: event.target.value }))}>
          {KIND_OPTIONS.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
        </select>
      </div>
    </div>
    <div className="memory-field">
      <label htmlFor={`${prefix}-text`} className="memory-label">Fact</label>
      <textarea id={`${prefix}-text`} rows={2} maxLength={TEXT_LIMIT + 20} value={fields.text}
        aria-invalid={!!error('text')} aria-describedby={`${prefix}-text-error`}
        onChange={event => setFields(current => ({ ...current, text: event.target.value }))} />
      {error('text') && <p id={`${prefix}-text-error`} className="memory-error">{error('text')}</p>}
    </div>
    <div className="memory-editor__actions">
      <button type="submit" className="btn btn--primary btn--sm" disabled={busy}>Save</button>
      <button type="button" className="btn btn--ghost btn--sm" disabled={busy} onClick={onCancel}>Cancel</button>
    </div>
  </form>;
}

function FactRow({ fact, client, onSaved, onDeleted, onOpenConversation }) {
  const [mode, setMode] = useState('view');  // view | edit | confirm
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const editRef = useRef(null), deleteRef = useRef(null), confirmRef = useRef(null);
  const chip = sensitivityChip(fact);
  const line = learnedLine(fact);
  useEffect(() => { if (mode === 'confirm') confirmRef.current?.focus(); }, [mode]);
  const back = ref => { setMode('view'); requestAnimationFrame(() => ref.current?.focus()); };

  const run = async action => {
    setBusy(true); setError('');
    try { await action(); return true; }
    catch (failure) { setError(memoryFailureMessage(failure)); return false; }
    finally { setBusy(false); }
  };
  const togglePin = () => run(async () => onSaved(await client.update(fact.id, { pinned: !fact.pinned })));
  const save = async value => {
    const changes = editChanges(fact, value);
    if (!Object.keys(changes).length) { back(editRef); return; }
    if (await run(async () => onSaved(await client.update(fact.id, changes)))) back(editRef);
  };
  const remove = () => run(async () => { await client.remove(fact.id); onDeleted(fact.id); });

  return <li className={`memory-row ${mode !== 'view' ? 'is-open' : ''}`} data-fact={fact.id} data-pinned={fact.pinned || undefined}>
    {mode === 'edit'
      ? <FactEditor fact={fact} busy={busy} onSave={save} onCancel={() => back(editRef)} />
      : <>
        <div className="memory-row__copy">
          <div className="memory-row__head">
            {fact.pinned && <Pin size={14} className="memory-row__pin" role="img" aria-label="Pinned" />}
            <strong className="memory-row__subject">{fact.subject}</strong>
            {chip && <StatusChip tone={chip.tone} className="memory-row__chip">{chip.label}</StatusChip>}
          </div>
          <p className="memory-row__text">{fact.text}</p>
          <p className="memory-row__meta">
            <span>{line.learned}</span>
            {line.source && <><span aria-hidden="true"> · </span>
              <button type="button" className="memory-link" onClick={() => onOpenConversation?.(line.conversationId)}>{line.source}</button></>}
          </p>
        </div>
        {mode === 'view' && <div className="memory-row__actions" role="group" aria-label={`Actions for ${fact.subject}`}>
          <button type="button" className="btn btn--ghost btn--sm" disabled={busy} aria-pressed={fact.pinned} onClick={togglePin}>
            {fact.pinned ? <PinOff size={14} aria-hidden="true" /> : <Pin size={14} aria-hidden="true" />}{fact.pinned ? 'Unpin' : 'Pin'}
          </button>
          <button ref={editRef} type="button" className="btn btn--ghost btn--sm" disabled={busy} onClick={() => { setError(''); setMode('edit'); }}>
            <Pencil size={14} aria-hidden="true" />Edit
          </button>
          <button ref={deleteRef} type="button" className="btn btn--ghost btn--sm memory-row__delete" disabled={busy} onClick={() => { setError(''); setMode('confirm'); }}>
            <Trash2 size={14} aria-hidden="true" />Delete
          </button>
        </div>}
      </>}
    {mode === 'confirm' && <div className="memory-confirm" role="group" aria-label={`Delete ${fact.subject}`}
      onKeyDown={event => { if (event.key === 'Escape') back(deleteRef); }}>
      <span className="memory-confirm__prompt">{DELETE_PROMPT}</span>
      <span aria-hidden="true" className="memory-confirm__dot">·</span>
      <button ref={confirmRef} type="button" className="btn btn--danger btn--sm" disabled={busy} onClick={remove}>Delete</button>
      <span aria-hidden="true" className="memory-confirm__dot">·</span>
      <button type="button" className="btn btn--ghost btn--sm" disabled={busy} onClick={() => back(deleteRef)}>Cancel</button>
    </div>}
    {error && <p className="memory-error memory-row__error" role="alert">{error}</p>}
  </li>;
}

/** Saves the export through the renderer's download path (Electron asks where to save). */
function saveJson(text) {
  const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url; link.download = EXPORT_FILENAME;
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** "What JARVIS knows": the owner's long-term memory, grouped by kind (S6.4, docs/MEMORY.md). */
export default function MemoryWorkspace({ onOpenConversation }) {
  const client = useMemo(() => createMemoryClient(socket), []);
  useEffect(() => () => client.dispose(), [client]);
  const [facts, setFacts] = useState(null);
  const [paused, setPaused] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [query, setQuery] = useState('');
  const [note, setNote] = useState(null);  // { tone, text } for pause and export
  const [busy, setBusy] = useState('');

  const load = useCallback(async () => {
    try {
      const value = await client.list();
      setFacts(value.facts); setPaused(value.paused); setLoadError('');
    } catch (failure) {
      if (failure?.code !== 'scope_closed') setLoadError(memoryFailureMessage(failure));
    }
  }, [client]);
  useEffect(() => {
    load();
    const offRemembered = client.on('memory_remembered', () => { load(); });
    const offConnect = client.on('connect', () => { load(); });
    return () => { offRemembered(); offConnect(); };
  }, [client, load]);

  const togglePause = async () => {
    setBusy('pause'); setNote(null);
    try { setPaused(await client.pause(!paused)); }
    catch (failure) { setNote({ tone: 'danger', text: memoryFailureMessage(failure) }); }
    finally { setBusy(''); }
  };
  const exportAll = async () => {
    setBusy('export'); setNote(null);
    try { saveJson(await client.exportJson()); setNote({ tone: 'ok', text: `Exported ${EXPORT_FILENAME}.` }); }
    catch (failure) { setNote({ tone: 'danger', text: memoryFailureMessage(failure) }); }
    finally { setBusy(''); }
  };
  const saved = useCallback(fact => setFacts(current => withFact(current || [], fact)), []);
  const deleted = useCallback(id => setFacts(current => withoutFact(current || [], id)), []);

  const shown = facts ? filterFacts(facts, query) : [];
  const groups = groupFacts(shown);
  return <section className="memory-workspace" aria-labelledby="memory-title">
    <div className="workspace-heading memory-heading">
      <div className="workspace-heading__copy">
        <h1 id="memory-title">{PAGE_TITLE}</h1>
        <p>{PAGE_DESCRIPTION}</p>
      </div>
      <div className="memory-heading__controls">
        <span className="memory-pause">
          <span className="memory-pause__label" aria-hidden="true">Pause learning</span>
          <Switch checked={paused} label="Pause learning" describedBy={paused ? 'memory-paused-line' : undefined}
            disabled={busy === 'pause' || facts === null} onClick={togglePause} />
        </span>
        <button type="button" className="btn btn--secondary btn--sm" disabled={busy === 'export' || facts === null} onClick={exportAll}>
          <Download size={14} aria-hidden="true" />Export
        </button>
      </div>
    </div>
    {paused && <p id="memory-paused-line" className="memory-note memory-note--warn" role="status">{PAUSED_LINE}</p>}
    {note && <p className={`memory-note memory-note--${note.tone}`} role={note.tone === 'danger' ? 'alert' : 'status'}>{note.text}</p>}

    {facts !== null && facts.length > 0 && <div className="memory-search">
      <Search size={14} className="memory-search__icon" aria-hidden="true" />
      <input type="search" aria-label="Search what JARVIS knows" placeholder="Search facts" autoComplete="off" spellCheck={false}
        value={query} onChange={event => setQuery(event.target.value)} />
      <span className="sr-only" aria-live="polite">{query.trim() ? factCount(shown.length) : ''}</span>
    </div>}

    {loadError && facts === null ? <PanelState kind="error" title="Could not load what JARVIS knows" detail={loadError} action={load} actionLabel="Refresh" />
      : facts === null ? <PanelState kind="loading" title="Loading what JARVIS knows" />
        : facts.length === 0 ? <EmptyState className="memory-empty" icon={<Brain />} body={EMPTY_COPY} />
          : groups.length === 0 ? <p className="memory-none" role="status">{NO_MATCH_COPY}</p>
            : <div className="memory-groups">{groups.map(group => <section key={group.kind} className="memory-group" aria-labelledby={`memory-group-${group.kind}`}>
              <h2 id={`memory-group-${group.kind}`} className="memory-group__title">{group.heading}<span className="sr-only">{`, ${factCount(group.facts.length)}`}</span></h2>
              <ul className="memory-list">{group.facts.map(fact => <FactRow key={fact.id} fact={fact} client={client}
                onSaved={saved} onDeleted={deleted} onOpenConversation={onOpenConversation} />)}</ul>
            </section>)}</div>}
  </section>;
}
