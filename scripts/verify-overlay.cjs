// Talking-overlay harness (npm run verify:overlay; build first with npm run build). Runs
// electron/overlay-app.cjs start() in-process against scripts/fake-overlay-core.py over a real
// socket. Offscreen only: showInactive/show/focus are stubbed, so nothing reaches the screen.
// Isolated userData under .runtime/ui-qa/overlay/. Hold the QA lock around it.
require('./qa-capture-retry.cjs');
const { app, BrowserWindow, screen } = require('electron');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');
const overlay = require('../electron/overlay-app.cjs');
const policy = require('../electron/overlay-policy.cjs');

const ROOT = path.resolve(__dirname, '..');
const OUTPUT = path.join(ROOT, '.runtime', 'ui-qa', 'overlay');
const PROFILE = path.join(OUTPUT, `profile-${Date.now()}`);
const PYTHON = path.join(ROOT, '.venv', 'Scripts', 'python.exe');
const TOKEN = crypto.randomBytes(32).toString('hex');
const CLIENT_ID = crypto.randomUUID();
const BACKDROPS = { light: '#eef1f4', dark: '#14181d' };
fs.mkdirSync(PROFILE, { recursive: true });
app.commandLine.appendSwitch('force-device-scale-factor', '1');
app.setPath('userData', PROFILE);
app.on('window-all-closed', () => {});

// Never on screen and never focused: record the calls instead.
const calls = { showInactive: 0, show: 0, focus: 0, alwaysOnTop: [], contentProtection: [], ignoreMouse: [], opacity: [] };
BrowserWindow.prototype.showInactive = function () { calls.showInactive++; };
BrowserWindow.prototype.show = function () { calls.show++; };
BrowserWindow.prototype.focus = function () { calls.focus++; };
const spy = (name, list) => {
  const original = BrowserWindow.prototype[name];
  BrowserWindow.prototype[name] = function (...args) { list.push(args); return original.apply(this, args); };
};
spy('setAlwaysOnTop', calls.alwaysOnTop);
spy('setContentProtection', calls.contentProtection);
spy('setIgnoreMouseEvents', calls.ignoreMouse);
spy('setOpacity', calls.opacity);

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, label, ms = 8000, step = 40) {
  const end = Date.now() + ms;
  for (;;) {
    const value = await check();
    if (value) return value;
    if (Date.now() > end) throw Error(`Timed out: ${label}`);
    await sleep(step);
  }
}

// --- fake core
const events = [];
let core;
function startCore() {
  core = spawn(PYTHON, ['-I', path.join(__dirname, 'fake-overlay-core.py')], {
    cwd: ROOT, env: { ...process.env, FAKE_OVERLAY_TOKEN: TOKEN, FAKE_OVERLAY_CLIENT_ID: CLIENT_ID }, stdio: ['pipe', 'pipe', 'pipe'],
  });
  core.stderr.on('data', chunk => process.stderr.write(chunk));
  readline.createInterface({ input: core.stdout }).on('line', line => { try { events.push({ ...JSON.parse(line), at: Date.now() }); } catch { /* ignore */ } });
  return until(() => events.find(event => event.event === 'ready'), 'fake core ready', 20000).then(event => event.port);
}
async function command(value) {
  const before = events.filter(event => event.event === 'ack').length;
  core.stdin.write(`${JSON.stringify(value)}\n`);
  await until(() => events.filter(event => event.event === 'ack').length > before, `ack ${value.op}`);
}
const count = name => events.filter(event => event.event === name).length;
const snapshot = fields => ({ session: 's1', state: 'listening', user: '', user_final: false, jarvis: '', jarvis_final: false, approval: false, end: null, ...fields });
const push = fields => command({ op: 'snapshot', data: snapshot(fields) });

