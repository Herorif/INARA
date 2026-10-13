const test = require('node:test');
const assert = require('node:assert/strict');
const {
  ResidentController,
  waitForBackend
} = require('../electron/resident');
test('close releases window while keeping backend; reopen and quit are distinct', async () => {
  let opened = 0,
    closed = 0,
    stopped = 0;
  const controller = new ResidentController({
    open: () => opened++,
    close: () => closed++,
    stop: async () => stopped++
  });
  controller.ready();
  controller.open();
  controller.close();
  assert.equal(closed, 1);
  assert.equal(stopped, 0);
  assert.equal(controller.state.visible, false);
  controller.open();
  assert.equal(opened, 2);
  assert.equal(controller.state.phase, 'ready');
  await Promise.all([controller.quit(), controller.quit()]);
  assert.equal(stopped, 1);
  assert.equal(controller.state.phase, 'stopped');
  controller.open();
  assert.equal(opened, 2);
});
test('gaming mode is retained when closing/reopening and failure is visible', () => {
  const controller = new ResidentController({
    open() {},
    close() {},
    stop() {}
  });
  controller.mode(true);
  controller.ready();
  controller.close();
  controller.open();
  assert.equal(controller.state.gaming, true);
  controller.fail('startup failed');
  assert.equal(controller.state.phase, 'failed');
  assert.equal(controller.state.error, 'startup failed');
});
test('readiness retries briefly, rejects timeout and detects exited child', async () => {
  let time = 0,
    attempts = 0;
  const clock = {
    timeout: 1000,
    interval: 100,
    now: () => time,
    sleep: async ms => {
      time += ms;
    }
  };
  await waitForBackend(async () => ++attempts === 3, clock);
  assert.equal(attempts, 3);
  await assert.rejects(waitForBackend(async () => false, clock), /timed out/);
  await assert.rejects(waitForBackend(async () => true, {
    ...clock,
    alive: () => false
  }), /exited/);
});
test('duplicate quit waits for the same pending backend cleanup', async () => {
  let release;
  const controller = new ResidentController({
    open() {},
    close() {},
    stop: () => new Promise(resolve => {
      release = resolve;
    })
  });
  const first = controller.quit(),
    duplicate = controller.quit();
  assert.equal(first, duplicate);
  await Promise.resolve();
  assert.equal(controller.state.phase, 'stopping');
  release();
  await duplicate;
  assert.equal(controller.state.phase, 'stopped');
});
