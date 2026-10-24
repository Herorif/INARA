/** A removable event group, shared by app and feature store bridges. */
export function createSubscriptions(socket) {
  const cleanups = new Set();
  let closed = false;
  return {
    on(event, handler) {
      if (closed) return () => {};
      const guarded = (...args) => { if (!closed) handler(...args); };
      socket.on(event, guarded);
      const off = () => { socket.off(event, guarded); cleanups.delete(off); };
      cleanups.add(off);
      return off;
    },
    dispose() { closed = true; for (const off of [...cleanups]) off(); },
  };
}

/** Fire-and-forget actions must not queue for an unexpected reconnect replay. */
export function emitConnected(socket, event, data) {
  if (!socket.connected) return false;
  if (typeof data === 'undefined') socket.emit(event); else socket.emit(event, data);
  return true;
}