// --- overlay instances
const logs = [];
const captions = new Set();
async function launch(fields = {}) {
  const state = { quitCode: undefined, quitAt: null };
  const controller = await overlay.start({ token: TOKEN, clientId: CLIENT_ID, profile: PROFILE, core: `http://127.0.0.1:${port}`, dev: false, ...fields }, {
    offscreen: true,
    log: message => logs.push(message),
    quit: code => { state.quitCode = code; state.quitAt = Date.now(); },
  });
  const contents = controller.window.webContents;
  const blocked = [];
  contents.session.webRequest.onBeforeRequest((details, callback) => {
    const ok = ['file:', 'data:', 'blob:', 'devtools:'].includes(new URL(details.url).protocol);
    if (!ok) blocked.push(details.url);
    callback({ cancel: !ok });
  });
  const errors = [];
  contents.on('console-message', event => { if (event.level === 'error') errors.push(String(event.message).slice(0, 200)); });
  return { controller, contents, state, blocked, errors };
}
const run = (instance, source) => instance.contents.executeJavaScript(source);
const panel = instance => run(instance, `(() => {
  const p = document.querySelector('.overlay-panel');
  if (!p) return null;
  const slot = name => { const e = p.querySelector(name); return e ? { text: e.textContent, tone: e.dataset.tone, clipped: e.dataset.clipped } : null; };
  const button = label => { const b = [...p.querySelectorAll('button')].find(x => (x.getAttribute('aria-label') || x.textContent) === label); if (!b) return null; const r = b.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2, w: r.width, h: r.height, title: b.title }; };
  const r = p.getBoundingClientRect();
  return { visible: p.dataset.visible, phase: p.dataset.phase, end: p.dataset.end, top: slot('.overlay-top'), main: slot('.overlay-main'),
    stop: button('Stop talking'), open: button('Open JARVIS'), ring: p.querySelector('.presence')?.dataset.presence,
    mode: p.querySelector('.presence')?.dataset.presenceMode, coreReady: !!p.querySelector('.presence-core[data-ready="true"]'),
    rect: { x: r.x, y: r.y, width: r.width, height: r.height, bottom: innerHeight - r.bottom } };
})()`);
const settle = instance => run(instance, 'new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))');

const shots = [];
async function shoot(instance, name) {
  for (const [backdrop, color] of Object.entries(BACKDROPS)) {
    const key = await instance.contents.insertCSS(`html { background: ${color} !important; }`);
    await settle(instance);
    const image = await instance.contents.capturePage();
    const file = path.join(OUTPUT, `${name}-${backdrop}.png`);
    fs.writeFileSync(file, image.toPNG());
    shots.push(path.relative(ROOT, file));
    await instance.contents.removeInsertedCSS(key);
  }
}
async function show(instance, check, label) {
  await until(async () => { const p = await panel(instance); return p && check(p) ? p : null; }, label);
  await sleep(260); // past the 180 ms enter motion and a few core frames
  const value = await panel(instance);
  assert.ok(value && check(value), `${label} (after settling)`);
  return value;
}
const mouse = (instance, type, x, y) => instance.contents.sendInputEvent({ type, x: Math.round(x), y: Math.round(y), button: 'left', clickCount: 1 });
async function click(instance, target) {
  mouse(instance, 'mouseMove', target.x, target.y);
  await sleep(60);
  mouse(instance, 'mouseDown', target.x, target.y);
  mouse(instance, 'mouseUp', target.x, target.y);
  await sleep(60);
}
const exited = (instance, ms) => Promise.race([instance.controller.exited, sleep(ms).then(() => { throw Error('overlay did not quit in time'); })]);

let port;
const report = { checks: [], screenshots: shots };
const pass = (name, detail) => { report.checks.push(detail === undefined ? name : `${name}: ${detail}`); };

