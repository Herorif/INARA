// S7.5 screen help (electron/screen-capture.cjs): one still per core request, with fakes for
// desktopCapturer, screen and powerMonitor. No real screen is captured.
const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { MAX_WIDTH, QUALITY, createScreenCapture, displaySize, parseRequest } = require('../electron/screen-capture.cjs');

const ID = '6f1c2a9e-3b4d-4e5f-8a6b-7c8d9e0f1a2b';
const JPEG = Buffer.from([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3]);

function image(width, height, log) {
  return {
    isEmpty: () => width === 0,
    getSize: () => ({ width, height }),
    resize: options => { log.push(['resize', options]); return image(options.width, Math.round(height * options.width / width), log); },
    toJPEG: quality => { log.push(['jpeg', quality, width]); return JPEG; },
  };
}

function setup({ sources = null, windows = [], width = 2560, height = 1440, scale = 1 } = {}) {
  const log = [];
  const power = new EventEmitter();
  const display = { id: 7, size: { width, height }, scaleFactor: scale };
  const desktopCapturer = {
    getSources: async options => {
      log.push(['sources', options, windows.map(window => window.protected)]);
      return sources ?? [
        { id: 'screen:0:0', display_id: '7', thumbnail: image(options.thumbnailSize.width, options.thumbnailSize.height, log) },
        { id: 'window:4242:0', display_id: '', thumbnail: image(1200, 800, log) },
      ];
    },
  };
  const screen = { getCursorScreenPoint: () => ({ x: 10, y: 10 }), getDisplayNearestPoint: () => display };
  const capture = createScreenCapture({ desktopCapturer, screen, powerMonitor: power, windows: () => windows, settle: async () => log.push(['settle']) });
  return { capture, log, power };
}

function fakeWindow(id, protectedAlready = false) {
  const window = { protected: protectedAlready, destroyed: false };
  Object.assign(window, {
    isDestroyed: () => window.destroyed,
    isContentProtected: () => window.protected,
    setContentProtection: value => { window.protected = value; },
    getMediaSourceId: () => id,
  });
  return window;
}

test('requests are validated: a uuid and whole, or window with a numeric HWND', () => {
  assert.deepEqual(parseRequest({ request_id: ID, region: 'whole' }), { region: 'whole' });
  assert.deepEqual(parseRequest({ request_id: ID, region: 'window', hwnd: '4242' }), { region: 'window', hwnd: '4242' });
  for (const bad of [null, {}, { request_id: 'x', region: 'whole' }, { request_id: ID, region: 'all' },
    { request_id: ID, region: 'window' }, { request_id: ID, region: 'window', hwnd: '0' }, { request_id: ID, region: 'window', hwnd: '12;rm' }]) {
    assert.equal(parseRequest(bad), null);
  }
});

test('thumbnails are physical pixels, at most 1600 wide, never upscaled', () => {
  assert.deepEqual(displaySize({ size: { width: 2560, height: 1440 }, scaleFactor: 1 }), { width: 1600, height: 900 });
  assert.deepEqual(displaySize({ size: { width: 1280, height: 720 }, scaleFactor: 1.5 }), { width: 1600, height: 900 });
  assert.deepEqual(displaySize({ size: { width: 1024, height: 768 }, scaleFactor: 1 }), { width: 1024, height: 768 });
});

test('whole screen: the display under the cursor, JARVIS hidden from the frame, JPEG 80', async () => {
  const workspace = fakeWindow('window:1:0'), already = fakeWindow('window:2:0', true);
  const { capture, log } = setup({ windows: [workspace, already] });
  const result = await capture.capture({ request_id: ID, region: 'whole' });
  assert.deepEqual(result, { image: JPEG.toString('base64') });
  const sources = log.find(item => item[0] === 'sources');
  assert.deepEqual(sources[1].types, ['screen']);
  assert.deepEqual(sources[1].thumbnailSize, { width: 1600, height: 900 });
  assert.deepEqual(sources[2], [true, true]); // both protected while the frame was taken
  assert.ok(log.some(item => item[0] === 'settle'));
  assert.deepEqual(log.find(item => item[0] === 'jpeg'), ['jpeg', QUALITY, 1600]);
  assert.equal(workspace.protected, false); // restored afterwards
  assert.equal(already.protected, true); // the overlay keeps its own protection
});

test('window: the HWND the core chose, downscaled past 1600, never JARVIS itself', async () => {
  const big = [{ id: 'window:4242:0', thumbnail: null }];
  const log = [];
  big[0].thumbnail = image(2400, 1600, log);
  const { capture } = setup({ sources: big });
  assert.deepEqual(await capture.capture({ request_id: ID, region: 'window', hwnd: '4242' }), { image: JPEG.toString('base64') });
  assert.deepEqual(log[0], ['resize', { width: MAX_WIDTH, quality: 'good' }]);
  assert.deepEqual(await capture.capture({ request_id: ID, region: 'window', hwnd: '9999' }), { error: 'no_window' });
  const own = setup({ windows: [fakeWindow('window:4242:0')] });
  assert.deepEqual(await own.capture.capture({ request_id: ID, region: 'window', hwnd: '4242' }), { error: 'own_window' });
  assert.equal(own.log.some(item => item[0] === 'sources'), false);
});

test('the Windows lock screen, bad requests and failures answer with an error only', async () => {
  const { capture, power, log } = setup();
  power.emit('lock-screen');
  assert.deepEqual(await capture.capture({ request_id: ID, region: 'whole' }), { error: 'locked' });
  assert.equal(log.length, 0);
  power.emit('unlock-screen');
  assert.ok((await capture.capture({ request_id: ID, region: 'whole' })).image);
  assert.deepEqual(await capture.capture({ region: 'whole' }), { error: 'failed' });
  const empty = setup({ sources: [{ id: 'screen:0:0', display_id: '7', thumbnail: image(0, 0, []) }] });
  assert.deepEqual(await empty.capture.capture({ request_id: ID, region: 'whole' }), { error: 'failed' });
  const none = setup({ sources: [] });
  assert.deepEqual(await none.capture.capture({ request_id: ID, region: 'whole' }), { error: 'failed' });
  const throwing = createScreenCapture({
    desktopCapturer: { getSources: async () => { throw Error('boom'); } },
    screen: { getCursorScreenPoint: () => ({}), getDisplayNearestPoint: () => ({ id: 1, size: { width: 100, height: 100 } }) },
    powerMonitor: new EventEmitter(), windows: () => [],
  });
  assert.deepEqual(await throwing.capture({ request_id: ID, region: 'whole' }), { error: 'failed' });
});

test('one capture at a time', async () => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const capture = createScreenCapture({
    desktopCapturer: { getSources: async () => { await gate; return [{ id: 's', display_id: '1', thumbnail: image(100, 100, []) }]; } },
    screen: { getCursorScreenPoint: () => ({}), getDisplayNearestPoint: () => ({ id: 1, size: { width: 100, height: 100 } }) },
    powerMonitor: new EventEmitter(), windows: () => [],
  });
  const first = capture.capture({ request_id: ID, region: 'whole' });
  assert.deepEqual(await capture.capture({ request_id: ID, region: 'whole' }), { error: 'busy' });
  release();
  assert.ok((await first).image);
  assert.ok((await capture.capture({ request_id: ID, region: 'whole' })).image);
});
