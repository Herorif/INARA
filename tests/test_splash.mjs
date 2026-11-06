import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { SPLASH_FADE_MS, dismissSplash } from '../src/app/splash.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = name => fs.readFileSync(path.join(ROOT, name), 'utf8').replace(/\r\n/g, '\n');

// A document holding one #splash element, a reduced-motion query and a manual clock.
function harness({ reduce = false, present = true } = {}) {
  const classes = new Set();
  const timers = [];
  const queries = [];
  let attached = present;
  const splash = {
    classList: { add: name => classes.add(name), contains: name => classes.has(name) },
    removals: 0,
    remove() { this.removals += 1; attached = false; },
  };
  const document = {
    getElementById: id => (id === 'splash' && attached ? splash : null),
    defaultView: { matchMedia: query => { queries.push(query); return { matches: reduce }; } },
  };
  const setTimeout = (callback, ms) => { timers.push({ callback, ms }); return timers.length; };
  return { splash, classes, timers, queries, document, setTimeout };
}

test('the splash fades, then is removed after the 180 ms fade', () => {
  const h = harness();
  assert.equal(SPLASH_FADE_MS, 180);
  assert.equal(dismissSplash({ document: h.document, setTimeout: h.setTimeout }), true);
  assert.ok(h.classes.has('is-done'), 'the done class starts the fade at once');
  assert.equal(h.splash.removals, 0, 'still in the document while it fades');
  assert.deepEqual(h.timers.map(timer => timer.ms), [180]);
  assert.deepEqual(h.queries, ['(prefers-reduced-motion: reduce)']);
  h.timers[0].callback();
  assert.equal(h.splash.removals, 1);
});

test('with reduced motion the splash is removed at once', () => {
  const h = harness({ reduce: true });
  assert.equal(dismissSplash({ document: h.document, setTimeout: h.setTimeout }), true);
  assert.ok(h.classes.has('is-done'));
  assert.equal(h.splash.removals, 1);
  assert.equal(h.timers.length, 0, 'no timer, no wait');
  const forced = harness();
  dismissSplash({ document: forced.document, setTimeout: forced.setTimeout, reducedMotion: true });
  assert.equal(forced.splash.removals, 1);
  assert.equal(forced.queries.length, 0, 'an injected preference wins over the media query');
});

test('dismissing twice (StrictMode effects) or without a splash does nothing more', () => {
  const h = harness();
  dismissSplash({ document: h.document, setTimeout: h.setTimeout });
  assert.equal(dismissSplash({ document: h.document, setTimeout: h.setTimeout }), false);
  assert.equal(h.timers.length, 1);
  h.timers[0].callback();
  assert.equal(dismissSplash({ document: h.document, setTimeout: h.setTimeout }), false);
  const none = harness({ present: false });
  assert.equal(dismissSplash({ document: none.document, setTimeout: none.setTimeout }), false);
  assert.equal(none.timers.length, 0);
  assert.equal(dismissSplash({ document: null, setTimeout: none.setTimeout }), false);
});

test('index.html paints a static splash before #root with an external stylesheet', () => {
  const html = read('index.html');
  const head = html.slice(0, html.indexOf('</head>'));
  assert.match(head, /<link rel="stylesheet" href="\/src\/app\/splash\.css" \/>/);
  assert.match(html, /<div id="splash" aria-hidden="true"><img src="\/src\/assets\/brand\/splash-core-720\.png" alt="" width="360" height="360" \/><span>JARVIS<\/span><\/div>\n\s*<div id="root"><\/div>/);
  // vite.config.js's CSP plugin refuses inline scripts and styles.
  assert.doesNotMatch(html, /<style[\s>]|<script(?![^>]*\ssrc=)[^>]*>/i);
  assert.doesNotMatch(read('overlay.html'), /splash/, 'the talking overlay has no splash');
});

test('the splash style: full window above the lock screen, centred, 180 ms fade', () => {
  const css = read('src/app/splash.css');
  const rule = selector => {
    const match = css.match(new RegExp(`(?:^|\\n)${selector.replace(/[.#]/g, '\\$&')} \\{([^}]*)\\}`));
    assert.ok(match, selector);
    return match[1];
  };
  const splash = rule('#splash');
  for (const part of ['position: fixed', 'inset: 0', 'background: #05080c', 'display: flex', 'flex-direction: column',
    'align-items: center', 'justify-content: center', 'gap: 14px', 'opacity: 1',
    'transition: opacity 180ms cubic-bezier(.2,.8,.2,1)']) assert.ok(splash.includes(part), part);
  assert.ok(Number(splash.match(/z-index: (\d+)/)[1]) > 9999, 'above .auth-lock (z-index 9999)');
  assert.match(rule('#splash.is-done'), /opacity: 0/);
  assert.match(rule('#splash img'), /width: min\(40vmin, 360px\)/);
  const word = rule('#splash span');
  for (const part of ['color: #e6eef5', 'letter-spacing: .34em', 'font-weight: 500', 'font-size: clamp(12px, 1.4vmin, 15px)',
    'font-family: "Segoe UI Variable", "Segoe UI", system-ui']) assert.ok(word.includes(part), part);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\) \{\n\s*#splash \{ transition: none; \}/);
});

test('the app shell dismisses the splash after the first React commit', () => {
  const main = read('src/main.jsx');
  assert.match(main, /import \{ dismissSplash \} from '\.\/app\/splash\.js'/);
  assert.match(main, /const Shell = \(\) => \{\n\s*useEffect\(\(\) => \{ dismissSplash\(\); \}, \[\]\);\n\s*return <App \/>;/);
  assert.match(main, /<React\.StrictMode>\n\s*<Shell \/>/);
});

test('the published splash render is 720 px RGBA', () => {
  const data = fs.readFileSync(path.join(ROOT, 'src/assets/brand/splash-core-720.png'));
  assert.equal(data.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
  assert.deepEqual([data.readUInt32BE(16), data.readUInt32BE(20), data[24], data[25]], [720, 720, 8, 6]);
});

test('the native host shows the window at first paint, never when hidden', () => {
  const host = read('electron/native-main.cjs');
  assert.match(host, /const showOnce = \(\) => \{ if \(shown \|\| bootstrap\.hide \|\| window\.isDestroyed\(\)\) return; shown = true; window\.show\(\); \};/);
  assert.match(host, /window\.once\('ready-to-show', showOnce\);/);
  // The fallback after the load shows it only if ready-to-show has not.
  const load = host.indexOf("else await window.loadFile(path.join(root, 'dist/index.html'));");
  assert.ok(load > host.indexOf("window.once('ready-to-show'"));
  assert.equal(host.slice(load).split('\n')[1].trim(), 'showOnce();');
  assert.doesNotMatch(host, /if \(!bootstrap\.hide\) window\.show\(\)/);
  assert.equal((host.match(/window\.show\(\)/g) || []).length, 1, 'only showOnce calls show() directly');
});