async function sessionOne() {
  await push({ state: 'connecting' });
  const one = await launch();
  const { window } = one.controller;
  const first = await show(one, p => p.visible === 'true', 'connecting shown');
  assert.equal(first.top.text, 'Connecting…');
  assert.equal(first.top.tone, 'tertiary');
  assert.equal(first.ring, 'working');
  assert.equal(calls.showInactive, 1);
  assert.equal(calls.show + calls.focus, 0);

  // Window options and bounds.
  const options = one.controller.options;
  for (const [key, value] of Object.entries({ frame: false, transparent: true, backgroundColor: '#00000000', hasShadow: false, resizable: false, movable: false, focusable: false, skipTaskbar: true, alwaysOnTop: true, show: false })) assert.equal(options[key], value, key);
  assert.deepEqual({ ...options.webPreferences, preload: path.basename(options.webPreferences.preload) },
    { contextIsolation: true, sandbox: true, nodeIntegration: false, preload: 'overlay-preload.js', backgroundThrottling: false, offscreen: true });
  assert.equal(window.isFocusable(), false);
  assert.equal(window.isAlwaysOnTop(), true);
  assert.equal(window.isResizable(), false);
  assert.equal(window.isMovable(), false);
  assert.deepEqual(calls.alwaysOnTop.at(-1), [true, 'screen-saver']);
  assert.deepEqual(calls.contentProtection.at(-1), [true]);
  if (typeof window.isContentProtected === 'function') assert.equal(window.isContentProtected(), true);
  assert.deepEqual(calls.ignoreMouse[0], [true, { forward: true }]);
  const workArea = screen.getDisplayNearestPoint(screen.getCursorScreenPoint()).workArea;
  const expected = policy.overlayBounds(workArea);
  assert.deepEqual(one.controller.bounds, expected);
  assert.deepEqual(window.getBounds(), expected);
  assert.equal(first.rect.width, Math.min(560, expected.width - 48));
  assert.equal(first.rect.bottom, 16);
  pass('window options', 'frameless, transparent, focusable false, always on top (screen-saver), skip taskbar, content protection on, click-through, shown inactive once');
  pass('bounds', `${JSON.stringify(expected)} for work area ${JSON.stringify(workArea)}; panel ${first.rect.width}x${first.rect.height}, 16 px above the bottom`);

  // The bridge: exactly the contract members, no token anywhere in the page.
  assert.deepEqual(await run(one, 'Object.keys(window.jarvisOverlay).sort()'), ['done', 'onLevel', 'onSnapshot', 'open', 'pointer', 'ready', 'stop']);
  assert.equal(await run(one, `document.documentElement.outerHTML.includes(${JSON.stringify(TOKEN)}) || JSON.stringify(window.jarvisOverlay).includes(${JSON.stringify(TOKEN)})`), false);
  pass('renderer bridge', 'exactly onSnapshot, onLevel, ready, pointer, stop, open, done; no token in the page');

  // Transparent outside the panel.
  const bitmap = (await one.contents.capturePage()).toBitmap();
  assert.equal(bitmap[3], 0, 'top-left pixel alpha');
  pass('transparency', 'top-left pixel alpha 0 without a backdrop');
  await shoot(one, '01-connecting');

  await push({ state: 'listening' });
  let p = await show(one, x => x.ring === 'listening', 'listening');
  assert.deepEqual(p.top, { text: 'Listening', tone: 'tertiary', clipped: undefined });
  assert.equal(p.main, null);
  assert.ok(p.stop && p.stop.w === 28 && p.stop.h === 28 && p.stop.title === 'Stop talking');
  assert.equal(p.open, null);
  await shoot(one, '02-listening');

  const asked = 'Hey Jarvis, what’s on my calendar this afternoon?';
  captions.add(asked);
  await push({ state: 'listening', user: asked });
  p = await show(one, x => x.top?.text.startsWith('“What'), 'hearing');
  assert.equal(p.top.text, '“What’s on my calendar this afternoon?”');
  assert.equal(p.top.tone, 'primary');
  await shoot(one, '03-hearing');

  await push({ state: 'thinking', user: asked, user_final: true });
  p = await show(one, x => x.main?.text === 'Thinking…', 'thinking');
  assert.equal(p.top.tone, 'secondary');
  assert.equal(p.main.tone, 'tertiary');
  assert.equal(p.ring, 'working');
  await shoot(one, '04-thinking');

  await push({ state: 'working', user: asked, user_final: true });
  p = await show(one, x => x.main?.text === 'Working on it…', 'working');
  await shoot(one, '05-working');

  const answer = 'You have two things this afternoon: the design review with Farah at 2:30 in the small meeting room, and a call with the landlord at 4 about renewing the lease. After that your calendar is clear until tomorrow morning, so the evening is free.';
  captions.add(answer);
  await push({ state: 'speaking', user: asked, user_final: true, jarvis: answer });
  for (const level of [0.2, 0.55, 0.9, 0.6, 0.35, 0.8]) { await command({ op: 'level', level }); await sleep(50); }
  p = await show(one, x => x.ring === 'speaking', 'speaking');
  assert.equal(p.main.text, answer);
  assert.equal(p.main.tone, 'primary');
  assert.equal(p.main.clipped, 'true');
  assert.equal(p.top.tone, 'tertiary');
  pass('3D core', `presence mode ${p.mode}, first frame ${p.coreReady}`);
  await shoot(one, '06-speaking');
  await command({ op: 'level', level: 0 });

  await push({ state: 'listening', user: asked, user_final: true, jarvis: answer, jarvis_final: true });
  p = await show(one, x => x.ring === 'listening', 'listening after answer');
  assert.equal(p.main.tone, 'secondary');
  assert.equal(p.main.text, answer);
  await shoot(one, '07-listening-dimmed');

  const asked2 = 'Hey Jarvis, email the summary to Farah.';
  const answer2 = 'That email needs your approval. Open JARVIS to review it.';
  captions.add(asked2); captions.add(answer2);
  await push({ state: 'listening', user: asked2, user_final: true });
  p = await show(one, x => x.main === null && x.top?.text.includes('Email'), 'new exchange clears the answer');
  await push({ state: 'speaking', user: asked2, user_final: true, jarvis: answer2, approval: true });
  p = await show(one, x => !!x.open, 'approval');
  assert.ok(p.stop);
  assert.equal(p.open.h, 28);
  assert.equal(p.main.clipped, 'false');
  await shoot(one, '08-approval');

  // Hover: click-through off inside the panel, back on when the pointer leaves.
  const ignoreBefore = calls.ignoreMouse.length;
  mouse(one, 'mouseMove', p.rect.x + 40, p.rect.y + 40);
  await until(() => calls.ignoreMouse.slice(ignoreBefore).some(args => args[0] === false), 'click-through off on hover');
  await click(one, p.stop);
  await until(() => count('overlay_stop') === 1, 'overlay_stop reached the core');
  await click(one, p.open);
  await until(() => count('overlay_open') === 1, 'overlay_open reached the core');
  assert.equal((await panel(one)).visible, 'true', 'Open JARVIS before the end keeps the panel');
  mouse(one, 'mouseMove', 2, 2);
  await until(() => calls.ignoreMouse.at(-1)[0] === true && calls.ignoreMouse.at(-1)[1]?.forward === true, 'click-through back on');
  assert.equal(calls.focus, 0);
  pass('buttons', 'Stop and Open JARVIS clicks reached the fake core as overlay_stop and overlay_open (with ack, no payload); hover toggled click-through');

  const endedAt = Date.now();
  await push({ state: 'ended', user: asked2, user_final: true, jarvis: answer2, jarvis_final: true, end: { kind: 'quiet', message: null } });
  p = await show(one, x => x.end === 'quiet', 'ended quiet');
  assert.deepEqual(p.top, { text: 'Voice is off', tone: 'tertiary', clipped: undefined });
  assert.equal(p.main.tone, 'secondary');
  assert.ok(p.open);
  assert.equal(p.stop, null);
  assert.equal(p.ring, 'offline');
  await shoot(one, '09-ended-quiet');
  assert.equal(await exited(one, 7000), 0);
  const held = one.state.quitAt - endedAt;
  assert.ok(held >= 3900 && held <= 5500, `quiet hold ${held} ms`);
  pass('ended quiet', `asked to quit ${held} ms after the end (4 s hold + 180 ms fade), exit code 0`);
  return one;
}

