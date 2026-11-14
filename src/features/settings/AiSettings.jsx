import React, { useCallback, useEffect, useMemo, useState } from 'react';
import socket from '../../services/socket';
import { createSecretsClient } from '../../transport/secretsClient.ts';
import VoiceSettings from './VoiceSettings';
import BriefingSettings from './BriefingSettings';
import SecretKeyRow, { ResultMessage } from './SecretKeyRow';
import SegmentedControl from './SegmentedControl';
import {
  ADDRESS_LABEL, ADDRESS_OPTIONS, AUTO_HELP, BRAIN_CHOICES, BRAIN_LABEL, EFFORT_LABEL, EFFORT_OPTIONS, GEMINI_LIST_FAILED,
  GEMINI_MODEL_LABEL, HOME_PLACE_EMPTY, HOME_PLACE_HELP, HOME_PLACE_LABEL, HOME_PLACE_MAX,
  HOME_PLACE_PLACEHOLDER, NAME_HELP, PROVIDERS, activeModelText, addressHint, addressOption,
  brainChoice, brainChoicePatch, brainOption, brainProblem, effortDisabled, effortHelp, effortOption, effortPatch,
  geminiModelOptions, geminiModelPatch, geminiModelValue, homePlaceInput, homePlaceStatus, rpcFailureMessage,
} from './aiSettingsModel';

const ROW = 'flex flex-col gap-2 rounded-md border border-line bg-raised px-3 py-2';
const HELP = 'text-[0.75rem] leading-relaxed text-ink-2';
const HINT = 'text-[0.75rem] leading-relaxed text-ink-3';
const LINE = 'flex flex-wrap items-center justify-between gap-x-3 gap-y-2';
const SELECT = 'w-full rounded-md border border-line-strong bg-panel px-2 py-1.5 text-sm text-ink-1';

