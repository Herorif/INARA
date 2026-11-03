import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, PhoneCall, Settings2 } from 'lucide-react';
import useStore from '../../store';
import socket, { emitSocket } from '../../services/socket';
import PanelState from '../../app/PanelState';
import StatusChip from '../../shared/ui/StatusChip';
import HudLabel from '../../shared/ui/HudLabel';
import EmptyState from '../../shared/ui/EmptyState';
import { createCallsClient, isCallProgress, isRecordReady } from '../../transport/callsClient.ts';
import useCallsStatus, { refreshCallsStatus } from './useCallsStatus';
import CallsSetup from './CallsSetup';
import CallSettingsDialog from './CallSettingsDialog';
import { Switch } from './controls';
import {
  CALLBACK_LIMIT, DELETE_CONFIRM, FILTERS, ROLE_LABELS, answeringProblem, approveErrorMessage, callChip, callDateTime,
  callTitle, callsFailureMessage, callsSettings, detailMeta, emptyState, filterCalls, formatCallTime, messageRows,
  needsCallbackApproval, progressText, setupComplete, summaryText, urgencyChip,
} from './callsModel';
import './calls.css';

/** The saved settings snapshot (the core echoes it after every change). */
function useSettingsSnapshot(active) {
  const [snapshot, setSnapshot] = useState(null);
  useEffect(() => {
    if (!active) return undefined;
    const handle = value => { if (value && typeof value === 'object') setSnapshot(value); };
    const reconnect = () => emitSocket('get_settings');
    socket.on('settings', handle);
    socket.on('connect', reconnect);
    emitSocket('get_settings');
    return () => { socket.off('settings', handle); socket.off('connect', reconnect); };
  }, [active]);
  return snapshot;
}

function CallRow({ call, selected, onSelect }) {
  const chip = callChip(call);
  return <li>
    <button type="button" className={`calls-row ${selected ? 'is-selected' : ''}`} aria-pressed={selected} data-call={call.id} onClick={() => onSelect(call.id)}>
      <span className="calls-row__top">
        <strong className="calls-row__name">{callTitle(call)}</strong>
        <time className="calls-row__time" dateTime={callDateTime(call.started_at)}>{formatCallTime(call.started_at)}</time>
      </span>
      <span className="calls-row__bottom">
        <span className="calls-row__summary">{call.summary || 'No summary yet'}</span>
        <StatusChip tone={chip.tone}>{chip.label}</StatusChip>
      </span>
    </button>
  </li>;
}

