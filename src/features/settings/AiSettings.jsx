import React, { useCallback, useEffect, useMemo, useState } from 'react';
import socket from '../../services/socket';
import { createSecretsClient } from '../../transport/secretsClient.ts';
import VoiceSettings from './VoiceSettings';
import BriefingSettings from './BriefingSettings';
import SecretKeyRow, { ResultMessage } from './SecretKeyRow';
import SegmentedControl from './SegmentedControl';
import {
  ADDRESS_LABEL, ADDRESS_OPTIONS, AUTO_HELP, BRAIN_OPTIONS, NAME_HELP, PROVIDERS, activeModelText, addressHint, addressOption,
  brainOption, brainProblem, rpcFailureMessage,
} from './aiSettingsModel';

const ROW = 'flex flex-col gap-2 rounded-md border border-line bg-raised px-3 py-2';
const HELP = 'text-[0.75rem] leading-relaxed text-ink-2';
const HINT = 'text-[0.75rem] leading-relaxed text-ink-3';
const LINE = 'flex flex-wrap items-center justify-between gap-x-3 gap-y-2';

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

/** "AI and assistant" section at the top of Preferences. `assistant`, `voice` and `briefing` are the saved settings sections. */
export default function AiSettings({ assistant, voice, briefing }) {
  const client = useMemo(() => createSecretsClient(socket), []);
  const [statuses, setStatuses] = useState({});
  const [loadError, setLoadError] = useState('');
  const [brain, setBrain] = useState(null);
  const [brainError, setBrainError] = useState('');
  const [nameResult, setNameResult] = useState(null);
  const savedName = typeof assistant?.owner_name === 'string' ? assistant.owner_name : '';
  const [name, setName] = useState(savedName);
  const [addressResult, setAddressResult] = useState(null);
  const setting = brainOption(assistant);
  const address = addressOption(assistant);
  const hint = addressHint(address, savedName);

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
  const patchSettings = async (patch) => {
    let message = '';
    const off = client.on('error', (payload) => { if (payload && typeof payload.msg === 'string') message = payload.msg; });
    try {
      await client.updateSettings(patch);
      return '';
    } catch (error) {
      return message || rpcFailureMessage(error);
    } finally { off(); }
  };

  const chooseBrain = async (next) => {
    if (next === setting) return;
    setBrainError(await patchSettings({ assistant: { brain: next } }));
  };

  const saveName = async (raw) => {
    const next = raw.replace(/\s+/g, ' ').trim();
    if (next === savedName) return;
    const failure = await patchSettings({ assistant: { owner_name: next } });
    setNameResult(failure ? { tone: 'danger', text: failure } : { tone: 'ok', text: 'Name saved.' });
  };

  const chooseAddress = async (next) => {
    if (next === address) return;
    setAddressResult(null);
    const failure = await patchSettings({ assistant: { address: next } });
    setAddressResult(failure ? { tone: 'danger', text: failure } : null);
  };

  const problem = brainError || brainProblem(setting, brain);

  return <section className="flex flex-col gap-4" aria-labelledby="ai-settings-heading">
    <h3 id="ai-settings-heading" className="sr-only">AI and assistant</h3>

    <div className="flex flex-col gap-2">
      <h4 className="hud-label">AI providers</h4>
      {loadError && <p className="text-[0.75rem] text-danger" role="alert">{loadError}</p>}
      {PROVIDERS.map((entry) =>
        <SecretKeyRow key={entry.name} entry={entry} status={statuses[entry.name]} client={client} onStatus={onStatus} />
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
      <div className={ROW} data-assistant-address>
        <div className={LINE}>
          <span id="assistant-address-label" className="text-sm text-ink-1">{ADDRESS_LABEL}</span>
          <SegmentedControl name="assistant-address" options={ADDRESS_OPTIONS} value={address} onChange={chooseAddress}
            aria-labelledby="assistant-address-label" />
        </div>
        {hint && <p className={HINT} data-address-hint>{hint}</p>}
        <ResultMessage id="assistant-address-result" result={addressResult} />
      </div>
      <BriefingSettings briefing={briefing} patch={patchSettings} />
    </div>

    <VoiceSettings voice={voice} client={client} patch={patchSettings}
      previewAvailable={statuses.gemini_api_key ? !!statuses.gemini_api_key.configured : null} />
  </section>;
}
