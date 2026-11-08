/**
 * The core's `vision_capture_request` (look_through_camera, approved by the owner): one job
 * at a time, answered exactly once with `vision_capture_result` {request_id, image | error}.
 * The job goes into the store as `visionCapture` (taken by the Vision studio) together with
 * `visionFocus` (CommandDeck opens the studio, then clears it). A job nobody finishes ends
 * as `failed` before the core's own 20 s timeout.
 */

export const CAPTURE_DEADLINE_MS = 18_000;
export const CAPTURE_ERRORS = new Set(['hidden', 'denied', 'unavailable', 'busy', 'gaming', 'locked', 'failed']);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function createCaptureRequests({ reply, store, hidden = () => false, timers = { set: (run, ms) => setTimeout(run, ms), clear: id => clearTimeout(id) }, deadline = CAPTURE_DEADLINE_MS }) {
  let job = null;
  const clearStore = requestId => store.setState(state => (state.visionCapture?.requestId === requestId ? { visionCapture: null, visionFocus: null } : {}));
  return {
    /** A `vision_capture_request` arrived. */
    request(data) {
      const requestId = data?.request_id;
      if (typeof requestId !== 'string' || !UUID.test(requestId)) return null;
      if (job) { reply(requestId, { error: 'busy' }); return null; }
      if (store.getState().isLockScreenVisible) { reply(requestId, { error: 'locked' }); return null; }
      if (hidden()) { reply(requestId, { error: 'hidden' }); return null; }
      const question = typeof data.question === 'string' ? data.question.slice(0, 500) : '';
      let done = false;
      const finish = (result, silent = false) => {
        if (done) return false;
        done = true;
        timers.clear(timer);
        if (job?.requestId === requestId) job = null;
        clearStore(requestId);
        if (silent) return true;
        const image = typeof result?.image === 'string' && result.image ? result.image : null;
        reply(requestId, image ? { image } : { error: CAPTURE_ERRORS.has(result?.error) ? result.error : 'failed' });
        return true;
      };
      const timer = timers.set(() => finish({ error: 'failed' }), deadline);
      job = Object.freeze({ requestId, question, settle: result => finish(result), abandon: () => finish(null, true) });
      store.setState({ visionCapture: job, visionFocus: requestId });
      return job;
    },
    /** The core connection dropped: the request is gone, nothing can be answered. */
    drop() {
      job?.abandon();
    },
    current: () => job,
  };
}
