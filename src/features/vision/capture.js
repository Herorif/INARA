// Own each camera acquisition, including permission prompts that finish after closing.
export function createCapture({
  acquire,
  attach,
  status
}) {
  let generation = 0,
    stream = null,
    pending = null;
  const release = value => value?.getTracks().forEach(track => track.stop());
  return {
    start() {
      if (stream || pending) return pending;
      const current = ++generation;
      status('requesting');
      pending = Promise.resolve().then(acquire).then(value => {
        if (current !== generation) {
          release(value);
          return;
        }
        stream = value;
        attach(value);
        status('active');
      }).catch(() => {
        if (current === generation) status('failed');
      }).finally(() => {
        if (current === generation) pending = null;
      });
      return pending;
    },
    stop() {
      generation++;
      release(stream);
      stream = null;
      pending = null;
      attach(null);
      status('idle');
    }
  };
}
