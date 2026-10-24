import React, { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, Bell, Inbox, ShieldCheck, RefreshCw, Smartphone } from 'lucide-react';
import useStore from '../store';
import socket from '../services/socket';
import { createMobileClient } from '../transport/mobileClient.ts';
import NotificationInbox from './NotificationInbox';
import PanelState from './PanelState';
import './mobile-companion.css';
import './inbox-workspace.css';

function ProjectInbox({ project, connected, locked, onOpen, embedded }) {
  const [report, setReport] = useState(null), [error, setError] = useState('');
  const [selected, setSelected] = useState(null), [refreshing, setRefreshing] = useState(false);
  const refresh = useRef(null);

  useEffect(() => {
    let live = true, inflight = false;
    setReport(null);
    setError('');
    if (!connected || locked) return;
    const client = createMobileClient(socket);
    const read = async () => {
      if (!socket.connected || inflight || !live) return;
      inflight = true;
      setRefreshing(true);
      try {
        const next = await client.state();
        if (live) {
          setReport(next);
          setError('');
        }
      } catch (failure) {
        if (live) {
          setReport(null);
          setError(failure.message);
        }
      } finally {
        inflight = false;
        if (live) setRefreshing(false);
      }
    };
    refresh.current = read;
    const off = client.on('disconnect', () => {
      setReport(null);
      setSelected(null);
    });
    read();
    const timer = setInterval(read, 4000);
    return () => {
      live = false;
      refresh.current = null;
      clearInterval(timer);
      off();
      client.dispose();
    };
  }, [project, connected, locked]);

  // Existing companion identities are the only source of device access.
  // Viewing this surface cannot open a listener, grant access or pair a phone.
  const devices = (connected && !locked ? report?.devices ?? [] : []).filter(device =>
    device.project === project && !device.revoked && device.expires > Date.now() / 1000);
  const device = devices.find(item => item.device_id === selected) ?? devices[0];

  if (locked) return null;
  return <section className="inbox-workspace" aria-labelledby={embedded ? undefined : 'inbox-title'} aria-label={embedded ? 'Inbox' : undefined}>
    <header className="inbox-workspace-heading">
      <div>
        {!embedded && <><span className="eyebrow">YOUR PRIVATE CHANNEL</span>
          <h1 id="inbox-title">Inbox<span>.</span></h1></>}
        {!embedded && <p>Selected signals from your phone, together in one place.</p>}
      </div>
      <button className="inbox-companion-link" onClick={() => onOpen?.('phone')}><Smartphone size={16} />Manage companion<ArrowUpRight size={15} /></button>
    </header>
    <div className="inbox-workspace-body">
      <aside className="inbox-sources" aria-label="Inbox sources">
        <div className="inbox-section-heading"><span>DEVICES</span><button aria-label="Refresh inbox sources" disabled={!connected || refreshing} onClick={() => refresh.current?.()}><RefreshCw size={15} /></button></div>
        {devices.length ? <div className="inbox-device-list">{devices.map(item => <button
          key={item.device_id}
          className={item.device_id === device?.device_id ? 'is-selected' : ''}
          aria-pressed={item.device_id === device?.device_id}
          onClick={() => setSelected(item.device_id)}
        >
          <Smartphone size={19} /><span><strong>{item.name}</strong><small>Paired · {item.project}</small></span><span className="inbox-device-signal" aria-hidden="true" />
        </button>)}</div> : <div className="inbox-no-source"><Smartphone size={22} /><span>{connected ? 'No active source' : 'Core offline'}</span></div>}
        <div className="inbox-privacy-note"><ShieldCheck size={17} /><strong>Yours to control</strong><p>Only selected notifications enter this project. Permission and retention are managed with your companion.</p></div>
        <div className="inbox-project"><span>ACTIVE PROJECT</span><strong>{project}</strong></div>
      </aside>
      <div className="inbox-stream-pane">
        {!connected
          ? <PanelState kind="offline" title="Your inbox is resting" detail="Reconnect to the core to view your paired sources and retained notifications." />
          : error
            ? <PanelState kind="error" title="Could not read your sources" detail={error} action={() => refresh.current?.()} actionLabel="Refresh sources" />
            : !report
              ? <PanelState kind="loading" title="Finding your sources" detail="Checking paired devices for this project." />
              : device
                ? <NotificationInbox key={`${project}:${device.device_id}`} device={device} project={project} readOnly />
                : <div className="inbox-empty">
                  <div className="inbox-empty-mark" aria-hidden="true"><Inbox size={34} strokeWidth={1.1} /><span><Bell size={14} /></span></div>
                  <span className="eyebrow">A QUIETER WAY TO CATCH UP</span>
                  <h2>Your signals start here.</h2>
                  <p>Connect your Android companion, then choose which notifications you want to see in this project.</p>
                  <button className="inbox-companion-link" onClick={() => onOpen?.('phone')}>Open companion<ArrowUpRight size={15} /></button>
                  <small>Phone setup and notification permission are separate steps.</small>
                </div>}
        <footer className="inbox-stream-footer"><ShieldCheck size={13} /><span>Read-only inbox · Replies and AI processing are off</span></footer>
      </div>
    </div>
  </section>;
}

export default function InboxWorkspace({ onOpen, embedded = false }) {
  const project = useStore(state => state.currentProject);
  const connected = useStore(state => state.backendConnected);
  const locked = useStore(state => state.isLockScreenVisible);
  // A project switch destroys all pending source reads and notification scopes.
  return <ProjectInbox key={project} project={project} connected={connected} locked={locked} onOpen={onOpen} embedded={embedded} />;
}
