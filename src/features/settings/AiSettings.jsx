import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import socket from '../../services/socket';
import StatusChip from '../../shared/ui/StatusChip';
import { createSecretsClient } from '../../transport/secretsClient.ts';
import {
  AUTO_HELP, BRAIN_OPTIONS, ENV_NOTE, NAME_HELP, PROVIDERS, REMOVE_CONFIRM,
  activeModelText, brainOption, brainProblem, rejectedMessage, rpcFailureMessage, saveResultMessage, secretChip, testResultMessage,
} from './aiSettingsModel';

const ROW = 'flex flex-col gap-2 rounded-md border border-line bg-raised px-3 py-2';
const HELP = 'text-[0.75rem] leading-relaxed text-ink-2';
const TONE_TEXT = { ok: 'text-ok', warn: 'text-warn', danger: 'text-danger', idle: 'text-ink-2' };

const ResultMessage = ({ id, result }) =>
  <p id={id} aria-live="polite" className={`min-h-0 text-[0.75rem] leading-snug ${result ? TONE_TEXT[result.tone] || 'text-ink-2' : ''}`}>
    {result ? result.text : ''}
  </p>;

function ProviderRow({ entry, status, client, onStatus }) {
  const [mode, setMode] = useState('idle'); // idle | edit | confirm
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const inputRef = useRef(null);
  const openerRef = useRef(null);
  const confirmRef = useRef(null);
  const removeRef = useRef(null);
  const chip = secretChip(status);
  const configured = !!status?.configured;
  const inputId = `ai-key-${entry.name}`;
  const resultId = `${inputId}-result`;

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
    if (!value.trim()) { setResult({ tone: 'warn', text: 'Paste a key first.' }); return; }
    // A key the provider rejects is never stored, so the saved one (if any) stays in use.
    const hadPrevious = configured && status?.source === 'store';
    setBusy(true);
    setResult(null);
    try {
      const saved = await client.set(entry.name, value);
      onStatus(saved);
      setResult(saveResultMessage(entry.name, saved));
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
      setResult({ tone: 'idle', text: 'Key removed.' });
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
        <p className="mt-0.5 text-[0.75rem] leading-snug text-ink-2">{entry.purpose}</p>
        {chip.envOverride && <p className="mt-0.5 text-[0.75rem] leading-snug text-ink-2">{ENV_NOTE}</p>}
      </div>
      <StatusChip tone={chip.tone}>{chip.hint ? <>VERIFIED ··<span className="normal-case">{chip.hint}</span></> : chip.label}</StatusChip>
    </div>

    {mode === 'idle' && <div className="flex flex-wrap items-center gap-2">
      {!chip.envOverride && <button ref={openerRef} type="button" className="btn btn--secondary btn--sm" disabled={busy}
        aria-label={`${configured ? 'Replace' : 'Add'} ${entry.title} key`} onClick={() => { setResult(null); setMode('edit'); }}>
        {configured ? 'Replace' : 'Add key'}
      </button>}
      {configured && <button type="button" className="btn btn--ghost btn--sm" disabled={busy}
        aria-label={`Test ${entry.title} key`} aria-describedby={resultId} onClick={runTest}>
        {busy ? 'Checking…' : 'Test'}
      </button>}
      {configured && !chip.envOverride && <button ref={removeRef} type="button" className="btn btn--ghost btn--sm" disabled={busy}
        aria-label={`Remove ${entry.title} key`} onClick={() => { setResult(null); setMode('confirm'); }}>
        Remove
      </button>}
    </div>}

    {mode === 'edit' && <form className="flex flex-wrap items-end gap-2" onSubmit={save} autoComplete="off">
      <div className="flex min-w-0 flex-1 basis-48 flex-col gap-1">
        <label htmlFor={inputId} className="text-[0.75rem] text-ink-2">{entry.provider === 'Google' ? 'Gemini' : 'Anthropic'} API key</label>
        <input ref={inputRef} id={inputId} type="password" name={`${entry.name}-entry`} autoComplete="off" spellCheck={false}
          autoCapitalize="off" autoCorrect="off" data-lpignore="true" data-1p-ignore="true" disabled={busy}
          aria-describedby={resultId}
          className="w-full rounded-md border border-line-strong bg-panel px-2 py-1.5 font-mono text-[0.8125rem] text-ink-1"
          onKeyDown={(event) => { if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); event.currentTarget.value = ''; closeTo(openerRef); } }} />
      </div>
      <button type="submit" className="btn btn--primary btn--sm" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
      <button type="button" className="btn btn--ghost btn--sm" disabled={busy}
        onClick={() => { if (inputRef.current) inputRef.current.value = ''; closeTo(openerRef); }}>Cancel</button>
    </form>}

    {mode === 'confirm' && <div className="flex flex-wrap items-center gap-2" role="group" aria-label={`Remove ${entry.title} key`}>
      <span className="text-[0.75rem] text-ink-1">{REMOVE_CONFIRM}</span>
      <button ref={confirmRef} type="button" className="btn btn--danger btn--sm" disabled={busy} onClick={remove}>Remove</button>
      <button type="button" className="btn btn--ghost btn--sm" disabled={busy} onClick={() => closeTo(removeRef)}>Cancel</button>
    </div>}

    <ResultMessage id={resultId} result={result} />
  </div>;
}

