import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { authLockCameraState, authLockMessage } from '../src/components/authLockView.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = name => fs.readFileSync(path.join(ROOT, name), 'utf8').replace(/\r\n/g, '\n');
const source = () => read('src/components/AuthLock.jsx');
const rule = selector => {
  const css = read('src/app/workspace.css');
  const match = css.match(new RegExp(`\\n${selector.replace(/[.[\]"=]/g, '\\$&')} \\{([^}]*)\\}`));
  assert.ok(match, selector);
  return match[1];
};

test('the status line and the camera rim follow the lock status', () => {
  assert.equal(authLockMessage('looking'), 'Looking for your face…');
  assert.equal(authLockMessage('recognized'), 'Face recognized');
  assert.equal(authLockMessage('rejected'), 'Face not recognized. Try again.');
  assert.equal(authLockCameraState('recognized'), 'recognized');
  for (const status of ['looking', 'rejected', undefined]) assert.equal(authLockCameraState(status), 'looking');
});

test('the face camera sits inside the dial, above the title and status', () => {
  const jsx = source();
  assert.doesNotMatch(jsx, /BrandMark/, 'the dial is the mark');
  assert.match(jsx, /import lockDial from '\.\.\/assets\/brand\/lock-dial-720\.png';/);
  const dial = jsx.indexOf('<div className="auth-lock__dial">');
  const art = jsx.indexOf('<img className="auth-lock__dial-art" src={lockDial} alt="" aria-hidden="true" draggable="false" />');
  const camera = jsx.indexOf('<div className="auth-lock__camera" data-state={authLockCameraState(status)}>');
  const title = jsx.indexOf('<h1 id="auth-lock-title">Locked</h1>');
  const status = jsx.indexOf('<p className="auth-lock__status" role="status" data-state={status}>{message}</p>');
  assert.ok(jsx.indexOf('<div className="auth-lock__content">') < dial && dial < art && art < camera && camera < title && title < status);
  const cameraBlock = jsx.slice(camera, title);
  assert.match(cameraBlock, /\{frameSrc \? <img src=\{frameSrc\} alt="Camera preview for face unlock" \/> : <User size=\{40\} strokeWidth=\{1\.25\} aria-hidden="true" \/>\}/);
  assert.equal((cameraBlock.match(/<\/div>/g) || []).length, 2, 'the camera closes, then the dial, before the title');
  assert.match(jsx, /role="dialog" aria-modal="true" aria-labelledby="auth-lock-title"/);
});

test('the lock timings and fade are unchanged', () => {
  const jsx = source();
  assert.match(jsx, /const RECOGNIZED_HOLD_MS = 2000;/);
  assert.match(jsx, /const FADE_MS = 180;/);
  assert.match(rule('.auth-lock'), /z-index:9999;.*transition:opacity var\(--dur-base\) var\(--ease-out\);/);
  assert.match(rule('.auth-lock.is-leaving'), /opacity:0; pointer-events:none;/);
});

test('the dial and its circular camera', () => {
  assert.match(rule('.auth-lock__dial'), /position:relative;.*width:min\(60vmin,360px\); height:min\(60vmin,360px\);/);
  assert.match(rule('.auth-lock__dial-art'), /position:absolute; inset:0; width:100%; height:100%;/);
  const camera = rule('.auth-lock__camera');
  // inset 26.5% on every side leaves a centred circle 47% of the dial across.
  assert.match(camera, /position:absolute; inset:26\.5%; box-sizing:border-box;/);
  for (const part of ['border:2px solid var(--line-strong);', 'border-radius:50%;', 'background:var(--bg-panel);', 'overflow:hidden;'])
    assert.ok(camera.includes(part), part);
  assert.equal(rule('.auth-lock__camera[data-state="recognized"]').trim(), 'border-color:var(--ok);');
  assert.match(rule('.auth-lock__camera img'), /object-fit:cover; transform:scaleX\(-1\);/);
  for (const selector of ['.auth-lock__dial', '.auth-lock__dial-art', '.auth-lock__camera', '.auth-lock__camera[data-state="recognized"]'])
    assert.doesNotMatch(rule(selector), /transition|animation/, `${selector}: no new motion`);
});

test('the published dial render is 720 px RGBA', () => {
  const data = fs.readFileSync(path.join(ROOT, 'src/assets/brand/lock-dial-720.png'));
  assert.equal(data.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
  assert.deepEqual([data.readUInt32BE(16), data.readUInt32BE(20), data[24], data[25]], [720, 720, 8, 6]);
});
