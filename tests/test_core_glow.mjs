import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { AdditiveBlending, Color, DataTexture, Vector3 } from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import {
  BREATH, GLOW_COLOR, GLOW_TARGETS, GLOW_TAU, GLOW_VISIBLE, PARALLAX_MAX, SPEAK_GAIN, SWEEP, breathing, flatGlow,
  glowMode, glowOpacity, glowTarget, initialGlow, parallaxEnabled, parallaxOffset, stepGlow, sweeping,
} from '../src/app/glowModel.js';
import { CORE_STATES, cameraFor, frameInterval, initialPose } from '../src/app/coreModel.js';
import { GLOW_BACK, GLOW_FILL, createCore, createGlowTexture } from '../src/app/coreScene.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const GLB = path.join(ROOT, 'src', 'assets', 'models', 'jarvis-core.glb');
const close = (actual, expected, tolerance, label) =>
  assert.ok(Math.abs(actual - expected) <= tolerance, `${label}: ${actual} != ${expected} (±${tolerance})`);
const parseCore = async () => {
  const bytes = fs.readFileSync(GLB);
  const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  const gltf = await new Promise((resolve, reject) => new GLTFLoader().parse(buffer, '', resolve, reject));
  return gltf.scene;
};
const map = () => new DataTexture(new Uint8Array([255, 255, 255, 255]), 1, 1);
const opacityAt = (state, extra = {}) => glowOpacity(initialGlow(state), { time: 1, ...extra });

// glowModel: state → intensity ---------------------------------------------------------

test('every core state has glow weights; aliases map like the core', () => {
  assert.deepEqual(Object.keys(GLOW_TARGETS).sort(), [...CORE_STATES].sort());
  assert.equal(glowTarget('recording'), GLOW_TARGETS.listening);
  assert.equal(glowTarget('playback'), GLOW_TARGETS.speaking);
  assert.equal(glowTarget('thinking'), GLOW_TARGETS.working);
  assert.equal(glowTarget('nonsense'), GLOW_TARGETS.idle);
  assert.equal(GLOW_COLOR, '#70e0ed');
});

test('idle is dim, listening a little brighter, offline off', () => {
  const idle = glowOpacity(initialGlow('idle'), { mode: 'static' });
  const listening = glowOpacity(initialGlow('listening'), { mode: 'static' });
  assert.ok(idle > 0.1 && idle < 0.4, `idle ${idle}`);
  assert.ok(listening > idle && listening - idle < 0.2, `listening ${listening} vs idle ${idle}`);
  assert.equal(opacityAt('offline'), 0);
  assert.equal(opacityAt('offline', { voice: 1 }), 0);
});

test('speaking pulses with the output level, other states ignore it', () => {
  const quiet = opacityAt('speaking', { voice: 0 }), loud = opacityAt('speaking', { voice: 1 });
  close(loud - quiet, SPEAK_GAIN, 1e-9, 'speaking gain');
  close(opacityAt('speaking', { voice: 0.5 }), quiet + SPEAK_GAIN * 0.5, 1e-9, 'half level');
  assert.equal(opacityAt('speaking', { voice: 7 }), loud, 'voice is clamped to 1');
  for (const state of ['idle', 'listening', 'working']) assert.equal(opacityAt(state, { voice: 1 }), opacityAt(state, { voice: 0 }), state);
});

test('working sweeps its intensity slowly; listening and speaking hold still', () => {
  const values = [0, 0.6, 1.2, 1.8].map(time => glowOpacity(initialGlow('working'), { time }));
  const level = GLOW_TARGETS.working.level;
  close(values[0], level * (1 - SWEEP.depth), 1e-9, 'sweep low');
  close(values[2], level * (1 + SWEEP.depth), 1e-9, 'sweep high at half a period');
  assert.ok(SWEEP.period > 2, 'slow');
  for (const state of ['listening', 'speaking']) assert.equal(opacityAt(state, { time: 0 }), opacityAt(state, { time: 2 }), state);
});

test('the pose offline weight dims every state to zero', () => {
  const full = opacityAt('listening');
  close(opacityAt('listening', { offline: 0.5 }), full / 2, 1e-9, 'half offline');
  assert.equal(opacityAt('listening', { offline: 1 }), 0);
});