/** "AI and assistant" section at the top of Preferences. `assistant`, `voice` and `briefing` are the saved settings sections. */
export default function AiSettings({ assistant, voice, briefing }) {
  const client = useMemo(() => createSecretsClient(socket), []);
  const [statuses, setStatuses] = useState({});
  const [loadError, setLoadError] = useState('');
  const [brain, setBrain] = useState(null);
  const [brainError, setBrainError] = useState('');
  const [geminiList, setGeminiList] = useState(null);
  const [geminiListFailed, setGeminiListFailed] = useState(false);
  const [nameResult, setNameResult] = useState(null);
  const savedName = typeof assistant?.owner_name === 'string' ? assistant.owner_name : '';
  const [name, setName] = useState(savedName);
  const [addressResult, setAddressResult] = useState(null);
  const [homeInput, setHomeInput] = useState('');
  const [homeBusy, setHomeBusy] = useState(false);
  const [homeResult, setHomeResult] = useState(null);
  const setting = brainOption(assistant);
  const choice = brainChoice(assistant);
  const effort = effortOption(assistant);
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

  // The saved choices changed (here or elsewhere): the active model may have moved.
  const claudeModel = assistant?.claude_model, geminiSaved = assistant?.gemini_model;
  useEffect(() => { refreshBrain(); }, [setting, claudeModel, effort, geminiSaved, refreshBrain]);

  // The Gemini model list, once per page open; on failure the select keeps the saved value.
  useEffect(() => {
    let live = true;
    client.brainModels().then((models) => { if (live) setGeminiList(models.gemini); })
      .catch(() => { if (live) setGeminiListFailed(true); });
    return () => { live = false; };
  }, [client]);

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

  const geminiValue = geminiModelValue(assistant, brain);

  const chooseBrain = async (next) => {
    const patch = brainChoicePatch(next, assistant);
    if (patch) setBrainError(await patchSettings(patch));
  };

  const chooseGeminiModel = async (next) => {
    const patch = geminiModelPatch(next, geminiValue);
    if (patch) setBrainError(await patchSettings(patch));
  };

  const chooseEffort = async (next) => {
    const patch = effortPatch(next, assistant);
    if (patch) setBrainError(await patchSettings(patch));
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

  const saveHomePlace = async (event) => {
    event.preventDefault();
    const next = homePlaceInput(homeInput);
    if (!next) { setHomeResult({ tone: 'warn', text: HOME_PLACE_EMPTY }); return; }
    setHomeBusy(true);
    setHomeResult(null);
    try {
      // The settings event carries the saved value to the status line.
      await client.setHomePlace(next);
      setHomeInput('');
    } catch (error) {
      setHomeResult({ tone: 'warn', text: rpcFailureMessage(error) });
    } finally { setHomeBusy(false); }
  };

  const problem = brainError || brainProblem(setting, brain);
  const geminiOptions = geminiModelOptions(geminiList, geminiValue);
  const noEffort = effortDisabled(setting, brain, statuses.anthropic_api_key ? !!statuses.anthropic_api_key.configured : undefined);

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
      <div className={ROW} data-assistant-brain>
        <label htmlFor="assistant-brain" className="text-sm text-ink-1">{BRAIN_LABEL}</label>
        <select id="assistant-brain" className={SELECT} value={choice} aria-describedby="assistant-brain-active assistant-brain-problem"
          onChange={(event) => chooseBrain(event.target.value)}>
          {BRAIN_CHOICES.map((entry) => <option key={entry.id} value={entry.id}>{entry.label}</option>)}
        </select>
        {setting === 'auto' && <p className={HELP}>{AUTO_HELP}</p>}
        {setting === 'gemini' && <>
          <label htmlFor="assistant-gemini-model" className="text-sm text-ink-1">{GEMINI_MODEL_LABEL}</label>
          <select id="assistant-gemini-model" className={SELECT} value={geminiValue} data-gemini-model
            aria-describedby={geminiListFailed ? 'assistant-gemini-model-help' : undefined}
            onChange={(event) => chooseGeminiModel(event.target.value)}>
            {geminiOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
          {geminiListFailed && <p id="assistant-gemini-model-help" className={HINT} data-gemini-list-failed>{GEMINI_LIST_FAILED}</p>}
        </>}
        <div className={LINE}>
          <span id="assistant-effort-label" className="text-sm text-ink-1">{EFFORT_LABEL}</span>
          <SegmentedControl name="assistant-effort" options={EFFORT_OPTIONS} value={effort} onChange={chooseEffort} disabled={noEffort}
            aria-labelledby="assistant-effort-label" aria-describedby="assistant-effort-help" />
        </div>
        <p id="assistant-effort-help" className={HELP} data-effort-help>{effortHelp(noEffort)}</p>
        {brain && <p id="assistant-brain-active" className={HELP} data-active-model>{activeModelText(brain, assistant)}</p>}
        <p id="assistant-brain-problem" aria-live="polite" className="text-[0.75rem] leading-snug text-danger">{problem}</p>
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
      <form className={ROW} data-assistant-home-place autoComplete="off" onSubmit={saveHomePlace}>
        <label htmlFor="assistant-home-place" className="text-sm text-ink-1">{HOME_PLACE_LABEL}</label>
        <div className="flex flex-wrap items-center gap-2">
          <input id="assistant-home-place" type="text" maxLength={HOME_PLACE_MAX} autoComplete="off" spellCheck={false}
            placeholder={HOME_PLACE_PLACEHOLDER} value={homeInput} disabled={homeBusy}
            aria-describedby="assistant-home-place-help assistant-home-place-status assistant-home-place-result"
            className="min-w-0 flex-1 basis-48 rounded-md border border-line-strong bg-panel px-2 py-1.5 text-sm text-ink-1"
            onChange={(event) => { setHomeInput(event.target.value); setHomeResult(null); }} />
          <button type="submit" className="btn btn--primary btn--sm" disabled={homeBusy}>{homeBusy ? 'Saving…' : 'Save'}</button>
        </div>
        <p id="assistant-home-place-help" className={HELP}>{HOME_PLACE_HELP}</p>
        <p id="assistant-home-place-status" className="text-[0.75rem] leading-snug text-ink-1" data-home-place-status>{homePlaceStatus(assistant)}</p>
        <ResultMessage id="assistant-home-place-result" result={homeResult} />
      </form>
      <BriefingSettings briefing={briefing} patch={patchSettings} />
    </div>

    <VoiceSettings voice={voice} client={client} patch={patchSettings}
      previewAvailable={statuses.gemini_api_key ? !!statuses.gemini_api_key.configured : null} />
  </section>;
}
