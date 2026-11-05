// Lifecycle policy separated from Electron for deterministic verification.
const path = require('path');
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
// The desktop profile moved from %APPDATA%\inara to %APPDATA%\<app name> (jarvis) with the JARVIS
// rename (5 Nov 2026); backend/resident_main.py makes the one-time move. Until it has, Electron's
// default profile falls back to the pre-rename folder when only that folder holds the resident
// identity (the data_migration.desktop_has_data rule). A profile a caller chose itself, such as a
// QA harness's throwaway folder, is always kept, so tests never open the owner's real profile.
function desktopProfile({ userData, appData, name, hasIdentity }) {
  const same = (a, b) => path.resolve(a).toLowerCase() === path.resolve(b).toLowerCase();
  const legacy = path.join(appData, 'inara');
  if (!same(userData, path.join(appData, name))) return userData;
  return !hasIdentity(userData) && hasIdentity(legacy) ? legacy : userData;
}
module.exports = {
  ResidentController,
  desktopProfile,
  waitForBackend
};