test('weights ease between states frame-rate independently and stay in range', () => {
  const one = stepGlow(initialGlow('idle'), glowTarget('speaking'), 100);
  let many = initialGlow('idle');
  for (let i = 0; i < 10; i += 1) many = stepGlow(many, glowTarget('speaking'), 10);
  for (const key of Object.keys(one)) close(one[key], many[key], 1e-9, key);
  const k = Math.exp(-100 / GLOW_TAU);
  close(one.breath, k, 1e-9, 'breath decays');
  close(one.speak, 1 - k, 1e-9, 'speak rises');
  assert.deepEqual(stepGlow(initialGlow('idle'), glowTarget('working'), -5), initialGlow('idle'), 'no negative time');
  for (const state of CORE_STATES) for (const voice of [0, 1]) for (const time of [0, 1, 2, 3]) {
    const value = glowOpacity(initialGlow(state), { voice, time });
    assert.ok(value >= 0 && value <= 1, `${state} ${value}`);
  }
});

// glowModel: breathing -----------------------------------------------------------------

test('breathing is a 4 s ease-in-out cycle of about ±15%', () => {
  assert.equal(BREATH.period, 4);
  close(BREATH.depth, 0.15, 1e-9, 'depth');
  close(breathing(0), 0.85, 1e-9, 'start dim');
  close(breathing(1), 1, 1e-9, 'quarter');
  close(breathing(2), 1.15, 1e-9, 'peak at 2 s');
  close(breathing(4), 0.85, 1e-9, 'back at 4 s');
  close(breathing(6.5), breathing(2.5), 1e-9, 'periodic');
  // Ease-in-out: slow near the ends, fastest in the middle.
  assert.ok(breathing(0.2) - breathing(0) < breathing(1.1) - breathing(0.9));
  close(breathing(Number.NaN), 0.85, 1e-9, 'bad time is t = 0');
  close(sweeping(SWEEP.period / 2), 1 + SWEEP.depth, 1e-9, 'sweep uses the same curve');
});

test('idle glow breathes in breathe mode and holds still in static mode', () => {
  const level = GLOW_TARGETS.idle.level;
  close(glowOpacity(initialGlow('idle'), { time: 0 }), level * 0.85, 1e-9, 'dim');
  close(glowOpacity(initialGlow('idle'), { time: 2 }), level * 1.15, 1e-9, 'bright');
  for (const time of [0, 1, 2, 3]) close(glowOpacity(initialGlow('idle'), { time, mode: 'static' }), level, 1e-9, `static ${time}`);
  close(glowOpacity(initialGlow('working'), { time: 0, mode: 'static' }), GLOW_TARGETS.working.level, 1e-9, 'static working');
  assert.equal(glowOpacity(initialGlow('speaking'), { voice: 1, mode: 'off' }), 0, 'off');
});

// glowModel: the on/off rule -----------------------------------------------------------

test('gaming mode has no glow; reduced motion or low battery a still one', () => {
  assert.equal(glowMode(), 'breathe');
  assert.equal(glowMode({ gaming: true }), 'off');
  assert.equal(glowMode({ gaming: true, reducedMotion: true, lowBattery: true }), 'off');
  assert.equal(glowMode({ reducedMotion: true }), 'static');
  assert.equal(glowMode({ lowBattery: true }), 'static');
  assert.equal(flatGlow('idle', 'breathe'), 'breathe');
  assert.equal(flatGlow('speaking', 'static'), 'static');
  assert.equal(flatGlow('listening', 'off'), 'off');
  assert.equal(flatGlow('offline', 'breathe'), 'off', 'offline: no glow');
  assert.equal(flatGlow('idle', undefined), 'breathe');
});

test('parallax runs only in full motion', () => {
  assert.equal(parallaxEnabled('full'), true);
  for (const mode of ['fade', 'instant', undefined]) assert.equal(parallaxEnabled(mode), false, String(mode));
});

// glowModel: parallax clamp ------------------------------------------------------------

test('parallax moves toward the pointer, at most 4 px, 0 at the centre', () => {
  const box = { left: 100, top: 50, width: 800, height: 400 };
  assert.equal(PARALLAX_MAX, 4);
  assert.deepEqual(parallaxOffset({ x: 500, y: 250 }, box), { x: 0, y: 0 });
  assert.deepEqual(parallaxOffset({ x: 900, y: 450 }, box), { x: 4, y: 4 });
  assert.deepEqual(parallaxOffset({ x: 100, y: 50 }, box), { x: -4, y: -4 });
  assert.deepEqual(parallaxOffset({ x: 700, y: 150 }, box), { x: 2, y: -2 });
  assert.deepEqual(parallaxOffset({ x: 5000, y: -5000 }, box), { x: 4, y: -4 }, 'clamped outside the box');
  assert.deepEqual(parallaxOffset({ x: 900, y: 450 }, box, 2), { x: 2, y: 2 }, '2 px variant');
  assert.deepEqual(parallaxOffset(null, box), { x: 0, y: 0 }, 'no pointer: at rest');
  assert.deepEqual(parallaxOffset({ x: 1, y: 1 }, { left: 0, top: 0, width: 0, height: 0 }), { x: 0, y: 0 }, 'empty box');
  assert.deepEqual(parallaxOffset({ x: Number.NaN, y: 450 }, box), { x: 0, y: 4 }, 'bad coordinate is the centre');
  assert.ok(Object.is(parallaxOffset({ x: 500, y: 250 }, box).x, 0), 'no negative zero');
});

