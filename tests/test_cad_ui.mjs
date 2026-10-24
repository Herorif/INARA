import test from 'node:test';
import assert from 'node:assert/strict';
import { mergeJob, pendingJob } from '../src/features/cad/client.js';
test('late submission acknowledgement cannot overwrite a completed build', () => {
  const ready = {
    request_id: 'one',
    state: 'succeeded',
    stats: {
      triangles: 12
    }
  };
  assert.deepEqual(mergeJob(ready, {
    request_id: 'one',
    state: 'queued'
  }), ready);
  assert.equal(pendingJob(ready), false);
  assert.equal(pendingJob({
    state: 'approval'
  }), true);
});
