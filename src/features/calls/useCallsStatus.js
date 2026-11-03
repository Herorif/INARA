import { useEffect, useSyncExternalStore } from 'react';
import socket from '../../services/socket';
import { createCallsClient } from '../../transport/callsClient.ts';

// One shared calls_status reader for the command bar (ON CALL chip, nav badge) and the
// Calls view. It refreshes on connect, on call events and every 30 s while in use.
const POLL_MS = 30000;
const listeners = new Set();
let state = { status: null, error: null, loaded: false };
let client = null, users = 0, timer = 0, debounce = 0, inflight = null, offs = [];

const emit = next => { state = { ...state, ...next }; listeners.forEach(listener => listener()); };

export function refreshCallsStatus() {
  if (!client || !socket.connected) return Promise.resolve(state.status);
  if (inflight) return inflight;
  inflight = client.status()
    .then(status => { emit({ status, error: null, loaded: true }); return status; })
    .catch(error => { emit({ status: null, error, loaded: true }); return null; })
    .finally(() => { inflight = null; });
  return inflight;
}

const soon = () => { clearTimeout(debounce); debounce = setTimeout(refreshCallsStatus, 300); };

function start() {
  client = createCallsClient(socket);
  offs = [
    client.on('connect', refreshCallsStatus),
    client.on('disconnect', () => emit({ status: null, error: null, loaded: false })),
    client.on('call_progress', soon),
    client.on('call_record_ready', soon),
  ];
  timer = setInterval(() => { if (!document.hidden) refreshCallsStatus(); }, POLL_MS);
  refreshCallsStatus();
}

function stop() {
  clearInterval(timer); clearTimeout(debounce);
  offs.forEach(off => off()); offs = [];
  client?.dispose(); client = null; inflight = null;
  emit({ status: null, error: null, loaded: false });
}

const subscribe = listener => { listeners.add(listener); return () => listeners.delete(listener); };
const read = () => state;

/** { status, error, loaded }; `active` false (locked, offline) stops reading and clears it. */
export default function useCallsStatus(active = true) {
  useEffect(() => {
    if (!active) return undefined;
    users += 1;
    if (users === 1) start();
    return () => { users -= 1; if (users === 0) stop(); };
  }, [active]);
  return useSyncExternalStore(subscribe, read);
}
