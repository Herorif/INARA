import React, { useEffect, useRef, useState } from 'react';
import { Bell, ShieldCheck, RefreshCw } from 'lucide-react';
import socket from '../services/socket';
import useStore from '../store';
import { createNotificationClient } from '../transport/notificationClient.ts';
import PanelState from './PanelState';
export default function NotificationInbox({
  device,
  project,
  readOnly = false
}) {
  const connected = useStore(state => state.backendConnected),
    locked = useStore(state => state.isLockScreenVisible),
    generation = useRef(0);
  const client = useRef(null),
    [report, setReport] = useState(null),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false);
  const [rules, setRules] = useState(''),
    [includeText, setIncludeText] = useState(false),
    [hours, setHours] = useState(24),
    [editing, setEditing] = useState(false);
  useEffect(() => {
    let live = true;
    const current = ++generation.current;
    setReport(null);
    setEditing(false);
    setError('');
    setBusy(false);
    if (!connected || locked || device.project !== project || device.revoked) return;
    const value = createNotificationClient(socket, device.device_id);
    client.current = value;
    value.read().then(next => {
      if (live && generation.current === current) {
        if (next.project !== project) throw new Error('The inbox belongs to a different project. Reopen your companion connection.');
        setReport(next);
        setRules(next.policy.rules.map(rule => `${rule.package} ${rule.all_conversations ? '*' : rule.conversations.join(',')}`).join('\n'));
        setIncludeText(next.policy.include_text);
        setHours(next.policy.retention_hours);
      }
    }).catch(failure => {
      if (live && generation.current === current) setError(failure.message);
    });
    const off = value.on('disconnect', () => {
      setReport(null);
      setEditing(false);
    });
    return () => {
      live = false;
      generation.current++;
      client.current = null;
      off();
      value.dispose();
    };
  }, [device.device_id, device.project, device.revoked, project, connected, locked]);
  const act = async action => {
    if (!connected || locked || !client.current) return;
    const current = generation.current;
    setBusy(true);
    setError('');
    try {
      const next = await action();
      if (generation.current === current) {
        if (next.project !== project) throw new Error('The inbox belongs to a different project. Reopen your companion connection.');
        setReport(next);
      }
    } catch (failure) {
      if (generation.current === current) setError(failure.message);
    } finally {
      if (generation.current === current) setBusy(false);
    }
  };
  const configure = enabled => {
    if (readOnly) return;
    return act(() => {
      const selected = rules.trim() ? rules.trim().split('\n').map(line => {
        const parts = line.trim().split(/\s+/);
        if (parts.length !== 2) throw new Error('Each line needs a package and * or comma-separated conversation IDs.');
        return {
          package: parts[0],
          all_conversations: parts[1] === '*',
          conversations: parts[1] === '*' ? [] : parts[1].split(',')
        };
      }) : [];
      return client.current.configure({
        enabled,
        include_text: includeText,
        retention_hours: Number(hours),
        rules: selected
      });
    });
  };
  if (locked || device.project !== project || device.revoked) return null;
  return <section className={`notification-inbox ${readOnly ? 'notification-inbox--readonly' : ''}`} aria-label={`Read-only inbox for ${device.name}`}>
    <div className="mobile-card-heading"><Bell size={18} /><strong>{readOnly ? 'Notification stream' : 'Selected signals'}</strong><span className="notification-badge">READ ONLY</span></div>
    {error && <PanelState kind="error" title="Inbox interrupted" detail={error} action={() => act(() => client.current.read())} actionLabel="Refresh inbox" />}
    {!connected && <PanelState compact kind="offline" title="Core offline" detail="Your inbox will be available when the core reconnects." />}
    {connected && !report && !error && <PanelState kind="loading" title="Opening your inbox" detail="Reading selected notifications for this project." />}
    {!readOnly && <p>Separate permission for this device and project. Phone collection stays off until native build/device acceptance and your explicit permission.</p>}
    {connected && report && <><div className="notification-summary"><span>{String(report.summary.total).padStart(2, '0')}</span><div><strong>Notifications retained</strong><small>Local counts / no AI provider / {report.policy.retention_hours}h retention</small></div><ShieldCheck size={20} /></div>
      <div className="notification-actions"><button disabled={busy} onClick={() => act(() => client.current.read())}><RefreshCw size={14} />Refresh inbox</button>{!readOnly && <><button disabled={busy} onClick={() => setEditing(!editing)}>{editing ? 'Close policy' : 'Review permission'}</button><button disabled={busy} onClick={() => act(() => client.current.clear())}>Clear laptop inbox</button></>}</div>
      <p className="notification-status">{report.policy.enabled ? 'Notification grant enabled' : 'Notification grant off'} / {report.policy.include_text ? 'Redacted text allowed' : 'Metadata only'}</p>
      {!readOnly && editing && <div className="notification-policy"><label>Selected packages and conversation scope<textarea aria-label="Notification application and conversation rules" rows={4} placeholder={'com.example.messages *\ncom.example.chat 64-character-conversation-hash'} value={rules} onChange={event => setRules(event.target.value)} /></label><small>One package per line. Use * only to explicitly select all conversations in that app; otherwise paste IDs shown on the phone. No app is selected by default.</small><label>Retention hours (1-168)<input type="number" min="1" max="168" value={hours} onChange={event => setHours(event.target.value)} /></label><label className="mobile-check"><input type="checkbox" checked={includeText} onChange={event => setIncludeText(event.target.checked)} />Allow redacted titles/text (may still contain personal details)</label><p>Applying any policy clears retained content and invalidates the phone queue. Revoking clears the laptop copy. Clearing here never dismisses anything on your phone.</p><button disabled={busy || device.revoked} onClick={() => configure(true)}>Apply selected permission</button><button disabled={busy} onClick={() => act(() => client.current.configure({
          enabled: false,
          include_text: false,
          retention_hours: 24,
          rules: []
        }))}>Revoke notification permission</button></div>}
      {!report.items.length ? <p className="notification-empty">Quiet channel. Only explicitly synced, selected notifications appear here.</p> : <ol className="notification-stream">{report.items.map(item => <li key={item.source_id}><div><strong>{item.package}</strong><time>{new Date(item.timestamp * 1000).toLocaleString()}</time></div><h4>{item.title || 'Selected notification'}</h4><p>{item.text || 'Content withheld / metadata only'}</p><code>Conversation / {item.conversation}</code></li>)}</ol>}
    </>}
    <small>No replies, drafts, acknowledgements, notification actions or cloud summaries.</small>
  </section>;
}
