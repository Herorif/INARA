// One local worker/model per explicit tracking session. No renderer-side inference.
import { createTracker } from './tracker';
let tracker;
self.onmessage = async ({
  data
}) => {
  const {
    type,
    id,
    frame,
    timestamp
  } = data;
  try {
    if (type === 'init') {
      tracker = await createTracker();
      self.postMessage({
        type: 'ready'
      });
    } else if (type === 'frame' && tracker) {
      const start = performance.now();
      const result = tracker.detectForVideo(frame, timestamp);
      self.postMessage({
        type: 'result',
        id,
        landmarks: result.landmarks,
        handedness: result.handedness,
        inferenceMs: performance.now() - start
      });
    }
  } catch (failure) {
    console.warn('Local tracker:', String(failure.message).slice(0, 200));
    self.postMessage({
      type: 'failed',
      id
    });
  } finally {
    frame?.close();
  }
};
