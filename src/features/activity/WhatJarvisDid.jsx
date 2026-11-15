import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import socket from '../../services/socket';
import useStore from '../../store';
import { createActivityClient } from './activityClient.js';
import {
  CLEAR_ERROR, EMPTY_TEXT, FIRST_PAGE, KEPT_NOTE, LIVE_FETCH, LOAD_ERROR, TRACE_LIMIT,
  canLoadMore, mergeTraces, traceRow, waterfall,
} from './activityModel.js';
import './activity.css';

function Waterfall({ trace }) {
  const view = waterfall(trace);
  if (!view.rows.length) return null;
  return <ol className="trace-waterfall" aria-label="Steps on a shared time axis">
    {view.rows.map((row, index) => <li key={index} className="trace-span" data-role={row.role}>
      <span className="trace-span__label">{row.label}</span>
      <span className="trace-span__offset">{row.offset || '—'}</span>
      <span className="trace-span__track" aria-hidden="true">
        {view.zero !== null && <span className="trace-span__zero" style={{ left: `${view.zero}%` }}/>}
        {row.bar && <span className="trace-span__bar" style={{ left: `${row.bar.left}%`, width: `${row.bar.width}%` }}/>}
      </span>
      <span className="trace-span__duration">{row.duration || '—'}</span>
    </li>)}
  </ol>;
}

function TraceRow({ trace, open, onToggle }) {
  const row = traceRow(trace);
  const detailsId = `trace-details-${row.id}`;
  return <li className="trace-item" data-outcome={trace.outcome || ''}>
    <button type="button" className="trace-row" aria-expanded={open} aria-controls={open ? detailsId : undefined} onClick={onToggle}>
      <span className="trace-row__line">
        <span className="trace-row__time">{row.time}</span>
        <span className="trace-row__origin">{row.origin}</span>
        <span className="trace-row__summary">{row.summary}</span>
        <span className="trace-row__total">{row.total}</span>
        <span className="trace-row__outcome" data-tone={row.outcome.tone}>
          <span className={row.outcome.tone === 'idle' ? 'status-dot' : `status-dot status-dot--${row.outcome.tone}`} aria-hidden="true"/>
          {row.outcome.quiet ? <span className="trace-sr">{row.outcome.label}</span> : <span>{row.outcome.label}</span>}
        </span>
      </span>
      {row.request && <span className="trace-row__request">{row.request}</span>}
    </button>
    {open && <div id={detailsId} className="trace-details">
      <Waterfall trace={trace}/>
      <dl className="trace-meta">
        {row.brain && <div><dt>Brain</dt><dd>{row.brain}</dd></div>}
        {row.tokens && <div><dt>Tokens</dt><dd>{row.tokens}</dd></div>}
        {row.cost && <div><dt>Estimated cost</dt><dd>{row.cost}</dd></div>}
      </dl>
      {!!row.approvals.length && <ul className="trace-approvals">{row.approvals.map((line, index) => <li key={index}>{line}</li>)}</ul>}
    </div>}
  </li>;
}

/** Activity drawer tab "What JARVIS did": the flight recorder's turns, newest first. */
export default function WhatJarvisDid() {
  const online = useStore(state => state.backendConnected);
  const client = useMemo(() => createActivityClient(socket), []);
  const [traces, setTraces] = useState([]);
  const [requested, setRequested] = useState(FIRST_PAGE);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [open, setOpen] = useState(() => new Set());
  const [confirming, setConfirming] = useState(false);
  const clearRef = useRef(null);

  useEffect(() => () => client.dispose(), [client]);

  const load = useCallback(async limit => {
    setBusy(true);
    setError('');
    try {
      const fresh = await client.recent(limit);
      setTraces(mergeTraces([], fresh));
      setRequested(limit);
      setLoaded(true);
    } catch {
      setError(LOAD_ERROR);
    } finally {
      setBusy(false);
    }
  }, [client]);

  useEffect(() => { if (online) load(FIRST_PAGE); }, [online, load]);

  useEffect(() => client.onAdded(() => {
    client.recent(LIVE_FETCH).then(fresh => setTraces(list => mergeTraces(list, fresh))).catch(() => {});
  }), [client]);

  const toggle = id => setOpen(current => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const clear = async () => {
    setBusy(true);
    setError('');
    try {
      await client.clear();
      setTraces([]);
      setOpen(new Set());
      setRequested(FIRST_PAGE);
    } catch {
      setError(CLEAR_ERROR);
    } finally {
      setBusy(false);
      setConfirming(false);
      requestAnimationFrame(() => clearRef.current?.focus());
    }
  };

  return <div className="what-jarvis-did">
    <div className="trace-header">
      <p className="trace-note">{KEPT_NOTE}</p>
      {confirming
        ? <span className="trace-confirm" role="group" aria-label="Clear the list">
          <span>Clear the list?</span><span aria-hidden="true">·</span>
          <button type="button" className="text-button trace-confirm__clear" disabled={busy} onClick={clear}>Clear</button>
          <span aria-hidden="true">·</span>
          <button type="button" className="text-button" autoFocus onClick={() => { setConfirming(false); requestAnimationFrame(() => clearRef.current?.focus()); }}>Cancel</button>
        </span>
        : <button ref={clearRef} type="button" className="text-button" disabled={busy || !traces.length} onClick={() => setConfirming(true)}>Clear</button>}
    </div>
    {error && <p className="trace-error" role="alert">{error}</p>}
    {loaded && !traces.length && !error && <p className="trace-empty">{EMPTY_TEXT}</p>}
    {!!traces.length && <ul className="trace-list" aria-label="What JARVIS did, newest first">
      {traces.map(trace => <TraceRow key={trace.id} trace={trace} open={open.has(trace.id)} onToggle={() => toggle(trace.id)}/>)}
    </ul>}
    {loaded && canLoadMore(traces.length, requested) && <button type="button" className="text-button trace-more" disabled={busy} onClick={() => load(TRACE_LIMIT)}>Load more</button>}
  </div>;
}
