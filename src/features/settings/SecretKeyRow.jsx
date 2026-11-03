import React, { useEffect, useRef, useState } from 'react';
import StatusChip from '../../shared/ui/StatusChip';
import { ENV_NOTE, REMOVE_CONFIRM, rejectedMessage, rpcFailureMessage, saveResultMessage, secretChip, testResultMessage } from './aiSettingsModel';

const ROW = 'flex flex-col gap-2 rounded-md border border-line bg-raised px-3 py-2';
const TONE_TEXT = { ok: 'text-ok', warn: 'text-warn', danger: 'text-danger', idle: 'text-ink-2' };

export const ResultMessage = ({ id, result }) =>
  <p id={id} aria-live="polite" className={`min-h-0 text-[0.75rem] leading-snug ${result ? TONE_TEXT[result.tone] || 'text-ink-2' : ''}`}>
    {result ? result.text : ''}
  </p>;

/**
 * One stored secret (API key, Twilio value, tunnel token, PIN): status chip and
 * add / replace / test / remove. The value is read once from an uncontrolled field and
 * cleared before the request; only status objects come back.
 *
 * entry: { name, title, purpose, provider, inputLabel?, inputType? ('password' | 'tel'),
 *   inputMode?, noun? ('key'), checkable? (true), removeConfirm?, removedText?, emptyText? }
 * onSaved(status) runs after a successful save (e.g. to re-check a companion value).
 */