async function sessionTwo() {
  const asked = 'Hey Jarvis, play something calm.';
  const message = 'Voice stopped: the microphone is in use by another app.';
  captions.add(asked); captions.add(message);
  await push({ session: 's2', state: 'listening', user: asked, user_final: true });
  const two = await launch();
  await show(two, x => x.visible === 'true', 'session 2 shown');
  const endedAt = Date.now();
  await push({ session: 's2', state: 'ended', user: asked, user_final: true, end: { kind: 'error', message } });
  const p = await show(two, x => x.end === 'error', 'ended error');
  assert.equal(p.top, null);
  assert.deepEqual(p.main, { text: message, tone: 'warn', clipped: 'false' });
  assert.equal(p.stop, null);
  assert.equal(p.open, null);
  await shoot(two, '10-ended-error');
  // Hover near the end of the 8 s hold pauses it; leaving resumes with at least 2 s left.
  await sleep(Math.max(0, endedAt + 7000 - Date.now()));
  mouse(two, 'mouseMove', p.rect.x + 40, p.rect.y + 40);
  await sleep(Math.max(0, endedAt + 8600 - Date.now()));
  assert.equal((await panel(two))?.visible, 'true', 'hover paused the error countdown');
  const leftAt = Date.now();
  mouse(two, 'mouseMove', 2, 2);
  assert.equal(await exited(two, 5000), 0);
  const resumed = two.state.quitAt - leftAt;
  assert.ok(resumed >= 1900 && resumed <= 3200, `resumed ${resumed} ms`);
  pass('ended error', `warn message, no top line; hover at 7 s held it past 8.6 s; left → quit ${resumed} ms later (2 s minimum + fade), exit code 0`);
}

