// Screen help (docs/SCREEN_HELP.md): the core's one `screen_capture` request per approved
// look_at_screen, answered once over the workspace control socket's acknowledgement.
// One still of the display under the cursor ("whole") or of one window ("window", the HWND
// the core chose), at most 1600 px wide, JPEG quality 80. The image is returned as base64
// and dropped here; nothing is written, logged or sent to the page.
const MAX_WIDTH = 1600;
const QUALITY = 80;
const SETTLE_MS = 150; // lets content protection take effect before the frame
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const HWND = /^[1-9][0-9]{0,19}$/;

/** {region, hwnd?} from the core's request, or null when it is malformed. */
function parseRequest(data) {
  if (!data || typeof data !== 'object' || !UUID.test(data.request_id ?? '')) return null;
  if (data.region === 'whole') return { region: 'whole' };
  if (data.region === 'window' && typeof data.hwnd === 'string' && HWND.test(data.hwnd)) return { region: 'window', hwnd: data.hwnd };
  return null;
}

/** The thumbnail size for a display: its physical pixels, at most MAX_WIDTH wide, never upscaled. */
function displaySize(display) {
  const scale = Number(display?.scaleFactor) > 0 ? Number(display.scaleFactor) : 1;
  const width = Math.max(1, Math.round((display?.size?.width || 1) * scale));
  const height = Math.max(1, Math.round((display?.size?.height || 1) * scale));
  const target = Math.min(MAX_WIDTH, width);
  return { width: target, height: Math.max(1, Math.round(height * target / width)) };
}

function createScreenCapture({ desktopCapturer, screen, powerMonitor, windows, settle = ms => new Promise(resolve => setTimeout(resolve, ms)) }) {
  let locked = false, busy = false;
  const onLock = () => { locked = true; };
  const onUnlock = () => { locked = false; };
  powerMonitor?.on?.('lock-screen', onLock);
  powerMonitor?.on?.('unlock-screen', onUnlock);
  const own = () => windows().filter(window => window && !window.isDestroyed());

  // JARVIS's own windows leave a whole-screen frame: content protection for the capture only.
  async function hidingJarvis(run) {
    const changed = [];
    for (const window of own()) {
      const protectedAlready = typeof window.isContentProtected === 'function' && window.isContentProtected();
      if (!protectedAlready) { window.setContentProtection(true); changed.push(window); }
    }
    try {
      if (changed.length) await settle(SETTLE_MS);
      return await run();
    } finally {
      for (const window of changed) if (!window.isDestroyed()) window.setContentProtection(false);
    }
  }

  async function sourceFor(request) {
    if (request.region === 'whole') {
      const display = screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
      const sources = await desktopCapturer.getSources({ types: ['screen'], thumbnailSize: displaySize(display), fetchWindowIcons: false });
      return sources.find(source => source.display_id === String(display.id)) ?? (sources.length === 1 ? sources[0] : null);
    }
    const id = `window:${request.hwnd}:0`;
    const sources = await desktopCapturer.getSources({ types: ['window'], thumbnailSize: { width: MAX_WIDTH, height: MAX_WIDTH }, fetchWindowIcons: false });
    return sources.find(source => source.id === id) ?? null;
  }

  /** One capture: {image} (base64 JPEG) or {error}. Never throws. */
  async function capture(data) {
    const request = parseRequest(data);
    if (!request) return { error: 'failed' };
    if (locked) return { error: 'locked' };
    if (busy) return { error: 'busy' };
    if (request.region === 'window' && own().some(window => window.getMediaSourceId?.() === `window:${request.hwnd}:0`)) return { error: 'own_window' };
    busy = true;
    let image = null;
    try {
      const source = request.region === 'whole' ? await hidingJarvis(() => sourceFor(request)) : await sourceFor(request);
      if (!source) return { error: request.region === 'window' ? 'no_window' : 'failed' };
      if (locked) return { error: 'locked' };
      image = source.thumbnail;
      if (!image || image.isEmpty()) return { error: 'failed' };
      if (image.getSize().width > MAX_WIDTH) image = image.resize({ width: MAX_WIDTH, quality: 'good' });
      return { image: image.toJPEG(QUALITY).toString('base64') };
    } catch {
      return { error: 'failed' };
    } finally {
      image = null;
      busy = false;
    }
  }

  const dispose = () => {
    powerMonitor?.removeListener?.('lock-screen', onLock);
    powerMonitor?.removeListener?.('unlock-screen', onUnlock);
  };
  return { capture, dispose, isLocked: () => locked };
}

module.exports = { MAX_WIDTH, QUALITY, createScreenCapture, displaySize, parseRequest };
