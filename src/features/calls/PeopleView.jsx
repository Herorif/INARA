import React, { useEffect, useRef, useState } from 'react';
import { Plus, Trash2, UserPlus, Users, X } from 'lucide-react';
import StatusChip from '../../shared/ui/StatusChip';
import EmptyState from '../../shared/ui/EmptyState';
import PanelState from '../../app/PanelState';
import { Segmented } from './controls';
import {
  GROUP_OPTIONS, NOTE_LABEL, NOTE_LIMIT, NUMBERS_LIMIT, NAME_LIMIT, avatarText, editorFields, errorField, formatNumber, groupChip,
  groupCopy, normalizeNumber, peopleCount, peopleFailureMessage, personChanged, validatePerson, whenHeading,
} from './peopleModel';

export function PersonAvatar({ person }) {
  return <span className="people-avatar" aria-hidden="true">{avatarText(person)}</span>;
}

function PersonRow({ person, selected, onSelect }) {
  const chip = groupChip(person.group);
  return <li>
    <button type="button" className={`calls-row people-row ${selected ? 'is-selected' : ''}`} aria-pressed={selected} data-person={person.id ?? 'new'} onClick={() => onSelect(person.id)}>
      <PersonAvatar person={person} />
      <span className="people-row__copy">
        <strong className="calls-row__name">{person.name || 'New person'}</strong>
        <span className="people-row__number">{person.numbers?.[0] ? formatNumber(person.numbers[0]) : 'No number yet'}</span>
      </span>
      {chip && <StatusChip tone={chip.tone}>{chip.label}</StatusChip>}
    </button>
  </li>;
}

/** Left pane of the People tab: the count, "Add person" and the list. */
export function PeopleList({ people, error, selectedId, draft, onSelect, onAdd, onRetry }) {
  const rows = people ? [...(draft && !draft.id ? [draft] : []), ...people] : [];
  return <>
    <div className="people-head">
      <span className="people-head__count" aria-live="polite">{people ? peopleCount(people.length) : ''}</span>
      <button type="button" className="btn btn--secondary btn--sm" onClick={onAdd} disabled={!people}><UserPlus size={14} aria-hidden="true" />Add person</button>
    </div>
    {error ? <PanelState compact kind="error" title="Could not load people" detail={error} action={onRetry} actionLabel="Refresh" />
      : people === null ? <PanelState compact kind="loading" title="Loading people" />
        : rows.length ? <ul className="calls-list" aria-label="People">{rows.map(person => <PersonRow key={person.id ?? 'new'} person={person}
          selected={(person.id ?? null) === (selectedId ?? null) && (!!person.id || !!draft)} onSelect={onSelect} />)}</ul>
          : <EmptyState className="calls-empty" icon={<Users />} title="No people yet" body="Add the people who call you, so JARVIS knows who they are." />}
  </>;
}

const fieldError = (id, message) => message ? <p id={id} className="calls-note calls-note--danger people-error">{message}</p> : null;

/**
 * Right pane of the People tab. Saves on blur (name, numbers, note) or change (group) once
 * the person is valid; shows the errors inline. A new person is stored on its first valid save.
 */
