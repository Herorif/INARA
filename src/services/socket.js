/**
 * Singleton Socket.IO instance and helpers.
 * Direct import - no React Context needed since the instance never changes.
 */
import io from 'socket.io-client';

let clientId = localStorage.getItem('inara_client_id');
if (!clientId) {
    clientId = crypto.randomUUID();
    localStorage.setItem('inara_client_id', clientId);
}
const socket = io('http://localhost:8000', {
    auth: { client_id: clientId, token: window.electronAPI?.sessionToken
        || import.meta.env.VITE_INARA_SESSION_TOKEN || '' },
});

/** Subscribe to a socket event, returns unsubscribe function. */
export const onSocket = (event, handler) => {
    socket.on(event, handler);
    return () => socket.off(event, handler);
};

/** Emit a socket event. */
export const emitSocket = (event, data) => {
    if (typeof data === 'undefined') {
        socket.emit(event);
        return;
    }
    socket.emit(event, data);
};

export default socket;
