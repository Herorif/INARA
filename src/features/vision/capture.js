// Own one acquisition, including permission results that arrive after stop/switch.
export function createCapture({
  acquire,
  attach,
  status,
  error = () => {}
}) {
  let generation = 0,
    stream = null,
    pending = null,
    detach = [];
  const release = value => value?.getTracks().forEach(track => track.stop());
  const stop = (reason = 'idle') => {
    generation++;
    detach.forEach(remove => remove());
    detach = [];
    const old = stream;
    stream = null;
    pending = null;
    release(old);
    attach(null);
    status(reason);
  };
  return {
    start(options) {
      if (stream || pending) return pending;
      const current = ++generation;
      status('requesting');
      pending = Promise.resolve().then(() => acquire(options)).then(value => {
        if (current !== generation) {
          release(value);
          return;
        }
        stream = value;
        const tracks = value.getVideoTracks?.() || value.getTracks();
        if (!tracks.length || tracks.some(track => track.readyState === 'ended')) throw new Error('No live video');
        for (const track of tracks) {
          const ended = () => {
            if (current === generation) stop('lost');
          };
          track.addEventListener?.('ended', ended);
          detach.push(() => track.removeEventListener?.('ended', ended));
        }
        attach(value);
        status('active');
      }).catch(failure => {
        if (current !== generation) return;
        detach.forEach(remove => remove());
        detach = [];
        release(stream);
        stream = null;
        attach(null);
        error(failure?.name || 'CaptureError');
        status('failed');
      }).finally(() => {
        if (current === generation) pending = null;
      });
      return pending;
    },
    stop
  };
}
