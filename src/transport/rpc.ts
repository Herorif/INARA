/** A renderer/panel owns its subscriptions and outstanding acknowledgements. */
export interface RpcSocket {
  connected: boolean;
  on(event: string, handler: (...args: any[]) => void): unknown;
  off(event: string, handler: (...args: any[]) => void): unknown;
  emit(event: string, data: unknown, ack: (response: unknown) => void): unknown;
}
export class RpcError extends Error {
  code: string;
  uncertain: boolean;
  constructor(message: string, code: string, uncertain = false) {
    super(message);
    this.name = 'RpcError';
    this.code = code;
    this.uncertain = uncertain;
  }
}
export function createRpcScope(socket: RpcSocket) {
  let closed = false;
  const pending = new Set<(error: RpcError) => void>();
  const listeners = new Set<() => void>();
  const disconnected = () => {
    for (const reject of [...pending]) reject(new RpcError(
      'Connection lost. Refresh revision history after reconnecting before trying again.',
      'disconnected', true));
  };
  socket.on('disconnect', disconnected);
  return {
    on(event: string, handler: (...args: any[]) => void) {
      if (closed) return () => {};
      const guarded = (...args: any[]) => { if (!closed) handler(...args); };
      socket.on(event, guarded);
      const off = () => { socket.off(event, guarded); listeners.delete(off); };
      listeners.add(off);
      return off;
    },
    call<T = Record<string, unknown>>(event: string, data: unknown = {}, timeout = 10000): Promise<T> {
      if (closed) return Promise.reject(new RpcError('This panel session has closed.', 'scope_closed'));
      if (!socket.connected) return Promise.reject(new RpcError('Connect to the core before using Studio.', 'offline'));
      return new Promise((resolve, reject) => {
        let settled = false;
        const finish = (error?: RpcError, response?: T) => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          pending.delete(cancel);
          if (error) reject(error); else resolve(response!);
        };
        const cancel = (error: RpcError) => finish(error);
        const timer = setTimeout(() => finish(new RpcError(
          'The core did not respond. Refresh revision history before trying again.', 'timeout', true)), timeout);
        pending.add(cancel);
        try {
          socket.emit(event, data, response => {
            if (!response || typeof response !== 'object' || !('ok' in response) || typeof response.ok !== 'boolean') {
              finish(new RpcError('The core returned an invalid response. Refresh revision history.', 'invalid_response', true));
            } else if (!response.ok) {
              const failure = response as { code?: unknown; message?: unknown };
              finish(new RpcError(typeof failure.message === 'string' ? failure.message : 'The Studio action could not complete.',
                typeof failure.code === 'string' ? failure.code : 'action_failed'));
            } else finish(undefined, response as T);
          });
        } catch {
          finish(new RpcError('The request could not be delivered. Refresh revision history.', 'send_failed', true));
        }
      });
    },
    dispose() {
      if (closed) return;
      closed = true;
      socket.off('disconnect', disconnected);
      for (const off of [...listeners]) off();
      for (const reject of [...pending]) reject(new RpcError('This panel session has closed.', 'scope_closed', true));
    },
  };
}
