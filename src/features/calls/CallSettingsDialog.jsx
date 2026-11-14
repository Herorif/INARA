import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import socket from '../../services/socket';
import PanelHeader from '../../app/PanelHeader';
import { useDialogFocus } from '../../app/useDialogFocus';
import HudLabel from '../../shared/ui/HudLabel';
import SecretKeyRow, { ResultMessage } from '../settings/SecretKeyRow';
import { rpcFailureMessage } from '../settings/aiSettingsModel';
import { createSecretsClient } from '../../transport/secretsClient.ts';
import { Segmented } from './controls';
import {
  BRIEF_OPTIONS, FACTS_LIMIT, WHEN_DISABLED_OPTIONS, validTime, validatePublicAddress, validateWhole,
} from './callsModel';

const ROW = 'flex flex-col gap-2 rounded-md border border-line bg-raised px-3 py-2';
const HELP = 'text-[0.75rem] leading-relaxed text-ink-2';
const FIELD = 'rounded-md border border-line-strong bg-panel px-2 py-1.5 text-sm text-ink-1';
const PIN = {
  name: 'call_briefing_pin', title: 'Briefing PIN', provider: 'JARVIS', noun: 'PIN', inputLabel: 'Briefing PIN, 4 to 8 digits',
  inputMode: 'numeric', checkable: false, purpose: 'JARVIS asks for it before telling anyone on a call about your messages. It is never shown.',
  removeConfirm: 'Remove the briefing PIN? JARVIS will brief you without asking for it.', removedText: 'PIN removed.', emptyText: 'Enter 4 to 8 digits first.',
};

function NumberField({ id, label, help, value, min, max, unit, onSave }) {
  const [text, setText] = useState(value === null || value === undefined ? '' : String(value));
  const [result, setResult] = useState(null);
  useEffect(() => { setText(value === null || value === undefined ? '' : String(value)); }, [value]);
  const commit = async () => {
    if (text === (value === null || value === undefined ? '' : String(value))) return;
    const checked = validateWhole(text, min, max);
    if (!checked.ok) { setResult({ tone: 'danger', text: checked.error }); return; }
    const failure = await onSave(checked.value);
    setResult(failure ? { tone: 'danger', text: failure } : { tone: 'ok', text: 'Saved.' });
  };
  return <div className={ROW}>
    <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
      <label htmlFor={id} className="text-sm text-ink-1">{label}</label>
      <span className="flex items-center gap-2">
        <input id={id} type="number" inputMode="numeric" min={min} max={max} step={1} value={text} className={`${FIELD} w-24 font-mono`}
          aria-describedby={`${id}-help ${id}-result`}
          onChange={event => { setText(event.target.value); setResult(null); }} onBlur={commit}
          onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); commit(); } }} />
        {unit && <span className="text-[0.75rem] text-ink-2">{unit}</span>}
      </span>
    </div>
    <p id={`${id}-help`} className={HELP}>{help}</p>
    <ResultMessage id={`${id}-result`} result={result} />
  </div>;
}

