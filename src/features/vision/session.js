// One presentation-independent camera/tracking session. All stop paths share cleanup.
import { createCapture } from './capture.js';
import { createTrackingLoop } from './trackingLoop.js';
export function createVisionSession({
  acquire,
  attach,
  frameSource,
  makeTracker,
  onState,
  onResult,
  onClear
}) {
  let state = {
      phase: 'idle',
      tracking: 'off',
      reason: '',
      error: ''
    },
    loop = null,
    disposed = false,
    rate = 10,
    currentSource = '';
  const publish = patch => {
    state = {
      ...state,
      ...patch
    };
    if (!disposed) onState(state);
  };
  const stopTracking = () => {
    loop?.stop();
    loop = null;
    publish({
      tracking: 'off'
    });
    onClear();
  };
  const capture = createCapture({
    acquire,
    attach,
    status: phase => {
      if (phase !== 'active') stopTracking();
      publish({
        phase
      });
    },
    error: code => publish({
      error: code
    })
  });
  const session = {
    start(source = '') {
      if (disposed) return Promise.resolve();
      if (['active', 'requesting'].includes(state.phase) && source === currentSource) return capture.start();
      currentSource = source;
      capture.stop();
      publish({
        reason: '',
        error: ''
      });
      return capture.start({
        audio: false,
        video: {
          width: {
            ideal: 640,
            max: 1280
          },
          height: {
            ideal: 480,
            max: 720
          },
          frameRate: {
            ideal: 15,
            max: 30
          },
          ...(source ? {
            deviceId: {
              exact: source
            }
          } : {})
        }
      });
    },
    stop(reason = '') {
      capture.stop(reason ? 'paused' : 'idle');
      publish({
        reason,
        error: ''
      });
    },
    track(enabled, fps = rate) {
      stopTracking();
      rate = fps === 5 ? 5 : 10;
      if (!enabled || state.phase !== 'active' || disposed) return;
      loop = createTrackingLoop({
        makeTracker,
        frameSource,
        onResult,
        onClear,
        interval: 1000 / rate,
        onStatus: tracking => publish({
          tracking
        })
      });
      return loop.start();
    },
    dispose() {
      disposed = true;
      capture.stop();
      loop?.stop();
      loop = null;
    },
    snapshot() {
      return {
        ...state
      };
    }
  };
  return session;
}
