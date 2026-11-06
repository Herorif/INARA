// Icon review sheet (developer tool): renders the icon set built by scripts/build-icons.py
// into one PNG for the owner to judge. Run after build-icons:
//
//   node_modules\.bin\electron scripts\icon-review.cjs
//
// The page is generated from the files in .runtime/icons/review/ (ICO frames are read out
// of the .ico files themselves), loaded in an offscreen window that is never shown, with
// an isolated profile under .runtime/icons/, and captured at device scale factor 1 to
// .runtime/icons/review/review-sheet.png. Nothing is fetched: every image is a data URL.
'use strict';

const { app, BrowserWindow } = require('electron');
// Retries capturePage's transient UnknownVizError; must load before any window exists.
require('./qa-capture-retry.cjs');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..');
const ICONS = path.join(ROOT, '.runtime', 'icons');
const REVIEW = path.join(ICONS, 'review');
const WIDTH = 1280;
const STATES = ['ready', 'talking', 'calls', 'attention', 'paused'];
const APP_SIZES = [256, 128, 96, 64, 48, 40, 32, 24, 20, 16];

app.setPath('userData', path.join(ICONS, 'electron-profile'));
app.commandLine.appendSwitch('force-device-scale-factor', '1');
app.disableHardwareAcceleration();

const dataUrl = buffer => `data:image/png;base64,${buffer.toString('base64')}`;
const file = name => fs.readFileSync(path.join(REVIEW, name));

function icoFrames(name) {
  const data = file(name);
  if (data.readUInt16LE(0) !== 0 || data.readUInt16LE(2) !== 1) throw Error(`${name} is not an ICO`);
  const frames = {};
  for (let i = 0; i < data.readUInt16LE(4); i += 1) {
    const entry = 6 + 16 * i;
    const size = data[entry] || 256;
    const length = data.readUInt32LE(entry + 8);
    const offset = data.readUInt32LE(entry + 12);
    frames[size] = dataUrl(data.subarray(offset, offset + length));
  }
  return frames;
}

function squirclePath(size, exponent) {
  const half = size / 2;
  const points = [];
  for (let i = 0; i < 128; i += 1) {
    const t = (2 * Math.PI * i) / 128;
    const c = Math.cos(t);
    const s = Math.sin(t);
    const x = half + half * Math.sign(c) * Math.abs(c) ** (2 / exponent);
    const y = half + half * Math.sign(s) * Math.abs(s) ** (2 / exponent);
    points.push(`${x.toFixed(2)} ${y.toFixed(2)}`);
  }
  return `M${points.join('L')}Z`;
}