export default function SecretKeyRow({ entry, status, client, onStatus, onSaved, idPrefix = 'ai-key' }) {
  const [mode, setMode] = useState('idle'); // idle | edit | confirm
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const inputRef = useRef(null);
  const openerRef = useRef(null);
  const confirmRef = useRef(null);
  const removeRef = useRef(null);
  const chip = secretChip(status);
  const configured = !!status?.configured;
  const noun = entry.noun || 'key';
  const checkable = entry.checkable !== false;
  const inputId = `${idPrefix}-${entry.name}`;
  const resultId = `${inputId}-result`;
  const inputLabel = entry.inputLabel || `${entry.provider === 'Google' ? 'Gemini' : 'Anthropic'} API key`;

  useEffect(() => {
    if (mode === 'edit') inputRef.current?.focus();
    if (mode === 'confirm') confirmRef.current?.focus();
  }, [mode]);

  const closeTo = (ref) => { setMode('idle'); requestAnimationFrame(() => ref.current?.focus()); };

  const save = async (event) => {
    event.preventDefault();
    const field = inputRef.current;
    if (!field || busy) return;
    // The value is read once and the field is emptied before any request is made.
    // It lives only in this call's argument until the socket frame is written.
    const value = field.value;
    field.value = '';
    if (!value.trim()) { setResult({ tone: 'warn', text: entry.emptyText || 'Paste a key first.' }); return; }
    // A value the provider rejects is never stored, so the saved one (if any) stays in use.
    const hadPrevious = configured && status?.source === 'store';
    setBusy(true);
    setResult(null);
    try {
      const saved = await client.set(entry.name, value);
      onStatus(saved);
      setResult(saveResultMessage(entry.name, saved));
      onSaved?.(saved);
    } catch (error) {
      if (error?.code !== 'key_rejected') {
        setResult({ tone: 'danger', text: rpcFailureMessage(error) });
        setBusy(false);
        field.focus();
        return;
      }
      setResult(rejectedMessage(entry.name, hadPrevious));
    }
    setBusy(false);
    setMode('idle');
    requestAnimationFrame(() => openerRef.current?.focus());
  };

  const runTest = async () => {
    setBusy(true);
    setResult(null);
    try {
      const tested = await client.test(entry.name);
      onStatus(tested);
      setResult(testResultMessage(entry.name, tested));
    } catch (error) {
      setResult({ tone: 'danger', text: rpcFailureMessage(error) });
    } finally { setBusy(false); }
  };

  const remove = async () => {
    setBusy(true);
    setResult(null);
    try {
      onStatus(await client.clear(entry.name));
      setResult({ tone: 'idle', text: entry.removedText || 'Key removed.' });
      setMode('idle');
      requestAnimationFrame(() => openerRef.current?.focus());
    } catch (error) {
      setResult({ tone: 'danger', text: rpcFailureMessage(error) });
    } finally { setBusy(false); }
  };

  return <div className={ROW} data-secret={entry.name}>
    <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
      <div className="min-w-0 flex-1 basis-40">
        <div className="text-sm text-ink-1">{entry.title}</div>
        {entry.purpose && <p className="mt-0.5 text-[0.75rem] leading-snug text-ink-2">{entry.purpose}</p>}
        {chip.envOverride && <p className="mt-0.5 text-[0.75rem] leading-snug text-ink-2">{ENV_NOTE}</p>}
      </div>
      <StatusChip tone={chip.tone}>{chip.hint ? <>{chip.prefix || 'VERIFIED'} ··<span className="normal-case">{chip.hint}</span></> : chip.label}</StatusChip>
    </div>

    {mode === 'idle' && <div className="flex flex-wrap items-center gap-2">
      {!chip.envOverride && <button ref={openerRef} type="button" className="btn btn--secondary btn--sm" disabled={busy}
        aria-label={`${configured ? 'Replace' : 'Add'} ${entry.title} ${noun}`} onClick={() => { setResult(null); setMode('edit'); }}>
        {configured ? 'Replace' : `Add ${noun}`}
      </button>}
      {configured && checkable && <button type="button" className="btn btn--ghost btn--sm" disabled={busy}
        aria-label={`Test ${entry.title} ${noun}`} aria-describedby={resultId} onClick={runTest}>
        {busy ? 'Checking…' : 'Test'}
      </button>}
      {configured && !chip.envOverride && <button ref={removeRef} type="button" className="btn btn--ghost btn--sm" disabled={busy}
        aria-label={`Remove ${entry.title} ${noun}`} onClick={() => { setResult(null); setMode('confirm'); }}>
        Remove
      </button>}
    </div>}

    {mode === 'edit' && <form className="flex flex-wrap items-end gap-2" onSubmit={save} autoComplete="off">
      <div className="flex min-w-0 flex-1 basis-48 flex-col gap-1">
        <label htmlFor={inputId} className="text-[0.75rem] text-ink-2">{inputLabel}</label>
        <input ref={inputRef} id={inputId} type={entry.inputType || 'password'} inputMode={entry.inputMode} name={`${entry.name}-entry`} autoComplete="off" spellCheck={false}
          autoCapitalize="off" autoCorrect="off" data-lpignore="true" data-1p-ignore="true" disabled={busy}
          aria-describedby={resultId}
          className="w-full rounded-md border border-line-strong bg-panel px-2 py-1.5 font-mono text-[0.8125rem] text-ink-1"
          onKeyDown={(event) => { if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); event.currentTarget.value = ''; closeTo(openerRef); } }} />
      </div>
      <button type="submit" className="btn btn--primary btn--sm" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
      <button type="button" className="btn btn--ghost btn--sm" disabled={busy}
        onClick={() => { if (inputRef.current) inputRef.current.value = ''; closeTo(openerRef); }}>Cancel</button>
    </form>}

    {mode === 'confirm' && <div className="flex flex-wrap items-center gap-2" role="group" aria-label={`Remove ${entry.title} ${noun}`}>
      <span className="text-[0.75rem] text-ink-1">{entry.removeConfirm || REMOVE_CONFIRM}</span>
      <button ref={confirmRef} type="button" className="btn btn--danger btn--sm" disabled={busy} onClick={remove}>Remove</button>
      <button type="button" className="btn btn--ghost btn--sm" disabled={busy} onClick={() => closeTo(removeRef)}>Cancel</button>
    </div>}

    <ResultMessage id={resultId} result={result} />
  </div>;
}