const BrainControl = ({ value, disabled, onChange }) =>
  <div role="radiogroup" aria-label="AI brain" className="inline-flex shrink-0 rounded-md border border-line-strong bg-panel p-0.5">
    {BRAIN_OPTIONS.map((entry) =>
      <label key={entry.id} className="relative cursor-pointer">
        <input type="radio" className="peer sr-only" name="assistant-brain" value={entry.id} disabled={disabled}
          checked={value === entry.id} onChange={() => onChange(entry.id)} />
        <span className="flex min-h-[1.75rem] items-center rounded px-2.5 text-[0.6875rem] text-ink-2 transition-colors hover:text-ink-1 peer-checked:bg-[var(--accent-subtle)] peer-checked:text-accent peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-1 peer-focus-visible:outline-[color:var(--accent)] [@media(pointer:coarse)]:min-h-[2.75rem]">
          {entry.label}
        </span>
      </label>
    )}
  </div>;

/** "AI and assistant" section at the top of Preferences. `assistant` is the saved settings.assistant. */
export default function AiSettings({ assistant }) {
  const client = useMemo(() => createSecretsClient(socket), []);
  const [statuses, setStatuses] = useState({});
  const [loadError, setLoadError] = useState('');
  const [brain, setBrain] = useState(null);
  const [brainError, setBrainError] = useState('');
  const [nameResult, setNameResult] = useState(null);
  const savedName = typeof assistant?.owner_name === 'string' ? assistant.owner_name : '';
  const [name, setName] = useState(savedName);
  const setting = brainOption(assistant);

  useEffect(() => () => client.dispose(), [client]);
  useEffect(() => { setName(savedName); }, [savedName]);

  const refreshBrain = useCallback(() => {
    client.brain().then(setBrain).catch(() => {});
  }, [client]);

  const load = useCallback(() => {
    client.status().then((list) => {
      setStatuses(Object.fromEntries(list.map((s) => [s.name, s])));
      setLoadError('');
    }).catch((error) => setLoadError(rpcFailureMessage(error)));
    refreshBrain();
  }, [client, refreshBrain]);

  useEffect(() => {
    load();
    return client.on('connect', load);
  }, [client, load]);

  // The saved setting changed (here or elsewhere): the active model may have moved.
  useEffect(() => { refreshBrain(); }, [setting, refreshBrain]);

  const onStatus = useCallback((status) => {
    setStatuses((current) => ({ ...current, [status.name]: status }));
    refreshBrain();
  }, [refreshBrain]);

  // update_settings reports failures on the `error` event with the core's message.
  const patchAssistant = async (patch) => {
    let message = '';
    const off = client.on('error', (payload) => { if (payload && typeof payload.msg === 'string') message = payload.msg; });
    try {
      await client.updateSettings({ assistant: patch });
      return '';
    } catch (error) {
      return message || rpcFailureMessage(error);
    } finally { off(); }
  };

  const chooseBrain = async (next) => {
    if (next === setting) return;
    setBrainError(await patchAssistant({ brain: next }));
  };

  const saveName = async (raw) => {
    const next = raw.replace(/\s+/g, ' ').trim();
    if (next === savedName) return;
    const failure = await patchAssistant({ owner_name: next });
    setNameResult(failure ? { tone: 'danger', text: failure } : { tone: 'ok', text: 'Name saved.' });
  };

  const problem = brainError || brainProblem(setting, brain);

  return <section className="flex flex-col gap-4" aria-labelledby="ai-settings-heading">
    <h3 id="ai-settings-heading" className="sr-only">AI and assistant</h3>

    <div className="flex flex-col gap-2">
      <h4 className="hud-label">AI providers</h4>
      {loadError && <p className="text-[0.75rem] text-danger" role="alert">{loadError}</p>}
      {PROVIDERS.map((entry) =>
        <ProviderRow key={entry.name} entry={entry} status={statuses[entry.name]} client={client} onStatus={onStatus} />
      )}
    </div>

    <div className="flex flex-col gap-2">
      <h4 className="hud-label">Assistant</h4>
      <div className={ROW}>
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
          <span id="assistant-brain-label" className="text-sm text-ink-1">AI brain</span>
          <BrainControl value={setting} onChange={chooseBrain} />
        </div>
        {setting === 'auto' && <p className={HELP}>{AUTO_HELP}</p>}
        {brain && <p className={HELP} data-active-model>{activeModelText(brain)}</p>}
        <p aria-live="polite" className="text-[0.75rem] leading-snug text-danger">{problem}</p>
      </div>
      <div className={ROW}>
        <label htmlFor="assistant-owner-name" className="text-sm text-ink-1">Your name <span className="text-ink-2">(optional)</span></label>
        <input id="assistant-owner-name" type="text" maxLength={80} autoComplete="off" spellCheck={false} value={name}
          aria-describedby="assistant-owner-name-help assistant-owner-name-result"
          className="w-full rounded-md border border-line-strong bg-panel px-2 py-1.5 text-sm text-ink-1"
          onChange={(event) => { setName(event.target.value); setNameResult(null); }}
          onBlur={(event) => saveName(event.currentTarget.value)}
          onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); saveName(event.currentTarget.value); } }} />
        <p id="assistant-owner-name-help" className={HELP}>{NAME_HELP}</p>
        <ResultMessage id="assistant-owner-name-result" result={nameResult} />
      </div>
    </div>
  </section>;
}
