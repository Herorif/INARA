import React, { useEffect, useMemo, useState } from 'react';
import { Home } from 'lucide-react';
import socket from '../../services/socket';
import useStore from '../../store';
import StatusChip from '../../shared/ui/StatusChip';
import { createHomeClient } from './homeClient.js';
import { TOKEN_HELP, TOKEN_STEPS, URL_PLACEHOLDER, cardView } from './homeModel.js';
import './home.css';

/** "Home Assistant" on Connections (docs/HOME_ASSISTANT.md). The core owns the connection. */
export default function HomeAssistantCard() {
  const online = useStore((s) => s.backendConnected);
  const status = useStore((s) => s.homeStatus || null);
  const client = useMemo(() => createHomeClient(socket), []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [url, setUrl] = useState('');
  const [token, setToken] = useState('');
  const view = cardView(status, { busy, error, online, url, token });

  useEffect(() => () => client.dispose(), [client]);
  useEffect(() => {
    if (!online) return;
    client.status().then(async (value) => {
      useStore.setState({ homeStatus: value });
      if (value.url) setUrl((current) => current || value.url);
      // The device count is known after the first device read since the core started.
      if (value.connected && value.devices === null) {
        const { list, status: fresh } = await client.devices();
        useStore.setState({ homeStatus: fresh, homeDevices: list });
      }
    }).catch(() => {});
  }, [client, online]);

  const run = async (action) => {
    setBusy(true);
    setError('');
    try {
      const value = await action();
      if (value) useStore.setState({ homeStatus: value });
    } catch (failure) {
      setError(failure?.message || 'Home Assistant could not be changed. Try again.');
    } finally {
      setBusy(false);
    }
  };

  const connect = (event) => {
    event.preventDefault();
    if (view.connect?.disabled) return;
    run(async () => {
      const value = await client.connect(url, token);
      setToken('');
      return value;
    });
  };
  const disconnect = () => run(async () => {
    const value = await client.disconnect();
    useStore.setState({ homeDevices: null });
    if (value.url) setUrl(value.url);
    return value;
  });

  return <article className="home-card" data-account="home_assistant" data-phase={view.phase} aria-label="Home Assistant">
    <div className="connections-readiness__card-top">
      <h3 className="home-card__title"><Home size={16} aria-hidden="true" />Home Assistant</h3>
      <StatusChip tone={view.chip.tone} className="home-card__chip">{view.chip.label}</StatusChip>
    </div>
    {view.intro && <p>{view.intro}</p>}
    {view.account && <p className="home-card__account">{view.account}</p>}
    {view.legacy && <p className="home-card__legacy" role="status">{view.legacy}</p>}

    {view.form && <form className="home-card__form" onSubmit={connect} noValidate>
      <div className="home-card__fields">
        <label>
          <span>Server address</span>
          <input type="url" value={url} placeholder={URL_PLACEHOLDER} autoComplete="off" spellCheck={false}
            disabled={busy || !online} onChange={(event) => setUrl(event.target.value)} />
        </label>
        <label>
          <span>Long-lived access token</span>
          <input type="password" value={token} autoComplete="off" spellCheck={false}
            disabled={busy || !online} onChange={(event) => setToken(event.target.value)} />
        </label>
      </div>
      {view.httpNote && <p className="home-card__note">{view.httpNote}</p>}
      <details className="home-card__help">
        <summary>{TOKEN_HELP}</summary>
        <ol>{TOKEN_STEPS.map((step) => <li key={step}>{step}</li>)}</ol>
      </details>
      {view.error && <p className="connections-readiness__error home-card__error" role="alert">{view.error}</p>}
      <div className="home-card__actions">
        <button type="submit" className="btn btn--primary btn--sm" disabled={view.connect.disabled}>{view.connect.label}</button>
      </div>
    </form>}

    {!view.form && view.error && <p className="connections-readiness__error home-card__error" role="alert">{view.error}</p>}
    {view.disconnect && <div className="home-card__actions">
      <button type="button" className="btn btn--secondary btn--sm" disabled={view.disconnect.disabled}
        onClick={disconnect}>{view.disconnect.label}</button>
    </div>}
  </article>;
}
