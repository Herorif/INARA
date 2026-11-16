import React, { useEffect, useState } from 'react';
import Switch from './Switch';
import SegmentedControl from './SegmentedControl';
import { ResultMessage } from './SecretKeyRow';
import {
  CHATTY_LABEL, CHATTY_OPTIONS, QUIET_HELP, QUIET_LABEL, QUIET_OFF_HELP,
  chattinessPatch, chattyHelp, proactiveChoice, quietHoursPatch, quietSwitchPatch,
} from '../proactive/proactiveModel.js';

const ROW = 'flex flex-col gap-2 rounded-md border border-line bg-raised px-3 py-2';
const HELP = 'text-[0.75rem] leading-relaxed text-ink-2';
const LINE = 'flex flex-wrap items-center justify-between gap-x-3 gap-y-2';
const FIELD = 'rounded-md border border-line-strong bg-panel px-2 py-1.5 text-sm text-ink-1 font-mono';
const TIME_LABEL = 'flex items-center gap-2 text-[0.75rem] text-ink-2';

/**
 * Preferences > Assistant (S7.2, docs/PROACTIVE.md): "How chatty" (assistant.chattiness) and
 * "Quiet hours" (assistant.quiet_hours, null when off). `patch(settings)` resolves to '' or a
 * failure message.
 */
export default function ProactiveSettings({ assistant, patch }) {
  const choice = proactiveChoice(assistant);
  const quiet = choice.quiet_hours;
  const [times, setTimes] = useState(() => quiet || { start: '22:30', end: '07:00' });
  const [results, setResults] = useState({});
  useEffect(() => { if (quiet) setTimes({ start: quiet.start, end: quiet.end }); }, [quiet?.start, quiet?.end]); // eslint-disable-line react-hooks/exhaustive-deps

  const show = (key, result) => setResults(current => ({ ...current, [key]: result }));
  const save = async (key, next) => {
    if (!next) return;
    const failure = await patch(next);
    show(key, failure ? { tone: 'danger', text: failure } : null);
  };
  const saveTimes = () => {
    const { patch: next, error } = quietHoursPatch(choice, times.start, times.end);
    if (error) { show('quiet', { tone: 'danger', text: error }); return; }
    save('quiet', next);
  };

  return <>
    <div className={ROW} data-assistant-chattiness>
      <div className={LINE}>
        <span id="assistant-chattiness-label" className="text-sm text-ink-1">{CHATTY_LABEL}</span>
        <SegmentedControl name="assistant-chattiness" options={CHATTY_OPTIONS} value={choice.chattiness}
          onChange={next => save('chattiness', chattinessPatch(choice, next))}
          aria-labelledby="assistant-chattiness-label" aria-describedby="assistant-chattiness-help" />
      </div>
      <p id="assistant-chattiness-help" className={HELP}>{chattyHelp(choice.chattiness)}</p>
      <ResultMessage id="assistant-chattiness-result" result={results.chattiness} />
    </div>
    <div className={ROW} data-assistant-quiet-hours>
      <div className={LINE}>
        <span className="text-sm text-ink-1">{QUIET_LABEL}</span>
        <Switch checked={quiet !== null} label={QUIET_LABEL} onClick={() => save('quiet', quietSwitchPatch(choice, quiet === null))} />
      </div>
      <p className={HELP}>{quiet ? QUIET_HELP : QUIET_OFF_HELP}</p>
      {quiet && <div className="flex flex-wrap items-center gap-2" role="group" aria-label={QUIET_LABEL}>
        <label className={TIME_LABEL}>From
          <input type="time" className={FIELD} value={times.start} aria-describedby="assistant-quiet-result"
            onChange={event => setTimes(current => ({ ...current, start: event.target.value }))} onBlur={saveTimes} /></label>
        <label className={TIME_LABEL}>to
          <input type="time" className={FIELD} value={times.end} aria-describedby="assistant-quiet-result"
            onChange={event => setTimes(current => ({ ...current, end: event.target.value }))} onBlur={saveTimes} /></label>
      </div>}
      <ResultMessage id="assistant-quiet-result" result={results.quiet} />
    </div>
  </>;
}
