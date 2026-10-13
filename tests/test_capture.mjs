import test from 'node:test';
import assert from 'node:assert/strict';
import { createCapture } from '../src/features/vision/capture.js';
test('closing during permission acquisition releases late stream without attaching', async () => {
  let resolve,
    released = 0;
  const attached = [],
    statuses = [];
  const capture = createCapture({
    acquire: () => new Promise(done => {
      resolve = done;
    }),
    attach: value => attached.push(value),
    status: value => statuses.push(value)
  });
  const pending = capture.start();
  await Promise.resolve();
  capture.stop();
  resolve({
    getTracks: () => [{
      stop: () => released++
    }]
  });
  await pending;
  assert.equal(released, 1);
  assert.deepEqual(attached, [null]);
  assert.equal(statuses.at(-1), 'idle');
});
test('duplicate activation acquires once and stopping releases every track', async () => {
  let acquired = 0,
    stopped = 0;
  const capture = createCapture({
    acquire: async () => {
      acquired++;
      return {
        getTracks: () => [{
          stop: () => stopped++
        }, {
          stop: () => stopped++
        }]
      };
    },
    attach() {},
    status() {}
  });
  await Promise.all([capture.start(), capture.start()]);
  assert.equal(acquired, 1);
  capture.stop();
  assert.equal(stopped, 2);
});
