// Lifecycle policy separated from Electron for deterministic verification.
class ResidentController {
  constructor({
    open,
    close,
    stop,
    publish = () => {}
  }) {
    Object.assign(this, {
      openWindow: open,
      closeWindow: close,
      stopBackend: stop,
      publish
    });
    this.state = {
      phase: 'starting',
      visible: false,
      gaming: false,
      error: null
    };
    this.quitting = false;
  }
  update(value) {
    Object.assign(this.state, value);
    this.publish({
      ...this.state
    });
  }
  ready() {
    this.update({
      phase: 'ready',
      error: null
    });
  }
  fail(message) {
    this.update({
      phase: 'failed',
      error: message
    });
  }
  open() {
    if (!this.quitting) {
      this.openWindow();
      this.update({
        visible: true
      });
    }
  }
  close() {
    if (!this.quitting) {
      this.closeWindow();
      this.update({
        visible: false
      });
    }
  }
  mode(gaming) {
    this.update({
      gaming: Boolean(gaming)
    });
  }
  quit() {
    if (this.stopPromise) return this.stopPromise;
    this.quitting = true;
    this.update({
      phase: 'stopping'
    });
    this.stopPromise = Promise.resolve().then(() => this.stopBackend()).then(() => {
      this.update({
        phase: 'stopped',
        visible: false
      });
    });
    return this.stopPromise;
  }
}
async function waitForBackend(probe, {
  timeout = 20000,
  interval = 250,
  now = Date.now,
  sleep = ms => new Promise(resolve => setTimeout(resolve, ms)),
  alive = () => true
} = {}) {
  const deadline = now() + timeout;
  while (now() < deadline) {
    if (!alive()) throw new Error('The backend exited before it was ready.');
    try {
      if (await probe()) return;
    } catch {/* bounded retry */}
    await sleep(interval);
  }
  throw new Error('Backend startup timed out. Check the core environment and storage.');
}
module.exports = {
  ResidentController,
  waitForBackend
};