async function sessionThree() {
  const answer = 'Okay, stopping now.';
  captions.add(answer);
  await push({ session: 's3', state: 'speaking', user: 'Hey Jarvis, stop.', user_final: true, jarvis: answer });
  const three = await launch();
  await show(three, x => x.visible === 'true' && x.main?.text === answer, 'session 3 speaking');
  await run(three, `(() => { window.qaNow = null; new MutationObserver(() => {
    const p = document.querySelector('.overlay-panel');
    if (!window.qaNow && p && p.dataset.end === 'now') window.qaNow = { top: !!p.querySelector('.overlay-top'), main: !!p.querySelector('.overlay-main'), buttons: p.querySelectorAll('button').length, visible: p.dataset.visible };
  }).observe(document.getElementById('root'), { subtree: true, childList: true, attributes: true, characterData: true }); })()`);
  const endedAt = Date.now();
  await push({ session: 's3', state: 'ended', user: 'Hey Jarvis, stop.', user_final: true, jarvis: answer, end: { kind: 'now', message: null } });
  const seen = await until(() => run(three, 'window.qaNow').catch(() => null), 'now observed', 2000, 10);
  assert.deepEqual(seen, { top: false, main: false, buttons: 0, visible: 'false' });
  try { await shoot(three, '11-ended-now'); } catch { pass('ended now screenshot', 'window closed before capture'); }
  assert.equal(await exited(three, 2000), 0);
  pass('ended now', `text and buttons gone in the same commit as the end; asked to quit ${three.state.quitAt - endedAt} ms after it, exit code 0`);
}

async function sessionFour() {
  // A new session during the hold cancels the close; then a server disconnect fades out over 1 s.
  await push({ session: 's4', state: 'ended', end: { kind: 'quiet', message: null } });
  const four = await launch();
  await show(four, x => x.end === 'quiet', 'session 4 holding');
  await sleep(1000);
  await push({ session: 's5', state: 'connecting' });
  await show(four, x => x.end === 'none' && x.visible === 'true', 'new session shown');
  await sleep(4000);
  assert.equal(four.state.quitAt, null, 'the new session cancelled the close');
  assert.equal((await panel(four)).top.text, 'Connecting…');
  pass('cancel', 'a new running session during the quiet hold kept the panel open past 5 s');
  await push({ session: 's5', state: 'listening', user: 'Hey Jarvis, are you there?' });
  captions.add('Hey Jarvis, are you there?');
  const before = await show(four, x => x.top?.text.includes('Are you'), 'session 5 listening');
  const opacityBefore = calls.opacity.length;
  const droppedAt = Date.now();
  await command({ op: 'disconnect' });
  await sleep(500);
  const during = await panel(four).catch(() => null);
  if (during) assert.equal(during.top.text, before.top.text, 'no text change while fading');
  assert.equal(await exited(four, 3000), 0);
  const steps = calls.opacity.slice(opacityBefore).map(args => args[0]);
  assert.ok(steps.length >= 5 && steps.at(-1) === 0 && steps.every((value, index) => index === 0 || value <= steps[index - 1]), 'opacity fades to 0');
  const faded = four.state.quitAt - droppedAt;
  assert.ok(faded >= 900 && faded <= 2000, `disconnect fade ${faded} ms`);
  pass('disconnect', `server disconnect faded the window over ${faded} ms in ${steps.length} steps with no text change, exit code 0`);
}

