import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ExternalLink, Globe, Square } from 'lucide-react';
import socket from '../../services/socket';
import useStore from '../../store';
import HudLabel from '../../shared/ui/HudLabel';
import StatusChip from '../../shared/ui/StatusChip';
import PresenceRing from '../../app/PresenceRing';
import { createWorldClient } from './worldClient.js';
import { createWorldBridge } from './worldBridge.js';
import { HEARTBEAT_MS, SETUP_STEPS, appUrl, pageView } from './worldModel.js';
import './world.css';

// The embedded globe needs scripts and its own origin (its workers and storage); it may not
// navigate JARVIS, open windows or use devices. JARVIS never asks for any device for it.
const SANDBOX = 'allow-scripts allow-same-origin';
const ALLOW = "camera 'none'; microphone 'none'; geolocation 'none'; display-capture 'none'";

/**
 * World (Studio): the God's Eye View globe running on this PC (docs/WORLD_VIEW.md). Opening
 * the page starts the sidecar; the page reports in while open so the core keeps it running.
 * Views the core pushes (world_view) go to the globe through the message bridge.
 */
export default function WorldPage({ onClose }) {
  const connected = useStore(state => state.backendConnected);
  const status = useStore(state => state.worldStatus);
  const tour = useStore(state => state.worldTour);
  const views = useStore(state => state.worldViews);
  const [failure, setFailure] = useState(null);
  const [busy, setBusy] = useState(false);
  const client = useRef(null);
  const frame = useRef(null);
  const view = pageView({ status, tour, failure });

  // Open: report in, start the globe if it isn't running, keep reporting in; closed on unmount.
  useEffect(() => {
    const world = createWorldClient(socket);
    client.current = world;
    let live = true;
    const apply = value => { if (live) useStore.setState({ worldStatus: value, worldTour: value.tour }); };
    const fail = error => { if (live) setFailure(error.message); };
    if (connected) {
      setFailure(null);
      world.status(true).then(value => {
        apply(value);
        if (value.state === 'stopped' || value.state === 'error') return world.start().then(apply);
        return undefined;
      }).catch(fail);
    }
    const timer = setInterval(() => { if (connected) world.status(true).then(apply).catch(() => {}); }, HEARTBEAT_MS);
    return () => {
      live = false;
      clearInterval(timer);
      // The closing report is sent at once; disposing only drops its reply.
      if (socket.connected) world.status(false).catch(() => {});
      world.dispose();
    };
  }, [connected]);

  // One bridge per embedded globe.
  const bridge = useMemo(() => (view.frameUrl ? createWorldBridge({
    origin: view.origin,
    target: () => frame.current?.contentWindow || null,
    onApplied: ({ id, ok, steps }) => { client.current?.viewResult(id, ok, steps).catch(() => {}); },
  }) : null), [view.frameUrl, view.origin]);

  useEffect(() => {
    if (!bridge) return undefined;
    const receive = event => { bridge.accept(event); };
    window.addEventListener('message', receive);
    return () => window.removeEventListener('message', receive);
  }, [bridge]);

  // Core views: hand them to the bridge (it waits for gev:ready), then drop them from the queue.
  useEffect(() => {
    if (!bridge || !views?.length) return;
    views.forEach(item => bridge.show(item.id, item.view));
    useStore.setState(state => ({ worldViews: (state.worldViews || []).filter(item => !views.includes(item)) }));
  }, [bridge, views]);

  const openInBrowser = useCallback(() => {
    const url = status && appUrl(status.port);
    if (url) window.electronAPI?.openExternal?.(url);
  }, [status]);

  const stop = useCallback(async () => {
    setBusy(true);
    try {
      const value = await client.current.stop();
      useStore.setState({ worldStatus: value, worldTour: value.tour });
      onClose?.();
    } catch (error) {
      setFailure(error.message);
      setBusy(false);
    }
  }, [onClose]);

  const stopTour = useCallback(() => {
    client.current?.tourStop().then(value => useStore.setState({ worldTour: value })).catch(error => setFailure(error.message));
  }, []);

  return <section className="world-page" aria-label="World view" data-phase={view.phase}>
    <header className="world-page__header">
      <div className="world-page__title">
        <HudLabel>WORLD</HudLabel>
        <h3>God&apos;s Eye View</h3>
        <StatusChip className="world-page__status" tone={view.chip.tone}>{view.chip.label}</StatusChip>
      </div>
      <div className="world-page__actions">
        <button type="button" className="btn btn--secondary btn--sm" disabled={!view.canOpen} onClick={openInBrowser}>
          <ExternalLink size={14} aria-hidden="true" />Open in browser
        </button>
        <button type="button" className="btn btn--secondary btn--sm" disabled={!view.canStop || busy} onClick={stop}>
          <Square size={14} aria-hidden="true" />Stop
        </button>
      </div>
    </header>
    <div className="world-page__stage">
      {view.phase === 'not_installed'
        ? <div className="world-page__setup">
          <span className="world-page__setup-icon" aria-hidden="true"><Globe size={20} strokeWidth={1.5} /></span>
          <p className="world-page__setup-title">World view isn&apos;t installed yet</p>
          <p className="world-page__setup-body">It runs the open-source God&apos;s Eye View globe on this PC. Setting it up needs a one-time download, which you approve and run yourself.</p>
          <details className="world-page__help">
            <summary>How to set it up</summary>
            <ol>{SETUP_STEPS.map(step => <li key={step}>{step}</li>)}</ol>
          </details>
        </div>
        : <>
          {view.frameUrl && <iframe ref={frame} key={view.frameUrl} className="world-page__frame" title="God's Eye View globe"
            src={view.frameUrl} sandbox={SANDBOX} allow={ALLOW} referrerPolicy="no-referrer" />}
          {view.message && <div className="world-page__veil" role={view.phase === 'error' ? 'alert' : 'status'}>
            <p>{view.message}</p>
          </div>}
          {view.tourBar && <div className="world-tour" role="region" aria-label="JARVIS tour">
            <PresenceRing size={44} state="speaking" lowPower />
            <div className="world-tour__text">
              <HudLabel className="world-tour__label">{view.tourBar.label}</HudLabel>
              <p className="world-tour__caption" aria-live="polite">{view.tourBar.caption}</p>
            </div>
            <button type="button" className="btn btn--secondary btn--sm world-tour__stop" onClick={stopTour}>Stop tour</button>
          </div>}
        </>}
    </div>
  </section>;
}