function ApprovalCard({ call, client, quietHours, approval, progress, onApproval, onDismiss }) {
  const [draft, setDraft] = useState(approval.message ?? '');
  const [loading, setLoading] = useState(approval.message === undefined);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const callback = call.fields?.callback_number_masked;
  const raw = progressText(progress);
  // A completed callback whose record came back for another decision shows no stale "Completed".
  const line = raw && raw.done && progress.state === 'completed' && needsCallbackApproval(call) ? null : raw;
  const running = !!approval.callId && !(raw?.done);
  // Once the approved call has ended and the record moved on, only the outcome stays.
  const finished = !!approval.callId && !!raw?.done && !needsCallbackApproval(call);

  useEffect(() => {
    if (approval.message !== undefined) return undefined;
    let live = true;
    setLoading(true);
    client.callbackDraft(call.id)
      .then(message => { if (live) { setDraft(message); onApproval({ message }); } })
      .catch(failure => { if (live) { setError(callsFailureMessage(failure)); onApproval({ message: '' }); } })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [call.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const approve = async () => {
    setBusy(true); setError('');
    try {
      const callId = await client.approveCallback(call.id, draft.trim());
      onApproval({ message: draft, callId });
    } catch (failure) {
      setError(approveErrorMessage(failure?.code, quietHours, failure?.message) || callsFailureMessage(failure));
    } finally { setBusy(false); }
  };
  const dismiss = async () => {
    setBusy(true); setError('');
    try { await onDismiss(); } catch (failure) { setError(callsFailureMessage(failure)); setBusy(false); }
  };

  return <section className="calls-approval hud-panel hud-frame" aria-labelledby={`calls-approval-${call.id}`}>
    <HudLabel as="h3" id={`calls-approval-${call.id}`} className="calls-approval__label">APPROVAL NEEDED · OUTGOING CALL</HudLabel>
    <label htmlFor={`calls-callback-${call.id}`} className="calls-approval__prompt">
      Call back {callback ? <span className="calls-mono">{callback}</span> : 'the caller'} and say:
    </label>
    <textarea id={`calls-callback-${call.id}`} rows={4} maxLength={CALLBACK_LIMIT} value={draft} disabled={loading || busy || running}
      placeholder={loading ? 'Drafting a reply…' : 'What INARA should say'} aria-describedby={`calls-callback-${call.id}-count calls-callback-${call.id}-status`}
      onChange={event => { setDraft(event.target.value); onApproval({ message: event.target.value }); }} />
    <div className="calls-approval__meta">
      <span id={`calls-callback-${call.id}-count`} className="calls-count">{`${draft.length} / ${CALLBACK_LIMIT}`}</span>
    </div>
    <div id={`calls-callback-${call.id}-status`} aria-live="polite">
      {!callback && <p className="calls-note calls-note--warn">No callback number was given.</p>}
      {error && <p className="calls-note calls-note--danger" role="alert">{error}</p>}
      {line && <p className={`calls-progress calls-note--${line.tone}`} data-progress={progress.state}>
        {!line.done && <span className="progress-line" aria-hidden="true" />}<span>{line.text}</span></p>}
    </div>
    {!finished && <div className="calls-actions">
      <button type="button" className="btn btn--primary" disabled={!callback || loading || busy || running || !draft.trim()} onClick={approve}>Approve call</button>
      <button type="button" className="btn btn--ghost" disabled={busy || running} onClick={dismiss}>Dismiss</button>
    </div>}
  </section>;
}

function CallDetail({ call, client, quietHours, approval, progress, onApproval, onMarkDone, onDelete }) {
  const [transcript, setTranscript] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const confirmRef = useRef(null), deleteRef = useRef(null);
  const urgency = urgencyChip(call.triage?.urgency || call.urgency);
  const rows = messageRows(call);
  useEffect(() => { setTranscript(false); setConfirm(false); setError(''); }, [call.id]);
  useEffect(() => { if (confirm) confirmRef.current?.focus(); }, [confirm]);
  const run = async action => {
    setBusy(true); setError('');
    try { await action(); } catch (failure) { setError(callsFailureMessage(failure)); } finally { setBusy(false); }
  };

  return <article className="calls-detail" aria-labelledby="calls-detail-title">
    <header className="calls-detail__head">
      <div className="calls-detail__copy">
        <h2 id="calls-detail-title">{callTitle(call)}</h2>
        <p className="calls-detail__meta">{detailMeta(call)}</p>
      </div>
      {urgency && <StatusChip tone={urgency.tone}>{urgency.label}</StatusChip>}
    </header>
    <section className="calls-panel hud-panel" aria-labelledby="calls-summary-label">
      <HudLabel as="h3" id="calls-summary-label">SUMMARY</HudLabel>
      <p className={call.triage?.summary ? 'calls-panel__text' : 'calls-panel__text calls-muted'}>{summaryText(call)}</p>
    </section>
    {rows.length > 0 && <section className="calls-panel hud-panel" aria-labelledby="calls-message-label">
      <HudLabel as="h3" id="calls-message-label">MESSAGE</HudLabel>
      <dl className="calls-fields">{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
    </section>}
    {(needsCallbackApproval(call) || approval.callId) && <ApprovalCard key={call.id} call={call} client={client} quietHours={quietHours} approval={approval} progress={progress}
      onApproval={onApproval} onDismiss={onMarkDone} />}
    <section className="calls-panel hud-panel calls-transcript" aria-labelledby="calls-transcript-label">
      <button type="button" className="calls-transcript__toggle" aria-expanded={transcript} aria-controls="calls-transcript-body" onClick={() => setTranscript(value => !value)}>
        <HudLabel id="calls-transcript-label">TRANSCRIPT</HudLabel>
        <span className="calls-transcript__hint">{transcript ? 'Hide' : `Show ${call.transcript.length} ${call.transcript.length === 1 ? 'turn' : 'turns'}`}</span>
        <ChevronDown size={14} aria-hidden="true" className={transcript ? 'is-open' : ''} />
      </button>
      {transcript && <div id="calls-transcript-body" className="calls-transcript__body">
        {call.transcript.length ? call.transcript.map((turn, index) => <div key={index} className={`calls-turn calls-turn--${turn.role}`}>
          <HudLabel className="calls-turn__role">{ROLE_LABELS[turn.role]}</HudLabel>
          <p>{turn.text}</p>
        </div>) : <p className="calls-muted">No transcript was kept for this call.</p>}
      </div>}
    </section>
    <footer className="calls-detail__footer">
      {error && <p className="calls-note calls-note--danger" role="alert">{error}</p>}
      {!confirm ? <div className="calls-actions">
        {call.status !== 'done' && call.status !== 'in_progress' && <button type="button" className="btn btn--secondary" disabled={busy} onClick={() => run(onMarkDone)}>Mark done</button>}
        <button ref={deleteRef} type="button" className="btn btn--ghost calls-delete" disabled={busy || call.status === 'in_progress'} onClick={() => setConfirm(true)}>Delete record</button>
      </div> : <div className="calls-actions" role="group" aria-label="Delete call record">
        <span className="calls-confirm">{DELETE_CONFIRM}</span>
        <button ref={confirmRef} type="button" className="btn btn--danger btn--sm" disabled={busy} onClick={() => run(onDelete)}>Delete</button>
        <button type="button" className="btn btn--ghost btn--sm" disabled={busy} onClick={() => { setConfirm(false); requestAnimationFrame(() => deleteRef.current?.focus()); }}>Cancel</button>
      </div>}
    </footer>
  </article>;
}

/** Calls: what INARA answered and made, with callbacks waiting for approval. */
export default function CallsWorkspace() {
  const connected = useStore(state => state.backendConnected);
  const locked = useStore(state => state.isLockScreenVisible);
  const active = connected && !locked;
  const { status, error: statusError, loaded } = useCallsStatus(active);
  const snapshot = useSettingsSnapshot(active);
  const settings = useMemo(() => callsSettings(snapshot), [snapshot]);
  const client = useMemo(() => createCallsClient(socket), []);
  const [view, setView] = useState('calls');
  const [dialog, setDialog] = useState(null);
  const [filter, setFilter] = useState('needs_you');
  const [calls, setCalls] = useState(null);
  const [listError, setListError] = useState('');
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailError, setDetailError] = useState('');
  const [approvals, setApprovals] = useState({});
  const [progress, setProgress] = useState({});
  const [toggleNote, setToggleNote] = useState('');
  const [toggling, setToggling] = useState(false);
  const selectedRef = useRef(null);
  selectedRef.current = selected;
  const complete = setupComplete(status);
  const showSetup = !!status && (view === 'setup' || !complete);

  useEffect(() => () => client.dispose(), [client]);

  const loadList = useCallback(async () => {
    if (!socket.connected) return;
    try {
      const list = await client.list(filter);
      setCalls(list); setListError('');
      // Keep the open call even when it leaves this tab (approved, marked done), so its outcome stays visible.
      setSelected(current => current ?? list[0]?.id ?? null);
    } catch (failure) { setListError(callsFailureMessage(failure)); }
  }, [client, filter]);
  const loadDetail = useCallback(async id => {
    if (!id || !socket.connected) { setDetail(null); return; }
    try {
      const call = await client.get(id);
      if (selectedRef.current === id) { setDetail(call); setDetailError(''); }
    } catch (failure) {
      if (selectedRef.current !== id) return;
      setDetail(null);
      // Deleted elsewhere (or expired): drop the selection instead of showing an error.
      if (failure?.code === 'not_found') { setSelected(null); setDetailError(''); } else setDetailError(callsFailureMessage(failure));
    }
  }, [client]);

  useEffect(() => { if (active && status && !showSetup) { setCalls(null); loadList(); } }, [active, !!status, showSetup, loadList]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setDetail(current => current?.id === selected ? current : null); loadDetail(selected); }, [selected, loadDetail]);

  useEffect(() => {
    const offReady = client.on('call_record_ready', payload => {
      if (!isRecordReady(payload)) return;
      loadList();
      if (payload.record_id === selectedRef.current) loadDetail(payload.record_id);
    });
    const offProgress = client.on('call_progress', payload => {
      if (!isCallProgress(payload)) return;
      setProgress(current => ({ ...current, [payload.call_id]: payload }));
      if (['completed', 'no_answer', 'failed'].includes(payload.state)) { loadList(); if (selectedRef.current) loadDetail(selectedRef.current); }
    });
    const offConnect = client.on('connect', () => loadList());
    return () => { offReady(); offProgress(); offConnect(); };
  }, [client, loadList, loadDetail]);

  const patchApproval = useCallback((id, change) => setApprovals(current => ({ ...current, [id]: { ...current[id], ...change } })), []);
  const after = async () => { await Promise.all([loadList(), refreshCallsStatus(), loadDetail(selectedRef.current)]); };
  const markDone = async () => { await client.markDone(detail.id); await after(); };
  const remove = async () => { await client.remove(detail.id); setSelected(null); setDetail(null); await after(); };

  const toggleAnswering = async () => {
    if (!status || toggling) return;
    setToggleNote('');
    if (!status.enabled && !complete) { setView('setup'); setToggleNote('Finish the setup checklist to turn answering on.'); return; }
    setToggling(true);
    let message = '';
    const off = client.on('error', payload => { if (payload && typeof payload.msg === 'string') message = payload.msg; });
    try { await client.updateSettings({ calls: { enabled: !status.enabled } }); }
    catch (failure) { setToggleNote(message || callsFailureMessage(failure)); }
    finally { off(); }
    await refreshCallsStatus();
    // The gateway and tunnel start in the background; look again shortly.
    setTimeout(refreshCallsStatus, 2500);
    setToggling(false);
  };

  const problem = answeringProblem(status);
  const answering = !!status?.answering;
  const visible = filterCalls(calls, filter);
  const empty = emptyState(filter);

  const body = !connected ? <PanelState kind="offline" title="Core offline" detail="Reconnect to the core to see your calls." />
    : !loaded ? <PanelState kind="loading" title="Checking calls" />
      : statusError || !status ? <PanelState kind="error" title="Could not read call status" detail={callsFailureMessage(statusError)} action={refreshCallsStatus} actionLabel="Refresh" />
        : showSetup ? <CallsSetup status={status} onStatusChange={refreshCallsStatus} onOpenSettings={focus => setDialog({ focus })} onBack={complete ? () => { setView('calls'); setToggleNote(''); } : null} />
          : <div className="calls-body">
            <div className="calls-list-pane">
              <div className="calls-tabs hud-tabs" role="group" aria-label="Show calls">
                {FILTERS.map(entry => <button type="button" key={entry.id} className={`hud-tab ${filter === entry.id ? 'is-active' : ''}`} aria-pressed={filter === entry.id}
                  onClick={() => { if (entry.id !== filter) { setFilter(entry.id); setCalls(null); setSelected(null); } }}>{entry.label}</button>)}
              </div>
              {listError ? <PanelState compact kind="error" title="Could not load calls" detail={listError} action={loadList} actionLabel="Refresh" />
                : calls === null ? <PanelState compact kind="loading" title="Loading calls" />
                  : visible.length ? <ul className="calls-list" aria-label="Calls">{visible.map(call => <CallRow key={call.id} call={call} selected={call.id === selected} onSelect={setSelected} />)}</ul>
                    : <EmptyState className="calls-empty" icon={<PhoneCall />} title={empty.title} body={empty.body} />}
            </div>
            <div className="calls-detail-pane">
              {detail ? <CallDetail call={detail} client={client} quietHours={settings.quiet_hours} approval={approvals[detail.id] || {}}
                progress={progress[approvals[detail.id]?.callId]} onApproval={change => patchApproval(detail.id, change)} onMarkDone={markDone} onDelete={remove} />
                : detailError ? <PanelState compact kind="error" title="Could not open this call" detail={detailError} action={() => loadDetail(selected)} actionLabel="Try again" />
                  : selected ? <PanelState compact kind="loading" title="Opening call" />
                    : <EmptyState className="calls-empty" title="No call selected" body="Choose a call to see its summary and transcript." />}
            </div>
          </div>;

  return <section className="calls-workspace" aria-labelledby="calls-title">
    <div className="workspace-heading calls-heading">
      <div className="workspace-heading__copy"><h1 id="calls-title">Calls</h1><p>Calls INARA answered and made for you</p></div>
      {status && <div className="calls-heading__controls">
        <StatusChip tone={answering ? 'ok' : 'idle'} className="calls-answering-chip">{answering ? 'ANSWERING ON' : 'ANSWERING OFF'}</StatusChip>
        <Switch checked={status.enabled} label="Answering" disabled={toggling} describedBy="calls-toggle-note" onClick={toggleAnswering} />
        <button type="button" className="btn btn--secondary btn--sm" onClick={() => setDialog({ focus: null })}><Settings2 size={14} aria-hidden="true" />Call settings</button>
      </div>}
    </div>
    <div id="calls-toggle-note" aria-live="polite">
      {toggleNote && <p className="calls-banner">{toggleNote}</p>}
      {!toggleNote && problem && <p className="calls-banner">{`Answering is on, but INARA can't answer yet: ${problem}`}{' '}
        <button type="button" className="text-button" onClick={() => setView('setup')}>Open setup checklist</button></p>}
    </div>
    {body}
    {dialog && <CallSettingsDialog settings={settings} briefingPinSet={status?.briefing_pin_set ?? null} focus={dialog.focus}
      onClose={() => setDialog(null)} onChanged={refreshCallsStatus} onOpenSetup={() => { setDialog(null); setView('setup'); }} />}
  </section>;
}
