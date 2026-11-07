import React, { useEffect, useMemo, useState } from 'react';
import { CalendarDays, ExternalLink } from 'lucide-react';
import socket from '../../services/socket';
import useStore from '../../store';
import StatusChip from '../../shared/ui/StatusChip';
import { createCalendarClient } from './calendarClient.js';
import { CONSOLE_URL, SETUP_STEPS, cardView, safeAuthUrl, setupReady } from './calendarModel.js';
import './google-calendar-card.css';

const openExternal = (url) => {
  const open = window.electronAPI?.openExternal;
  if (typeof open !== 'function') return false;
  open(url);
  return true;
};

const CalendarSwitch = ({ row, onToggle }) => {
  const labelId = `calendar-switch-${row.id}`;
  return <div className="calendar-card__switch-row">
    <div>
      <span id={labelId} className="calendar-card__switch-label">{row.label}</span>
      <span className="calendar-card__switch-detail">{row.detail}</span>
    </div>
    <button type="button" role="switch" aria-checked={row.checked} aria-labelledby={labelId} disabled={row.disabled}
      className={`calendar-card__switch ${row.checked ? 'is-on' : ''}`} onClick={() => onToggle(row.id, !row.checked)}>
      <span aria-hidden="true" />
    </button>
  </div>;
};

/** "Google Calendar" on Connections (docs/CALENDAR.md). The core owns the connection. */
export default function GoogleCalendarCard() {
  const online = useStore((s) => s.backendConnected);
  const status = useStore((s) => s.calendarStatus || null);
  const client = useMemo(() => createCalendarClient(socket), []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');
  const view = cardView(status, { busy, error, online });

  useEffect(() => () => client.dispose(), [client]);
  useEffect(() => {
    if (!online) return;
    client.status().then((value) => useStore.setState({ calendarStatus: value })).catch(() => {});
  }, [client, online]);

  const run = async (action) => {
    setBusy(true);
    setError('');
    try {
      const value = await action();
      if (value) useStore.setState({ calendarStatus: value });
    } catch (failure) {
      setError(failure?.message || 'Google Calendar could not be changed. Try again.');
    } finally {
      setBusy(false);
    }
  };

  const connect = () => run(async () => {
    const { status: value, authUrl } = await client.connect();
    const url = safeAuthUrl(authUrl);
    if (!url || !openExternal(url)) {
      const stopped = await client.cancel().catch(() => value);
      useStore.setState({ calendarStatus: stopped });
      throw new Error("JARVIS couldn't open your browser for Google sign-in. Try again from the JARVIS desktop app.");
    }
    return value;
  });
  const saveClient = () => run(async () => {
    const value = await client.saveClient(clientId, clientSecret);
    setClientId('');
    setClientSecret('');
    return value;
  });

  return <article className="calendar-card" data-account="google_calendar" data-phase={view.phase} aria-label="Google Calendar">
    <div className="connections-readiness__card-top">
      <h3 className="calendar-card__title"><CalendarDays size={16} aria-hidden="true" />Google Calendar</h3>
      <StatusChip tone={view.chip.tone} className="calendar-card__chip">{view.chip.label}</StatusChip>
    </div>
    {view.intro && <p>{view.intro}</p>}
    {view.account && <p className="calendar-card__account">{view.account}</p>}

    {view.setup && <section className="calendar-card__setup" aria-labelledby="calendar-setup-title">
      <h4 id="calendar-setup-title">One-time setup</h4>
      <div className="calendar-card__fields">
        <label>
          <span>Client ID</span>
          <input type="text" value={clientId} autoComplete="off" spellCheck={false} disabled={busy || !online}
            onChange={(event) => setClientId(event.target.value)} />
        </label>
        <label>
          <span>Client secret</span>
          <input type="password" value={clientSecret} autoComplete="off" spellCheck={false} disabled={busy || !online}
            onChange={(event) => setClientSecret(event.target.value)} />
        </label>
        <button type="button" className="btn btn--secondary btn--sm" disabled={busy || !online || !setupReady(clientId, clientSecret)}
          onClick={saveClient}>Save</button>
      </div>
      <details className="calendar-card__help">
        <summary>How to get these</summary>
        <ol>{SETUP_STEPS.map((step) => <li key={step}>{step}</li>)}</ol>
        <button type="button" className="btn btn--ghost btn--sm" onClick={() => openExternal(CONSOLE_URL)}>
          <ExternalLink size={14} aria-hidden="true" /><span>Open Google Cloud Console</span>
        </button>
      </details>
    </section>}

    {view.switches.length > 0 && <div className="calendar-card__switches">
      {view.switches.map((row) => <CalendarSwitch key={row.id} row={row}
        onToggle={(id, value) => run(() => client.setSwitch(id, value))} />)}
    </div>}

    {view.waiting && <div className="calendar-card__waiting" role="status">
      <span>{view.waiting.text}</span>
      <button type="button" className="btn btn--secondary btn--sm" disabled={view.waiting.disabled}
        onClick={() => run(() => client.cancel())}>{view.waiting.cancel}</button>
    </div>}

    {view.error && <p className="connections-readiness__error calendar-card__error" role="alert">{view.error}</p>}

    {(view.connect || view.disconnect) && <div className="calendar-card__actions">
      {view.connect && <button type="button" className="btn btn--primary btn--sm" disabled={view.connect.disabled}
        onClick={connect}>{view.connect.label}</button>}
      {view.disconnect && <button type="button" className="btn btn--secondary btn--sm" disabled={view.disconnect.disabled}
        onClick={() => run(() => client.disconnect())}>{view.disconnect.label}</button>}
    </div>}
  </article>;
}