async function sessionFive() {
  const shown = calls.showInactive;
  const refusedBefore = events.filter(event => event.event === 'connect' && !event.accepted).length;
  const five = await launch({ token: 'f'.repeat(64) });
  assert.equal(await exited(five, 5000), 1);
  assert.ok(events.filter(event => event.event === 'connect' && !event.accepted).length > refusedBefore, 'the fake core refused the token');
  assert.equal(calls.showInactive, shown, 'never shown');
  pass('refused connection', 'a wrong token was refused by the fake core; the overlay quit with code 1 and never showed');
}

async function sessionSix() {
  await command({ op: 'silent', value: true });
  const accepted = () => events.filter(event => event.event === 'connect' && event.accepted).length;
  const acceptedBefore = accepted();
  const six = await launch();
  const startedAt = Date.now();
  await until(() => accepted() > acceptedBefore, 'connected');
  await sleep(300);
  for (const data of [{ ...snapshot({}), state: 'sleeping' }, { ...snapshot({}), user: 5 }, 'text', null])
    await command({ op: 'raw', event: 'voice_overlay', data });
  await command({ op: 'raw', event: 'voice_level', data: { level: 'loud' } });
  assert.equal(await exited(six, 13000), 1);
  const waited = six.state.quitAt - startedAt;
  assert.ok(waited >= 9800 && waited <= 11500, `first-snapshot timeout ${waited} ms`);
  assert.ok(logs.filter(line => line === 'dropped an invalid snapshot').length >= 4);
  await command({ op: 'silent', value: false });
  pass('no snapshot', `invalid payloads were dropped and did not count; quit after ${waited} ms with code 1`);
}

app.whenReady().then(async () => {
  let code = 0;
  try {
    const html = fs.readFileSync(path.join(ROOT, 'dist', 'overlay.html'), 'utf8');
    assert.match(html, /<meta http-equiv="Content-Security-Policy" content="[^"]*script-src 'self'[^"]*connect-src 'self';/);
    assert.equal(/<script(?![^>]*\ssrc=)[^>]*>|<style[\s>]/i.test(html), false);
    pass('dist/overlay.html', 'CSP meta present (connect-src self), no inline script or style');
    port = await startCore();
    assert.notEqual(port, 8000);
    pass('fake core', `127.0.0.1:${port}`);
    const one = await sessionOne();
    await sessionTwo();
    await sessionThree();
    await sessionFour();
    await sessionFive();
    await sessionSix();
    assert.equal(calls.show + calls.focus, 0, 'never show() or focus()');
    const leaked = logs.filter(line => line.includes(TOKEN) || [...captions].some(text => line.includes(text)));
    assert.deepEqual(leaked, [], 'logs never contain the token or captions');
    pass('logging', `${logs.length} log lines, none with the token or caption text`);
    assert.deepEqual(one.blocked, [], 'renderer made no network requests');
    pass('renderer network', 'no non-file requests');
    report.consoleErrors = one.errors;
    report.passed = true;
  } catch (error) {
    report.passed = false;
    report.error = String(error.stack || error);
    code = 1;
  }
  report.logs = logs;
  fs.writeFileSync(path.join(OUTPUT, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  try { core?.stdin.end(); core?.kill(); } catch { /* already gone */ }
  for (const window of BrowserWindow.getAllWindows()) window.destroy();
  app.exit(code);
});
