import React, { useCallback, useEffect, useMemo, useState } from 'react';
import socket from '../../services/socket';
import { ResultMessage } from './SecretKeyRow';
import { rpcFailureMessage } from './aiSettingsModel';
import { createProactiveClient } from '../proactive/proactiveClient.js';
import {
  HEARTBEAT_HELP, HEARTBEAT_LABEL, HEARTBEAT_LOAD_ERROR, HEARTBEAT_ROWS, HEARTBEAT_SAVED,
  heartbeatTextError, lastCheckLine,
} from '../proactive/heartbeatModel.js';

const ROW = 'flex flex-col gap-2 rounded-md border border-line bg-raised px-3 py-2';
const HELP = 'text-[0.75rem] leading-relaxed text-ink-2';
const MUTED = 'text-[0.75rem] leading-snug text-ink-3';
const AREA = 'w-full rounded-md border border-line-strong bg-panel px-2 py-1.5 text-sm text-ink-1 font-mono';

/**
 * Preferences > Assistant (S7.3, docs/PROACTIVE.md "Heartbeat"): the owner's standing
 * instructions (HEARTBEAT.md, heartbeat_get / heartbeat_save) and the last check.
 */
export default function HeartbeatSettings() {
  const client = useMemo(() => createProactiveClient(socket), []);
  const [text, setText] = useState('');
  const [saved, setSaved] = useState(null);
  const [last, setLast] = useState({ lastRun: null, lastActions: [] });
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  useEffect(() => () => client.dispose(), [client]);

  const load = useCallback(() => {
    client.heartbeat().then((value) => {
      setSaved(value.text);
      setText(value.text);
      setLast({ lastRun: value.lastRun, lastActions: value.lastActions });
    }).catch(() => setResult({ tone: 'danger', text: HEARTBEAT_LOAD_ERROR }));
  }, [client]);

  useEffect(() => {
    load();
    return client.on('connect', load);
  }, [client, load]);

  const save = async (event) => {
    event.preventDefault();
    const error = heartbeatTextError(text);
    if (error) { setResult({ tone: 'danger', text: error }); return; }
    setBusy(true);
    try {
      const stored = await client.saveHeartbeat(text);
      setSaved(stored);
      setText(stored);
      setResult({ tone: 'ok', text: HEARTBEAT_SAVED });
    } catch (failure) {
      setResult({ tone: 'danger', text: rpcFailureMessage(failure) });
    } finally {
      setBusy(false);
    }
  };

  return <form className={ROW} data-assistant-heartbeat onSubmit={save}>
    <label htmlFor="assistant-heartbeat" className="text-sm text-ink-1">{HEARTBEAT_LABEL}</label>
    <textarea id="assistant-heartbeat" rows={HEARTBEAT_ROWS} spellCheck={false} className={AREA}
      value={text} disabled={saved === null || busy}
      aria-describedby="assistant-heartbeat-help assistant-heartbeat-last assistant-heartbeat-result"
      onChange={(event) => { setText(event.target.value); setResult(null); }} />
    <div className="flex flex-wrap items-center gap-2">
      <button type="submit" className="btn btn--primary btn--sm" disabled={saved === null || busy || text === saved}>
        {busy ? 'Saving…' : 'Save'}
      </button>
    </div>
    <p id="assistant-heartbeat-help" className={HELP}>{HEARTBEAT_HELP}</p>
    <p id="assistant-heartbeat-last" className={MUTED} data-heartbeat-last>{lastCheckLine(last.lastRun, last.lastActions)}</p>
    <ResultMessage id="assistant-heartbeat-result" result={result} />
  </form>;
}
