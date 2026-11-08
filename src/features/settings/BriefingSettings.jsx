import React, { useEffect, useMemo, useState } from 'react';
import { Loader2, Play } from 'lucide-react';
import socket from '../../services/socket';
import { createBriefingClient } from '../briefing/briefingClient';
import Switch from './Switch';
import { ResultMessage } from './SecretKeyRow';
import {
  ENABLED_LABEL, HEADING, PHONE_HELP, PHONE_LABEL, PHONE_TIME_LABEL, PLAY_LABEL, SPEAK_HELP, SPEAK_LABEL,
  briefingChoice, enabledHelp, phoneTimePatch, playResult, switchPatch, windowPatch,
} from './briefingSettingsModel';

const ROW = 'flex flex-col gap-2 rounded-md border border-line bg-raised px-3 py-2';
const HELP = 'text-[0.75rem] leading-relaxed text-ink-2';
const LINE = 'flex flex-wrap items-center justify-between gap-x-3 gap-y-2';
const FIELD = 'rounded-md border border-line-strong bg-panel px-2 py-1.5 text-sm text-ink-1 font-mono';
const TIME_LABEL = 'flex items-center gap-2 text-[0.75rem] text-ink-2';

/**
 * Preferences > Assistant > Morning briefing (P2). `briefing` is the saved settings.briefing;
 * `patch(settings)` saves through update_settings and resolves to '' or a failure message.
 * "Play today's briefing" works outside the briefing window too.
 */
export default function BriefingSettings({ briefing, patch }) {
  const client = useMemo(() => createBriefingClient(socket), []);
  const choice = briefingChoice(briefing);
  const [windowTimes, setWindowTimes] = useState({ start: choice.window_start, end: choice.window_end });
  const [phoneTime, setPhoneTime] = useState(choice.phone_time);
  const [results, setResults] = useState({});
  const [playing, setPlaying] = useState(false);

  useEffect(() => () => client.dispose(), [client]);
  useEffect(() => { setWindowTimes({ start: choice.window_start, end: choice.window_end }); }, [choice.window_start, choice.window_end]);
  useEffect(() => { setPhoneTime(choice.phone_time); }, [choice.phone_time]);

  const show = (key, result) => setResults(current => ({ ...current, [key]: result }));
  const save = async (key, next) => {
    if (!next) return;
    const failure = await patch(next);
    show(key, failure ? { tone: 'danger', text: failure } : null);
  };
  const toggle = key => save(key, switchPatch(choice, key, !choice[key]));
  const saveWindow = () => {
    const { patch: next, error } = windowPatch(choice, windowTimes.start, windowTimes.end);
    if (error) { show('enabled', { tone: 'danger', text: error }); return; }
    save('enabled', next);
  };
  const savePhoneTime = () => {
    const { patch: next, error } = phoneTimePatch(choice, phoneTime);
    if (error) { show('phone', { tone: 'danger', text: error }); return; }
    save('phone', next);
  };
  const play = async () => {
    setPlaying(true);
    show('play', null);
    try { show('play', playResult(await client.play())); }
    catch (error) { show('play', playResult(error)); }
    finally { setPlaying(false); }
  };

  return <div className="flex flex-col gap-2" data-briefing-settings>
    <h5 className="hud-label">{HEADING}</h5>
    <div className={ROW} data-briefing-row="enabled">
      <div className={LINE}>
        <span id="briefing-enabled-label" className="text-sm text-ink-1">{ENABLED_LABEL}</span>
        <Switch checked={choice.enabled} label={ENABLED_LABEL} onClick={() => toggle('enabled')} />
      </div>
      <p className={HELP}>{enabledHelp(choice)}</p>
      {choice.enabled && <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Briefing window">
        <label className={TIME_LABEL}>From
          <input type="time" className={FIELD} value={windowTimes.start} aria-describedby="briefing-enabled-result"
            onChange={event => setWindowTimes(current => ({ ...current, start: event.target.value }))} onBlur={saveWindow} /></label>
        <label className={TIME_LABEL}>to
          <input type="time" className={FIELD} value={windowTimes.end} aria-describedby="briefing-enabled-result"
            onChange={event => setWindowTimes(current => ({ ...current, end: event.target.value }))} onBlur={saveWindow} /></label>
      </div>}
      <ResultMessage id="briefing-enabled-result" result={results.enabled} />
    </div>
    <div className={ROW} data-briefing-row="speak">
      <div className={LINE}>
        <span className="text-sm text-ink-1">{SPEAK_LABEL}</span>
        <Switch checked={choice.speak} label={SPEAK_LABEL} onClick={() => toggle('speak')} />
      </div>
      <p className={HELP}>{SPEAK_HELP}</p>
      <ResultMessage id="briefing-speak-result" result={results.speak} />
    </div>
    <div className={ROW} data-briefing-row="phone">
      <div className={LINE}>
        <span className="text-sm text-ink-1">{PHONE_LABEL}</span>
        <Switch checked={choice.phone} label={PHONE_LABEL} onClick={() => toggle('phone')} />
      </div>
      <p className={HELP}>{PHONE_HELP}</p>
      {choice.phone && <label className={TIME_LABEL}>{PHONE_TIME_LABEL}
        <input type="time" className={FIELD} value={phoneTime} aria-describedby="briefing-phone-result"
          onChange={event => setPhoneTime(event.target.value)} onBlur={savePhoneTime} /></label>}
      <ResultMessage id="briefing-phone-result" result={results.phone} />
    </div>
    <div className="flex flex-col gap-1">
      <div>
        <button type="button" className="btn btn--secondary btn--sm" disabled={playing} onClick={play} aria-describedby="briefing-play-result">
          {playing ? <Loader2 size={14} aria-hidden="true" className="animate-spin" /> : <Play size={14} aria-hidden="true" />}<span>{PLAY_LABEL}</span>
        </button>
      </div>
      <ResultMessage id="briefing-play-result" result={results.play} />
    </div>
  </div>;
}
