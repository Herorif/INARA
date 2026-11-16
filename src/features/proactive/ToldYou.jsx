import React, { useCallback, useEffect, useMemo, useState } from 'react';
import socket from '../../services/socket';
import useStore from '../../store';
import HudLabel from '../../shared/ui/HudLabel';
import { createProactiveClient } from './proactiveClient.js';
import {
  LOAD_ERROR, MUTE_ERROR, MUTE_LABEL, MUTES_EMPTY, MUTES_HEADING, TOLD_EMPTY, TOLD_NOTE, UNMUTE_ERROR,
  muteLabel, muteRequest, toldRows,
} from './proactiveModel.js';
import './proactive.css';

/** Activity drawer tab "Told you" (S7.2): what JARVIS told the owner on its own, and the mutes. */
export default function ToldYou() {
  const online = useStore(state => state.backendConnected);
  const client = useMemo(() => createProactiveClient(socket), []);
  const [deliveries, setDeliveries] = useState([]);
  const [mutes, setMutes] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => () => client.dispose(), [client]);

  const load = useCallback(async () => {
    try {
      const [recent, rules] = await Promise.all([client.recent(), client.mutes()]);
      setDeliveries(recent); setMutes(rules); setLoaded(true); setError('');
    } catch { setError(LOAD_ERROR); }
  }, [client]);

  useEffect(() => { if (online) load(); }, [online, load]);
  useEffect(() => client.on('proactive_delivered', () => { load(); }), [client, load]);

  const mute = async item => {
    setBusy(true); setError('');
    try {
      const rule = await client.mute(muteRequest(item));
      if (rule) setMutes(current => current.some(entry => entry.id === rule.id) ? current : [...current, rule]);
    } catch { setError(MUTE_ERROR); }
    finally { setBusy(false); }
  };
  const unmute = async rule => {
    setBusy(true); setError('');
    try { await client.unmute(rule.id); setMutes(current => current.filter(entry => entry.id !== rule.id)); }
    catch { setError(UNMUTE_ERROR); }
    finally { setBusy(false); }
  };

  const rows = toldRows(deliveries, mutes);
  return <div className="told-you" data-told-you>
    <p className="trace-note">{TOLD_NOTE}</p>
    {error && <p className="trace-error" role="alert">{error}</p>}
    {loaded && !rows.length && !error && <p className="trace-empty">{TOLD_EMPTY}</p>}
    {!!rows.length && <ul className="trace-list" aria-label="What JARVIS told you, newest first">
      {rows.map(row => <li key={row.id} className="told-row" data-channel={row.channel}>
        <span className="trace-row__time">{row.time}</span>
        <span className="told-row__text">
          <span className="told-row__title">{row.title}</span>
          <span className="told-row__meta">{`${row.kindText} · ${row.channelText}`}</span>
        </span>
        <span className="told-row__action">{row.muted
          ? <span className="told-muted">Muted</span>
          : <button type="button" className="text-button" disabled={busy} onClick={() => mute(row)}>{MUTE_LABEL}</button>}</span>
      </li>)}
    </ul>}
    <div className="told-mutes">
      <HudLabel className="told-mutes__heading">{MUTES_HEADING.toUpperCase()}</HudLabel>
      {mutes.length ? <ul className="trace-list" aria-label="Muted">
        {mutes.map(rule => <li key={rule.id} className="told-row">
          <span className="told-row__text"><span className="told-row__title">{muteLabel(rule)}</span></span>
          <span className="told-row__action"><button type="button" className="text-button" disabled={busy} onClick={() => unmute(rule)}>Unmute</button></span>
        </li>)}
      </ul> : loaded && <p className="trace-empty">{MUTES_EMPTY}</p>}
    </div>
  </div>;
}
