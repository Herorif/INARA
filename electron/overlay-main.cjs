// Talking overlay entry. The core spawns this with one JSON bootstrap object on stdin
// ({ token, clientId, profile, core, dev }); see docs/VOICE_OVERLAY.md.
const fs = require('node:fs');
const { app } = require('electron');
const { parseBootstrap } = require('./overlay-policy.cjs');

// The overlay is never focused, so it never sees a gesture: its one interface cue (a proactive
// card's notify, docs/PROACTIVE.md) may play without one. It has no microphone or camera.
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');

let bootstrap;
try {
  bootstrap = parseBootstrap(fs.readFileSync(0, 'utf8'));
} catch {
  bootstrap = { ok: false, error: 'Invalid overlay bootstrap: unreadable stdin' };
}
if (!bootstrap.ok) {
  // The message names the failing field only; it never contains the token.
  console.error(bootstrap.error);
  app.exit(1);
} else {
  // The overlay ends itself (done, lost core, no snapshot); closing its window never quits early.
  app.on('window-all-closed', () => {});
  require('./overlay-app.cjs').start(bootstrap.value).catch(() => {
    console.error('JARVIS overlay: start failed');
    app.exit(1);
  });
}
