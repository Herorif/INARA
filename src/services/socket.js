/**
 * Singleton Socket.IO instance and helpers.
 * Direct import - no React Context needed since the instance never changes.
 */
import io from 'socket.io-client';

const socket = io('http://localhost:8000');

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
