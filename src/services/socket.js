/**
 * Singleton Socket.IO instance and helpers.
 * Direct import - no React Context needed since the instance never changes.
 */
import io from 'socket.io-client';
import { emitConnected } from './subscriptions';
import { readMigrated } from './storageKeys';

let clientId = window.electronAPI?.clientId || readMigrated(localStorage, 'jarvis_client_id');
if (!clientId) {
    clientId = crypto.randomUUID();
    localStorage.setItem('jarvis_client_id', clientId);
}
// Production renderers get the launch token only from the preload bridge. The Vite dev
// value is referenced behind import.meta.env.DEV so builds drop it as dead code.
const devSessionToken = import.meta.env.DEV ? import.meta.env.VITE_JARVIS_SESSION_TOKEN : '';
const socket = io('http://localhost:8000', {
    autoConnect: false,
    auth: { client_id: clientId, token: window.electronAPI?.sessionToken || devSessionToken || '' },
});

// Complete native owner registration before the renderer hydrates owner-only state.
Promise.resolve(window.electronAPI?.registerResident(clientId)).catch(() => {
    // The desktop status bridge reports registration failure. Text reconnect remains available.
}).finally(() => socket.connect());

/** Subscribe to a socket event, returns unsubscribe function. */
export const onSocket = (event, handler) => {
    socket.on(event, handler);
    return () => socket.off(event, handler);
};

/** Emit a socket event. */
export const emitSocket = (event, data) => emitConnected(socket, event, data);

export default socket;
