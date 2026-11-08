import { cleanSteps } from './worldModel.js';

/**
 * The World page's message bridge to the embedded God's Eye View (its src/app/embed.js).
 *
 * Only messages whose source is the iframe's own window and whose origin is exactly the
 * globe's origin are read; everything else is ignored. Views wait until the globe posts
 * `gev:ready`, then go out as `{type: 'gev:view', id, view}` to that origin only. Each
 * `gev:view-applied` for a view this bridge sent is passed to `onApplied({id, ok, steps})`,
 * once.
 *
 * `target()` returns the iframe's current contentWindow (or null); `origin` is
 * http://127.0.0.1:<port>.
 */
export function createWorldBridge({ origin, target, onApplied, onReady = () => {} }) {
  let ready = false;
  const queue = [];
  const sent = new Set();

  const flush = () => {
    const frame = target();
    if (!ready || !frame) return;
    while (queue.length) {
      const { id, view } = queue.shift();
      sent.add(id);
      frame.postMessage({ type: 'gev:view', id, view }, origin);
    }
  };

  return {
    /** Handles one window `message` event; returns what it accepted, or null. */
    accept(event) {
      const frame = target();
      if (!frame || !event || event.source !== frame || event.origin !== origin) return null;
      const data = event.data;
      if (!data || typeof data !== 'object') return null;
      if (data.type === 'gev:ready') {
        ready = true;
        onReady();
        flush();
        return { type: 'ready' };
      }
      if (data.type === 'gev:view-applied' && typeof data.id === 'string' && sent.has(data.id)) {
        sent.delete(data.id);
        let steps = cleanSteps(data.steps);
        if (!steps.length && typeof data.error === 'string' && data.error.trim()) {
          steps = [{ step: 'view', ok: false, error: data.error.trim().slice(0, 300) }];
        }
        const result = { id: data.id, ok: data.ok === true && steps.every(step => step.ok), steps };
        onApplied(result);
        return { type: 'applied', ...result };
      }
      return null;
    },
    /** Queues a view; it goes out once the globe is ready. A repeated id is ignored. */
    show(id, view) {
      if (sent.has(id) || queue.some(item => item.id === id)) return;
      queue.push({ id, view });
      flush();
    },
    /** The iframe loaded again: wait for its next gev:ready. */
    reset() {
      ready = false;
    },
    get ready() {
      return ready;
    },
  };
}