function page() {
  const appIco = icoFrames('jarvis.ico');
  const tray = Object.fromEntries(STATES.map(state => [state, icoFrames(`tray/jarvis-${state}.ico`)]));
  const foreground = dataUrl(file('android/res/mipmap-xhdpi/ic_launcher_foreground.png'));
  const monochrome = dataUrl(file('android/res/mipmap-xhdpi/ic_launcher_monochrome.png'));
  const setup64 = dataUrl(file('setup/emblem-64.png'));
  const mark24 = dataUrl(file('ui/mark-24.png'));
  const manifest = JSON.parse(file('manifest.json').toString('utf8'));

  const img = (src, size, scale = 1, extra = '') =>
    `<img src="${src}" width="${size * scale}" height="${size * scale}"${scale > 1 ? ' class="px"' : ''}${extra}>`;
  const cell = (inner, label) => `<figure>${inner}<figcaption>${label}</figcaption></figure>`;
  const appRow = background => `<div class="row tile" style="background:${background}">${
    APP_SIZES.map(size => cell(img(appIco[size], size), `${size}`)).join('')}</div>`;
  const bar = (dark, size) => {
    const colour = dark ? '#f0f0f0' : '#1a1a1a';
    const app = dark ? '#3c4048' : '#c9ced6';
    const icons = STATES.map(state => img(tray[state][size], size, 1, ` title="${state}"`)).join('');
    return `<div class="bar" style="background:${dark ? '#1c1c1c' : '#eef0f3'};color:${colour};height:${size === 16 ? 48 : 72}px">
      <div class="apps"><span class="win" style="width:${size + 4}px;height:${size + 4}px"></span>${
        [0, 1, 2].map(() => `<span class="app" style="background:${app};width:${size + 8}px;height:${size + 8}px"></span>`).join('')}
        ${img(appIco[size === 16 ? 24 : 32], size === 16 ? 24 : 32)}</div>
      <div class="tray" style="gap:${size === 16 ? 11 : 16}px"><span class="chev" style="border-color:${colour}"></span>${icons}
      <span class="clock" style="font-size:${size === 16 ? 12 : 18}px">5:42 PM<br>6/11/2026</span></div></div>`;
  };
  const masks = {
    circle: 'border-radius:50%',
    squircle: `clip-path:path('${squirclePath(96, 5)}')`,
    'rounded square': 'border-radius:22px',
  };
  const adaptive = Object.entries(masks).map(([name, css]) => cell(
    `<div class="mask" style="${css}"><img src="${foreground}" width="144" height="144"></div>`, name)).join('');
  const themed = [['#d3e3f4', '#123a5a', 'themed, light'], ['#22303d', '#bcd9f0', 'themed, dark']]
    .map(([background, tint, label]) => cell(`<div class="mask" style="border-radius:50%;background:${background}">
      <div class="mono" style="background:${tint};-webkit-mask-image:url(${monochrome})"></div></div>`, label)).join('');
  const sources = manifest.source;

  return `<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">
<title>JARVIS icon review</title>
<style>
  * { box-sizing: border-box; }
  body { margin: 0; padding: 28px 32px 36px; width: ${WIDTH}px; background: #e7e9ec; color: #1f2328;
         font: 13px/1.4 "Segoe UI", system-ui, sans-serif; }
  h1 { font-size: 20px; font-weight: 600; margin: 0 0 4px; }
  h2 { font-size: 14px; font-weight: 600; margin: 26px 0 8px; }
  .note { color: #57606a; margin: 0 0 6px; }
  .row { display: flex; align-items: flex-end; gap: 22px; flex-wrap: wrap; }
  .tile { padding: 18px 20px 12px; border-radius: 8px; margin-bottom: 10px; }
  figure { margin: 0; display: flex; flex-direction: column; align-items: center; gap: 6px; }
  figcaption { font-size: 11px; color: #8b949e; }
  img { display: block; }
  img.px { image-rendering: pixelated; }
  .bar { display: flex; align-items: center; padding: 0 14px; border-radius: 8px; margin-bottom: 10px;
         font-family: "Segoe UI", system-ui, sans-serif; }
  .apps { flex: 1; display: flex; justify-content: center; align-items: center; gap: 12px; }
  .win { display: inline-block; background: #5fb3f0; border-radius: 2px; }
  .app { display: inline-block; border-radius: 5px; }
  .tray { display: flex; align-items: center; }
  .chev { width: 7px; height: 7px; border-left: 1.5px solid; border-top: 1.5px solid; transform: rotate(45deg);
          margin: 4px 4px 0; }
  .clock { text-align: right; line-height: 1.25; margin-left: 6px; }
  .mask { width: 96px; height: 96px; overflow: hidden; background: #05080c; position: relative; }
  .mask img { position: absolute; left: -24px; top: -24px; }
  .mono { position: absolute; left: -24px; top: -24px; width: 144px; height: 144px;
          -webkit-mask-size: 144px 144px; }
  .dark { background: #05080c; color: #e6eef5; }
  .setup { display: flex; align-items: center; gap: 16px; }
  .word { font-size: 22px; font-weight: 500; letter-spacing: .32em; color: #e6eef5; }
  .sub { font-size: 11px; letter-spacing: .12em; color: #7f93a6; margin-top: 4px; }
  .title { display: flex; align-items: center; gap: 8px; height: 36px; width: 520px; border-bottom: 1px solid #17212c; }
  .title b { font-size: 13px; font-weight: 500; color: #e6eef5; }
  .ctl { margin-left: auto; color: #9fb0bf; font-size: 13px; letter-spacing: 14px; }
  .pair { display: flex; gap: 22px; flex-wrap: wrap; }
  .grid { display: grid; grid-template-columns: 90px repeat(5, 1fr); gap: 10px 18px; align-items: end; }
  .grid .k { color: #57606a; align-self: center; }
  footer { margin-top: 24px; color: #8b949e; font-size: 11px; }
</style></head><body>
<h1>JARVIS icon set: crystal J (B2a review)</h1>
<p class="note">Everything below is read from .runtime/icons/review/: the app and tray frames come out of the .ico files. Images are shown 1:1 unless marked 6&times;.</p>

<h2>App icon (jarvis.ico): 256 to 16</h2>
<p class="note">48 and up: full renders. 40 and 32: simplified renders (no ticks, heavier ring). 24, 20, 16: drawn on the pixel grid.</p>
${appRow('#05080c')}
${appRow('#f3f3f3')}

<h2>Pixel frames at 6&times; (nearest neighbour)</h2>
<div class="row tile" style="background:#05080c">${[16, 20, 24].map(size => cell(img(appIco[size], size, 6), `${size} px`)).join('')}</div>

<h2>Tray: ready, talking, calls on, needs attention, paused</h2>
<p class="note">16 px strips at 100% scale, 24 px strips at 150%. The taskbar button beside the apps is the 24 or 32 frame of jarvis.ico.</p>
${bar(true, 16)}${bar(false, 16)}${bar(true, 24)}${bar(false, 24)}
<div class="tile" style="background:#d5d9de">
  <div class="grid">
    <span></span>${STATES.map(state => `<span class="k">${state}</span>`).join('')}
    <span class="k">16 at 6&times;</span>${STATES.map(state => img(tray[state][16], 16, 6)).join('')}
    <span class="k">24 at 6&times;</span>${STATES.map(state => img(tray[state][24], 24, 6)).join('')}
    <span class="k">16 20 24 32</span>${STATES.map(state => `<div class="row" style="gap:8px">${
      [16, 20, 24, 32].map(size => img(tray[state][size], size)).join('')}</div>`).join('')}
  </div>
</div>

<h2>Android adaptive icon (96 px) and themed monochrome</h2>
<p class="note">Foreground layer on the #05080C background, cut by launcher masks; the themed icons tint the monochrome layer.</p>
<div class="row tile" style="background:#0e1420">${adaptive}${themed}</div>

<h2>In place: Setup header and workspace title bar</h2>
<div class="pair">
  <div class="tile dark"><div class="setup">${img(setup64, 64)}<div><div class="word">JARVIS</div><div class="sub">YOUR DESKTOP COMPANION</div></div></div></div>
  <div class="tile dark"><div class="title">${img(mark24, 24)}<b>JARVIS</b><span class="ctl">&#8211;&#9633;&#215;</span></div></div>
</div>

<footer>Renders: ${sources.generator} (sha256 ${String(sources.generator_sha256).slice(0, 12)}&hellip;), Blender ${sources.blender_version}. Icons: ${manifest.generator} (sha256 ${String(manifest.generator_sha256).slice(0, 12)}&hellip;).</footer>
</body></html>`;
}

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

app.whenReady().then(async () => {
  let code = 0;
  try {
    const html = path.join(ICONS, 'review-sheet.html');
    fs.writeFileSync(html, page());
    const window = new BrowserWindow({
      width: WIDTH, height: 800, show: false, useContentSize: true,
      webPreferences: { offscreen: true, contextIsolation: true, sandbox: true, javascript: true },
    });
    await window.loadFile(html);
    const height = await window.webContents.executeJavaScript(
      'Math.ceil(document.documentElement.getBoundingClientRect().height)', true);
    window.setContentSize(WIDTH, height);
    await sleep(500);
    const image = await window.webContents.capturePage({ x: 0, y: 0, width: WIDTH, height });
    const out = path.join(REVIEW, 'review-sheet.png');
    fs.writeFileSync(out, image.toPNG());
    const size = image.getSize();
    console.log(`review sheet ${size.width}x${size.height}: ${out}`);
  } catch (error) {
    console.error(`icon-review: ${error.stack || error}`);
    code = 1;
  }
  app.exit(code);
});
