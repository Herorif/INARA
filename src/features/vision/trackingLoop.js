// Bounded scheduling/backpressure, independent of React and capture permissions.
export function createTrackingLoop({
  makeTracker,
  frameSource,
  onResult,
  onStatus,
  onClear = () => {},
  interval = 100,
  now = () => performance.now(),
  schedule = setInterval,
  unschedule = clearInterval
}) {
  let generation = 0,
    client = null,
    timer = null,
    busy = false,
    lastTime = -1,
    lastResult = 0;
  const stop = () => {
    generation++;
    unschedule(timer);
    timer = null;
    client?.close();
    client = null;
    busy = false;
    onClear();
  };
  return {
    async start() {
      stop();
      const current = generation;
      onStatus('loading');
      try {
        const instance = makeTracker();
        client = instance;
        await instance.ready;
        if (generation !== current) {
          instance.close();
          return;
        }
        onStatus('running');
        lastTime = -1;
        lastResult = now();
        timer = schedule(async () => {
          if (current !== generation) return;
          if (now() - lastResult > 700) {
            onClear();
            lastResult = now();
          }
          if (busy) return;
          let source;
          try {
            source = frameSource();
          } catch {
            stop();
            onStatus('failed');
            return;
          }
          if (!source || source.time === lastTime) return;
          lastTime = source.time;
          busy = true;
          const capturedAt = now();
          let frame;
          try {
            frame = await source.capture();
            if (current !== generation) {
              frame.close();
              return;
            }
            const result = await instance.detect(frame, capturedAt);
            if (current === generation && now() - capturedAt <= 500) {
              lastResult = now();
              onResult(result, {
                capturedAt,
                receivedAt: now()
              });
            }
          } catch {
            if (current === generation) {
              stop();
              onStatus('failed');
            }
          } finally {
            if (current === generation) busy = false;
          }
        }, interval);
      } catch {
        if (current === generation) {
          stop();
          onStatus('failed');
        }
      }
    },
    stop
  };
}
