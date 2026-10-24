// Injectable protocol owner, also exercised without a browser/model in Node tests.
export function createWorkerClient(worker, {
  timeout = 15000,
  frameTimeout = 4000
} = {}) {
  let closed = false,
    pending = null,
    sequence = 0,
    timer;
  let resolveReady, rejectReady;
  const ready = new Promise((resolve, reject) => {
    resolveReady = resolve;
    rejectReady = reject;
  });
  const close = () => {
    if (closed) return;
    closed = true;
    clearTimeout(timer);
    clearTimeout(pending?.timer);
    worker.terminate();
    rejectReady(new Error('Tracking session closed.'));
    pending?.reject(new Error('Tracking session closed.'));
    pending = null;
  };
  const fail = () => {
    rejectReady(new Error('Local tracking could not load or stopped.'));
    close();
  };
  timer = setTimeout(fail, timeout);
  worker.onmessage = ({
    data
  }) => {
    if (closed) return;
    if (data.type === 'ready') {
      clearTimeout(timer);
      resolveReady();
    } else if (data.type === 'failed') fail();else if (data.type === 'result' && pending?.id === data.id) {
      clearTimeout(pending.timer);
      const resolve = pending.resolve;
      pending = null;
      resolve(data);
    }
  };
  worker.onerror = fail;
  worker.onmessageerror = fail;
  try {
    worker.postMessage({
      type: 'init'
    });
  } catch {
    fail();
  }
  return {
    ready,
    detect(frame, timestamp) {
      if (closed || pending) {
        frame.close();
        return Promise.reject(new Error('Tracking worker unavailable or busy.'));
      }
      return new Promise((resolve, reject) => {
        const id = ++sequence;
        pending = {
          id,
          resolve,
          reject,
          timer: setTimeout(fail, frameTimeout)
        };
        try {
          worker.postMessage({
            type: 'frame',
            id,
            frame,
            timestamp
          }, [frame]);
        } catch {
          frame.close();
          fail();
        }
      });
    },
    close
  };
}
export function createTrackingWorker() {
  // Classic worker: the bundled Emscripten loader uses importScripts.
  return createWorkerClient(new Worker(new URL('./tracking.worker.js', import.meta.url)));
}