export function PersonEditor({ person, people, client, onSaved, onDeleted }) {
  const [fields, setFields] = useState(() => editorFields(person));
  const [saved, setSavedState] = useState(person?.id ? person : null);
  const savedRef = useRef(saved);
  const setSaved = value => { savedRef.current = value; setSavedState(value); };
  const [touched, setTouched] = useState({});
  const [failure, setFailure] = useState(null);
  const [status, setStatus] = useState('');
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const latest = useRef(fields);
  latest.current = fields;
  const queue = useRef(Promise.resolve());
  const confirmRef = useRef(null), deleteRef = useRef(null);
  const checked = validatePerson(fields, people);
  useEffect(() => { if (confirm) confirmRef.current?.focus(); }, [confirm]);

  const commit = (next, field) => {
    const marks = { ...touched, ...(field ? { [field]: true } : {}) };
    setTouched(marks);
    const result = validatePerson(next, people);
    // A new person stays a draft until it is complete; a saved one keeps its last good version.
    if (!result.ok) return;
    queue.current = queue.current.then(async () => {
      const current = savedRef.current;  // saves run one at a time: a new person is created once
      if (!personChanged(result.value, current)) return;
      setStatus('Saving…'); setFailure(null);
      try {
        const stored = await client.save({ ...result.value, id: current?.id ?? null });
        setSaved(stored);
        setFields(current => ({ ...current, id: stored.id, numbers: current.numbers.map(value => { const number = normalizeNumber(value); return number ? formatNumber(number) : value; }) }));
        setStatus('Saved.');
        onSaved?.(stored);
      } catch (error) {
        setStatus('');
        setFailure({ field: errorField(error?.code), text: peopleFailureMessage(error) });
      }
    });
  };

  const update = change => setFields(current => ({ ...current, ...change }));
  const setNumber = (index, value) => update({ numbers: fields.numbers.map((item, position) => position === index ? value : item) });
  const blurNumber = index => {
    const number = normalizeNumber(latest.current.numbers[index] || '');
    const next = number ? { ...latest.current, numbers: latest.current.numbers.map((item, position) => position === index ? formatNumber(number) : item) } : latest.current;
    if (number) setFields(next);
    commit(next, `number-${index}`);
  };
  const addNumber = () => { if (fields.numbers.length < NUMBERS_LIMIT) update({ numbers: [...fields.numbers, ''] }); requestAnimationFrame(() => document.getElementById(`people-number-${fields.numbers.length}`)?.focus()); };
  const removeNumber = index => {
    const next = { ...fields, numbers: fields.numbers.length > 1 ? fields.numbers.filter((_item, position) => position !== index) : [''] };
    setFields(next);
    setTouched(current => Object.fromEntries(Object.entries(current).filter(([key]) => !key.startsWith('number-'))));
    commit(next, 'list');
  };
  const chooseGroup = group => { const next = { ...fields, group }; setFields(next); commit(next, 'group'); };
  const remove = async () => {
    setBusy(true); setFailure(null);
    try { await client.remove(saved.id); onDeleted?.(saved.id); }
    catch (error) { setFailure({ field: 'form', text: peopleFailureMessage(error) }); setBusy(false); }
  };

  const shown = key => touched[key] || touched.all;
  const nameError = shown('name') ? checked.errors.name : '';
  const listError = (shown('list') || Object.keys(touched).some(key => key.startsWith('number-'))) ? checked.errors.list : '';
  const serverError = field => failure && failure.field === field ? failure.text : '';
  const title = saved?.name || (fields.name.trim() ? fields.name.trim() : 'New person');
  const chip = groupChip(saved?.group || fields.group);

  return <article className="calls-detail people-editor" aria-labelledby="people-editor-title">
    <header className="calls-detail__head">
      <div className="people-editor__who">
        <PersonAvatar person={{ name: title === 'New person' ? '' : title }} />
        <div className="calls-detail__copy">
          <h2 id="people-editor-title">{title}</h2>
          <p className="calls-detail__meta" aria-live="polite">{status || (saved ? 'Saved' : 'Not saved yet')}</p>
        </div>
      </div>
      <div className="people-editor__tools">
        {chip && saved && <StatusChip tone={chip.tone}>{chip.label}</StatusChip>}
        {saved && <button ref={deleteRef} type="button" className="btn btn--ghost btn--icon calls-delete" aria-label="Delete person" title="Delete person" disabled={busy} onClick={() => setConfirm(true)}><Trash2 size={16} aria-hidden="true" /></button>}
      </div>
    </header>
    {confirm && <div className="calls-actions people-confirm" role="group" aria-label="Delete person">
      <span className="calls-confirm">{`Delete ${saved?.name || 'this person'}? This can't be undone.`}</span>
      <button ref={confirmRef} type="button" className="btn btn--danger btn--sm" disabled={busy} onClick={remove}>Delete</button>
      <button type="button" className="btn btn--ghost btn--sm" disabled={busy} onClick={() => { setConfirm(false); requestAnimationFrame(() => deleteRef.current?.focus()); }}>Cancel</button>
    </div>}
    {serverError('form') && <p className="calls-note calls-note--danger" role="alert">{serverError('form')}</p>}

    <div className="people-field">
      <label htmlFor="people-name" className="people-label">Name</label>
      <input id="people-name" type="text" autoComplete="off" spellCheck={false} maxLength={NAME_LIMIT} value={fields.name}
        aria-invalid={!!(nameError || serverError('name'))} aria-describedby="people-name-error"
        onChange={event => update({ name: event.target.value })} onBlur={() => commit(latest.current, 'name')} />
      {fieldError('people-name-error', nameError || serverError('name'))}
    </div>

    <fieldset className="people-field people-numbers">
      <legend className="people-label">Phone numbers</legend>
      {fields.numbers.map((value, index) => {
        const message = shown(`number-${index}`) ? checked.errors.numbers[index] : '';
        return <div key={index} className="people-number">
          <div className="people-number__row">
            <input id={`people-number-${index}`} type="text" inputMode="tel" autoComplete="off" spellCheck={false} maxLength={32} value={value}
              placeholder="+60 12-345 6789" aria-label={`Phone number ${index + 1}`} aria-invalid={!!message} aria-describedby={`people-number-${index}-error`}
              onChange={event => setNumber(index, event.target.value)} onBlur={() => blurNumber(index)} />
            <button type="button" className="btn btn--ghost btn--icon btn--sm" aria-label={`Remove phone number ${index + 1}`} title="Remove number"
              disabled={fields.numbers.length === 1 && !value} onClick={() => removeNumber(index)}><X size={14} aria-hidden="true" /></button>
          </div>
          {fieldError(`people-number-${index}-error`, message)}
        </div>;
      })}
      {fields.numbers.length < NUMBERS_LIMIT && <div><button type="button" className="btn btn--ghost btn--sm" onClick={addNumber}><Plus size={14} aria-hidden="true" />Add number</button></div>}
      {fieldError('people-numbers-error', listError || serverError('list'))}
    </fieldset>

    <div className="people-field">
      <span id="people-group-label" className="people-label">Group</span>
      <Segmented labelledBy="people-group-label" name="people-group" options={GROUP_OPTIONS} value={fields.group} onChange={chooseGroup} />
    </div>

    <div className="people-field">
      <label htmlFor="people-note" className="people-label">{NOTE_LABEL}</label>
      <textarea id="people-note" rows={3} maxLength={NOTE_LIMIT} value={fields.note} aria-describedby="people-note-count people-note-error"
        onChange={event => update({ note: event.target.value })} onBlur={() => commit(latest.current, 'note')} />
      <span id="people-note-count" className="calls-count people-count">{`${fields.note.length} / ${NOTE_LIMIT}`}</span>
      {fieldError('people-note-error', (shown('note') ? checked.errors.note : '') || serverError('note'))}
    </div>

    <section className="calls-panel hud-panel people-when" aria-labelledby="people-when-label">
      <h3 id="people-when-label" className="people-when__title">{whenHeading(fields.name)}</h3>
      <p className="calls-panel__text" data-group={fields.group}>{groupCopy(fields.group)}</p>
    </section>
  </article>;
}