/** Call settings (calls.* through update_settings, plus the briefing PIN secret). */
export default function CallSettingsDialog({ settings, briefingPinSet, focus, onClose, onOpenSetup, onChanged }) {
  const ref = useRef(null);
  useDialogFocus(ref, onClose);
  const secrets = useMemo(() => createSecretsClient(socket), []);
  const [pin, setPin] = useState(null);
  const [results, setResults] = useState({});
  const [quiet, setQuiet] = useState(settings.quiet_hours);
  const [facts, setFacts] = useState(settings.facts);
  const [address, setAddress] = useState(settings.public_base_url);

  useEffect(() => () => secrets.dispose(), [secrets]);
  useEffect(() => { setQuiet(settings.quiet_hours); }, [settings.quiet_hours]);
  useEffect(() => { setFacts(settings.facts); }, [settings.facts]);
  useEffect(() => { setAddress(settings.public_base_url); }, [settings.public_base_url]);
  useEffect(() => {
    secrets.status().then(list => setPin(list.find(item => item.name === 'call_briefing_pin') || null)).catch(() => setPin(null));
  }, [secrets]);
  useEffect(() => {
    if (focus === 'public-address') requestAnimationFrame(() => { const field = document.getElementById('calls-public-address'); field?.focus(); field?.scrollIntoView({ block: 'center' }); });
  }, [focus]);

  // update_settings reports failures on the `error` event with the core's message.
  const patch = useCallback(async (calls) => {
    let message = '';
    const off = secrets.on('error', payload => { if (payload && typeof payload.msg === 'string') message = payload.msg; });
    try { await secrets.updateSettings({ calls }); onChanged?.(); return ''; }
    catch (error) { return message || rpcFailureMessage(error); }
    finally { off(); }
  }, [secrets, onChanged]);
  const save = async (field, calls, okText = 'Saved.') => {
    const failure = await patch(calls);
    setResults(current => ({ ...current, [field]: failure ? { tone: 'danger', text: failure } : { tone: 'ok', text: okText } }));
  };

  const saveQuiet = () => {
    if (quiet.start === settings.quiet_hours.start && quiet.end === settings.quiet_hours.end) return;
    if (!validTime(quiet.start) || !validTime(quiet.end)) { setResults(current => ({ ...current, quiet: { tone: 'danger', text: 'Enter both times as HH:MM.' } })); return; }
    save('quiet', { quiet_hours: { start: quiet.start, end: quiet.end } });
  };
  const saveFacts = () => { if (facts !== settings.facts) save('facts', { facts }); };
  const saveAddress = () => {
    const checked = validatePublicAddress(address);
    if (!checked.ok) { setResults(current => ({ ...current, address: { tone: 'danger', text: checked.error } })); return; }
    setAddress(checked.value);
    if (checked.value !== settings.public_base_url) save('address', { public_base_url: checked.value }, checked.value ? 'Address saved.' : 'Address cleared.');
  };
  const pinStatus = pin || (briefingPinSet === null ? undefined : { name: PIN.name, label: PIN.title, configured: briefingPinSet, source: briefingPinSet ? 'store' : null, hint: null, verified_at: null, last_check: briefingPinSet ? { ok: false, code: 'no_check', at: '' } : null });

  return <div className="dialog-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section ref={ref} className="feature-dialog calls-settings-dialog" role="dialog" aria-modal="true" aria-labelledby="calls-settings-title" tabIndex={-1}>
      <PanelHeader title="Call settings" titleId="calls-settings-title" eyebrow="CALLS" onClose={onClose} closeLabel="Close call settings" />
      <div className="calls-settings">
        <section className="flex flex-col gap-2" aria-labelledby="calls-settings-outgoing">
          <HudLabel as="h3" id="calls-settings-outgoing">OUTGOING CALLS</HudLabel>
          <div className={ROW}>
            <span id="calls-quiet-label" className="text-sm text-ink-1">Quiet hours</span>
            <div className="flex flex-wrap items-center gap-2" role="group" aria-labelledby="calls-quiet-label">
              <label className="flex items-center gap-2 text-[0.75rem] text-ink-2">From
                <input type="time" className={`${FIELD} font-mono`} value={quiet.start} aria-describedby="calls-quiet-result"
                  onChange={event => setQuiet(current => ({ ...current, start: event.target.value }))} onBlur={saveQuiet} /></label>
              <label className="flex items-center gap-2 text-[0.75rem] text-ink-2">to
                <input type="time" className={`${FIELD} font-mono`} value={quiet.end} aria-describedby="calls-quiet-result"
                  onChange={event => setQuiet(current => ({ ...current, end: event.target.value }))} onBlur={saveQuiet} /></label>
            </div>
            <p className={HELP}>JARVIS does not phone anyone but you during these hours. The same start and end time turns them off.</p>
            <ResultMessage id="calls-quiet-result" result={results.quiet} />
          </div>
          <NumberField id="calls-daily-cap" label="Daily outgoing call limit" min={0} max={100} value={settings.daily_outbound_cap}
            help="The most calls JARVIS may place to other people in a day." onSave={value => patch({ daily_outbound_cap: value })} />
          <NumberField id="calls-cooldown" label="Wait before calling the same number again" unit="minutes" min={0} max={10080} value={settings.number_cooldown_minutes}
            help="Stops JARVIS from calling one person over and over." onSave={value => patch({ number_cooldown_minutes: value })} />
          <NumberField id="calls-max-minutes" label="Longest call" unit="minutes" min={2} max={30} value={settings.max_call_minutes}
            help="JARVIS ends a call politely when it reaches this length." onSave={value => patch({ max_call_minutes: value })} />
        </section>

        <section className="flex flex-col gap-2" aria-labelledby="calls-settings-you">
          <HudLabel as="h3" id="calls-settings-you">YOU AND YOUR CALLERS</HudLabel>
          <div className={ROW}>
            <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
              <span id="calls-brief-label" className="text-sm text-ink-1">Phone briefings</span>
              <Segmented labelledBy="calls-brief-label" name="calls-brief" options={BRIEF_OPTIONS} value={settings.brief_by_phone}
                onChange={value => save('brief', { brief_by_phone: value })} />
            </div>
            <p className={HELP}>Whether JARVIS phones your mobile about a call: never, only for urgent ones, or whenever a call needs you.</p>
            <ResultMessage id="calls-brief-result" result={results.brief} />
          </div>
          <div className={ROW}>
            <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
              <span id="calls-disabled-label" className="text-sm text-ink-1">When calls are off</span>
              <Segmented labelledBy="calls-disabled-label" name="calls-when-disabled" options={WHEN_DISABLED_OPTIONS} value={settings.when_disabled}
                onChange={value => save('disabled', { when_disabled: value })} />
            </div>
            <p className={HELP}>What a forwarded caller hears while answering is off.</p>
            <ResultMessage id="calls-disabled-result" result={results.disabled} />
          </div>
          <div className={ROW}>
            <label htmlFor="calls-facts" className="text-sm text-ink-1">What JARVIS may tell callers</label>
            <textarea id="calls-facts" rows={5} maxLength={FACTS_LIMIT} value={facts} className={`${FIELD} w-full resize-y leading-relaxed`}
              placeholder="For example: Hiro is usually free after 6 pm." aria-describedby="calls-facts-help calls-facts-count calls-facts-result"
              onChange={event => { setFacts(event.target.value); setResults(current => ({ ...current, facts: null })); }} onBlur={saveFacts} />
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p id="calls-facts-help" className={HELP}>JARVIS shares only what you write here.</p>
              <span id="calls-facts-count" className="font-mono text-[0.75rem] text-ink-2">{`${facts.length.toLocaleString('en-US')} / ${FACTS_LIMIT.toLocaleString('en-US')}`}</span>
            </div>
            <ResultMessage id="calls-facts-result" result={results.facts} />
          </div>
          <SecretKeyRow idPrefix="calls-key" entry={PIN} status={pinStatus} client={secrets} onStatus={next => { setPin(next); onChanged?.(); }} />
        </section>

        <section className="flex flex-col gap-2" aria-labelledby="calls-settings-connection">
          <HudLabel as="h3" id="calls-settings-connection">CONNECTION</HudLabel>
          <div className={ROW}>
            <label htmlFor="calls-public-address" className="text-sm text-ink-1">Public address</label>
            <input id="calls-public-address" type="url" inputMode="url" spellCheck={false} autoComplete="off" value={address} className={`${FIELD} w-full font-mono`}
              placeholder="https://calls.example.com" aria-describedby="calls-address-help calls-address-result"
              onChange={event => { setAddress(event.target.value); setResults(current => ({ ...current, address: null })); }} onBlur={saveAddress}
              onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); saveAddress(); } }} />
            <p id="calls-address-help" className={HELP}>Your tunnel’s https address. It must match the start of the webhook addresses in Twilio exactly.</p>
            <ResultMessage id="calls-address-result" result={results.address} />
          </div>
          <div>
            <button type="button" className="btn btn--secondary btn--sm" onClick={onOpenSetup}>Open setup checklist</button>
          </div>
        </section>
      </div>
    </section>
  </div>;
}