// coreScene: the sprite ----------------------------------------------------------------

test('the core gets an additive cyan sprite behind it that never writes depth', async () => {
  const core = createCore(await parseCore(), { lod: 'full', cssSize: 150, glowMap: map() });
  const { glow } = core;
  assert.ok(glow?.isSprite, 'sprite');
  assert.equal(glow.parent, core.scene);
  assert.equal(glow.material.blending, AdditiveBlending);
  assert.equal(glow.material.depthWrite, false);
  assert.equal(glow.material.depthTest, true, 'the faces cover it');
  assert.equal(glow.material.transparent, true);
  assert.ok(glow.material.color.equals(new Color(GLOW_COLOR)));
  assert.equal(glow.renderOrder, -1);
  assert.equal(glow.visible, false, 'hidden until the first frame sets it');
  // Behind the origin, seen from the camera, and fading out inside the canvas.
  const view = cameraFor(150, 'full');
  const toCamera = new Vector3(...view.position).normalize();
  close(glow.position.dot(toCamera), -GLOW_BACK, 1e-9, 'behind the core');
  const extent = 2 * Math.tan(view.fov * Math.PI / 360) * (view.distance + GLOW_BACK);
  close(glow.scale.x, GLOW_FILL * extent, 1e-9, 'fills the frustum at its depth');
  assert.ok(GLOW_FILL < 1);
  core.dispose();
});

test('the sprite follows the level of detail and the glow opacity', async () => {
  const core = createCore(await parseCore(), { lod: 'full', cssSize: 150, glowMap: map() });
  const full = core.glow.scale.x;
  core.setLod('small');
  const view = cameraFor(150, 'small');
  close(core.glow.scale.x, GLOW_FILL * 2 * Math.tan(view.fov * Math.PI / 360) * (view.distance + GLOW_BACK), 1e-9, 'small LOD');
  assert.notEqual(core.glow.scale.x, full);
  core.setGlow(0.4);
  assert.equal(core.glow.material.opacity, 0.4);
  assert.equal(core.glow.visible, true);
  core.setGlow(GLOW_VISIBLE / 2);
  assert.equal(core.glow.visible, false, 'too faint: no draw call');
  core.setGlow(3);
  assert.equal(core.glow.material.opacity, 1);
  core.setGlow(Number.NaN);
  assert.equal(core.glow.visible, false);
  core.dispose();
});

test('dispose frees the sprite material and map but keeps the shared sprite geometry', async () => {
  const texture = map();
  const core = createCore(await parseCore(), { lod: 'full', cssSize: 150, glowMap: texture });
  const disposed = new Set();
  texture.addEventListener('dispose', () => disposed.add('map'));
  core.glow.material.addEventListener('dispose', () => disposed.add('material'));
  core.glow.geometry.addEventListener('dispose', () => disposed.add('geometry'));
  core.dispose();
  assert.deepEqual([...disposed].sort(), ['map', 'material']);
});

test('no canvas (node) or glowMap null: no sprite, and setGlow is a no-op', async () => {
  assert.equal(createGlowTexture(null), null);
  assert.equal(createGlowTexture({ createElement: () => ({ getContext: () => null }) }), null);
  for (const options of [{}, { glowMap: null }]) {
    const core = createCore(await parseCore(), { lod: 'full', cssSize: 150, ...options });
    assert.equal(core.glow, null);
    core.setGlow(0.5);
    let sprites = 0;
    core.scene.traverse(node => { if (node.isSprite) sprites += 1; });
    assert.equal(sprites, 0);
    core.dispose();
  }
});

test('the glow does not change the core frame rate: idle stays at 15 fps', () => {
  // The sprite is drawn inside the core's own frame; the loop's interval rule is untouched.
  assert.equal(frameInterval('idle', false), 1000 / 15);
  assert.equal(frameInterval('offline', false), null);
  assert.ok(initialPose('idle').offline === 0);
});
