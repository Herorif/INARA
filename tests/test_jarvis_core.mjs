import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Color, Vector3 } from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import {
  CORE_FOV, CORE_SCALE_GAIN, CORE_STATES, CORE_TARGETS, EASED_KEYS, EDGE_GLOW, cameraFor, coreLod, coreTarget,
  frameInterval, initialPose, isSettled, levelEnvelope, presenceMode, presenceState, stepPose, syntheticPulse,
} from '../src/app/coreModel.js';
import { CORE_COLORS, CORE_NODES, PRIMARY_LINES, SECONDARY_LINES, SMALL_LOD_NODES, createCore } from '../src/app/coreScene.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const GLB = path.join(ROOT, 'src', 'assets', 'models', 'jarvis-core.glb');
const DEG = Math.PI / 180;
const close = (actual, expected, tolerance, label) =>
  assert.ok(Math.abs(actual - expected) <= tolerance, `${label}: ${actual} != ${expected} (±${tolerance})`);

const parseCore = async () => {
  const bytes = fs.readFileSync(GLB);
  const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  const gltf = await new Promise((resolve, reject) => new GLTFLoader().parse(buffer, '', resolve, reject));
  return gltf.scene;
};
const shown = node => { for (let item = node; item; item = item.parent) if (!item.visible) return false; return true; };

// coreModel ------------------------------------------------------------------------------

test('presence mode: 3d only at 64 px or more with motion, power and WebGL available', () => {
  const ok = { reducedMotion: false, lowPower: false, webgl: true };
  assert.equal(presenceMode({ ...ok, size: 63 }), 'flat');
  assert.equal(presenceMode({ ...ok, size: 64 }), '3d');
  assert.equal(presenceMode({ ...ok, size: 160, webgl: undefined }), '3d');
  assert.equal(presenceMode({ ...ok, size: 64, reducedMotion: true }), 'flat');
  assert.equal(presenceMode({ ...ok, size: 64, lowPower: true }), 'flat');
  assert.equal(presenceMode({ ...ok, size: 64, webgl: false }), 'flat');
});

test('level of detail: small below 96 px, full from 96 px', () => {
  assert.equal(coreLod(64), 'small');
  assert.equal(coreLod(95), 'small');
  assert.equal(coreLod(96), 'full');
  assert.equal(coreLod(160), 'full');
});

test('targets exist for all five states and aliases resolve through presenceState', () => {
  assert.deepEqual(Object.keys(CORE_TARGETS).sort(), [...CORE_STATES].sort());
  for (const state of CORE_STATES) for (const key of EASED_KEYS) assert.equal(typeof coreTarget(state)[key], 'number', `${state}.${key}`);
  const aliases = { recording: 'listening', transcribing: 'working', thinking: 'working', playback: 'speaking' };
  for (const [alias, state] of Object.entries(aliases)) {
    assert.equal(presenceState(alias), state);
    assert.deepEqual(coreTarget(alias), coreTarget(state));
  }
  assert.equal(presenceState('unknown'), 'idle');
  assert.deepEqual({ ...CORE_TARGETS.working }, { midSpeed: 60, innerSpeed: 30, arcSpeed: 120, tilt: 1, arcOpacity: 1, speak: 0, sweep: 1, offline: 0 });
  for (const state of ['idle', 'listening', 'speaking', 'offline']) assert.equal(CORE_TARGETS[state].sweep, 0, `${state} sweep`);
  assert.equal(CORE_TARGETS.listening.tilt, 0.35);
  assert.equal(CORE_TARGETS.offline.offline, 1);
});

test('stepPose is frame-rate independent and converges', () => {
  const start = initialPose('idle');
  assert.equal(start.midAngle, 10);
  assert.equal(start.innerAngle, -6);
  assert.ok(EASED_KEYS.includes('sweep'));
  for (const state of ['listening', 'speaking', 'working', 'offline']) {
    const target = coreTarget(state, { envelope: 0.4, levelAge: 20, time: 0.5 });
    const twice = stepPose(stepPose(start, target, 8), target, 8);
    const once = stepPose(start, target, 16);
    for (const key of [...EASED_KEYS, 'voice', 'midAngle', 'innerAngle', 'arcAngle']) close(twice[key], once[key], 1e-9, `${state} ${key}`);
    let pose = start;
    for (let frame = 0; frame < 400; frame++) pose = stepPose(pose, target, 16);
    assert.ok(isSettled(pose, target), `${state} settles`);
    for (const key of EASED_KEYS) close(pose[key], target[key], 1e-4 * Math.max(1, Math.abs(target[key])), `${state} ${key} converged`);
  }
  // Nothing jumps: one frame moves only part of the way.
  const step = stepPose(start, coreTarget('working'), 16);
  close(step.midSpeed, 60 + (6 - 60) * Math.exp(-16 / 400), 1e-12, 'one 16 ms frame of speed easing');
  close(step.sweep, 1 - Math.exp(-16 / 250), 1e-12, 'one 16 ms frame of sweep easing');
});

test('level envelope: attack is faster than release', () => {
  const rise = levelEnvelope(0, 1, 50);
  const fall = 1 - levelEnvelope(1, 0, 50);
  close(rise, 1 - Math.exp(-1), 1e-12, 'attack τ 50 ms');
  close(fall, 1 - Math.exp(-0.25), 1e-12, 'release τ 200 ms');
  assert.ok(rise > fall);
  close(levelEnvelope(0.3, 0.8, 0), 0.3, 1e-15, 'no time, no change');
});

test('voice drive: envelope with a fresh level, synthetic pulse with a stale one', () => {
  const fresh = coreTarget('speaking', { envelope: 0.5, levelAge: 100, time: 0.3 });
  assert.equal(fresh.pulse, 0);
  close(fresh.levelDrive, 0.5, 1e-12, 'level drive is the envelope');
  for (const levelAge of [301, Infinity]) assert.equal(coreTarget('speaking', { envelope: 0.5, levelAge, time: 0.3 }).pulse, 1);
  close(syntheticPulse(0.3), 1, 1e-12, 'pulse peak');
  close(syntheticPulse(0.9), 0, 1e-12, 'pulse trough');
  close(syntheticPulse(0), 0.5, 1e-12, 'pulse mid');
  let pose = initialPose('idle');
  assert.equal(pose.voice, 0);
  const stale = coreTarget('speaking', { envelope: 0.5, levelAge: Infinity, time: 0.3 });
  for (let frame = 0; frame < 200; frame++) pose = stepPose(pose, stale, 16);
  close(pose.voice, 1, 1e-5, 'stale speaking follows the pulse');
  for (let frame = 0; frame < 200; frame++) pose = stepPose(pose, fresh, 16);
  close(pose.voice, 0.5, 1e-5, 'fresh speaking follows the envelope');
  // Halfway through the pulse/level blend, voice = speak × mix of both drives.
  const blend = { ...pose, pulse: 0.25, speak: 0.8 };
  close(stepPose(blend, { ...fresh, pulse: 0.25, speak: 0.8 }, 0).voice, 0.8 * (0.75 * 0.5 + 0.25 * syntheticPulse(0.3)), 1e-12, 'blend');
  for (let frame = 0; frame < 200; frame++) pose = stepPose(pose, coreTarget('idle', { envelope: 0.5, levelAge: 10 }), 16);
  close(pose.voice, 0, 1e-5, 'no voice outside speaking');
});

test('frame interval: 15 fps idle, 60 fps live or settling, offline stops once settled', () => {
  assert.equal(frameInterval('idle', false), 1000 / 15);
  assert.equal(frameInterval('idle', true), 1000 / 60);
  for (const state of ['listening', 'speaking', 'working', 'thinking', 'recording']) {
    assert.equal(frameInterval(state, false), 1000 / 60);
    assert.equal(frameInterval(state, true), 1000 / 60);
  }
  assert.equal(frameInterval('offline', true), 1000 / 60);
  assert.equal(frameInterval('offline', false), null);
  let pose = initialPose('working'), frames = 0;
  const target = coreTarget('offline');
  while (!isSettled(pose, target) && frames < 1000) { pose = stepPose(pose, target, 1000 / 60); frames++; }
  assert.ok(frames < 300, `offline settles in ${frames} frames`);
  assert.equal(frameInterval('offline', !isSettled(pose, target)), null);
  // A level arriving while offline (not speaking) does not wake the loop for long.
  assert.ok(isSettled(pose, coreTarget('offline', { envelope: 0.5, levelAge: 10 })));
  assert.ok(!isSettled(initialPose('speaking'), coreTarget('speaking', { envelope: 0.5, levelAge: 10 })));
});

test('camera framing matches the README default view', () => {
  close(CORE_FOV, 20.4079, 1e-4, 'vertical FOV');
  const half = Math.tan(CORE_FOV * DEG / 2);
  const full = cameraFor(160, 'full'), small = cameraFor(64, 'small');
  close(full.distance, (1.2 * 256 / 228) / half, 1e-12, 'full distance');
  close(small.distance, 1 / (0.88 * half), 1e-12, 'small distance');
  close(full.distance, 7.4856, 1e-3, 'full distance value');
  close(small.distance, 6.3131, 1e-3, 'small distance value');
  for (const view of [full, small]) {
    const [x, y, z] = view.position;
    close(Math.hypot(x, y, z), view.distance, 1e-9, 'distance');
    close(Math.atan2(x, z) / DEG, 24, 1e-9, 'azimuth');
    close(Math.asin(y / view.distance) / DEG, 12, 1e-9, 'elevation');
    assert.deepEqual(view.target, [0, 0, 0]);
    assert.deepEqual(view.up, [0, 1, 0]);
  }
});

// coreScene ------------------------------------------------------------------------------

test('core scene: nodes, LOD visibility, wide lines and opacities', async () => {
  const reference = await parseCore();
  const core = createCore(await parseCore(), { lod: 'small', cssSize: 64 });
  const names = new Set();
  core.scene.traverse(node => names.add(node.name));
  for (const name of CORE_NODES) assert.ok(names.has(name), name);
  assert.equal(core.nodes.beads.parent.name, 'ring_mid');
  for (const name of [...PRIMARY_LINES, ...SECONDARY_LINES]) {
    const line = core.nodes[name];
    assert.ok(line.isLineSegments2 && line.material.isLineMaterial, `${name} is a LineSegments2`);
    assert.equal(line.material.linewidth, 1);
    assert.deepEqual(line.material.resolution.toArray(), [64, 64]);
    // Every segment of the indexed GLB line survives the non-indexed conversion.
    assert.equal(line.geometry.attributes.instanceStart.count, reference.getObjectByName(name).geometry.index.count / 2, `${name} segments`);
  }
  const visible = () => CORE_NODES.filter(name => shown(core.nodes[name])).sort();
  const opacity = name => core.nodes[name].material.opacity;
  assert.deepEqual(visible(), [...SMALL_LOD_NODES].sort());
  for (const name of ['ring_outer', 'ticks_major', 'ring_mid']) assert.equal(opacity(name), 1);
  close(opacity('core_edges'), 0.35, 1e-12, 'small core edges');
  for (const name of SECONDARY_LINES) {
    // The small-LOD arc band follows the working sweep (its own test below).
    close(opacity(name), name === 'arc_band' ? 0 : 0.35, 1e-12, name);
    assert.equal(core.nodes[name].material.transparent, true);
    assert.equal(core.nodes[name].material.depthWrite, false);
  }
  core.setLod('full');
  core.setCssSize(160);
  assert.deepEqual(visible(), [...CORE_NODES].sort());
  assert.equal(opacity('core_edges'), 1);
  assert.deepEqual(core.nodes.ring_outer.material.resolution.toArray(), [160, 160]);
  assert.equal(core.nodes.core_faces.material.type, 'MeshLambertMaterial');
  assert.equal(core.nodes.core_faces.material.flatShading, true);
  assert.equal(core.nodes.beads.material.type, 'MeshBasicMaterial');
  assert.equal(core.nodes.ring_mid.material.color.getHexString(), CORE_COLORS.accent.slice(1).toLowerCase());
  core.dispose();
});

test('core scene: listening tilt, offline steel and core scale', async () => {
  const root = await parseCore();
  const rest = root.getObjectByName('ring_mid').quaternion.clone();
  close(2 * Math.acos(rest.w) / DEG, 62, 1e-4, 'stored ring_mid tilt');
  const core = createCore(root, { lod: 'full', cssSize: 160 });
  const normalTilt = name => new Vector3(0, 0, 1).applyQuaternion(core.nodes[name].quaternion).angleTo(new Vector3(0, 0, 1)) / DEG;
  core.apply(initialPose('listening'));
  close(normalTilt('ring_mid'), 0.35 * 62, 1e-3, 'listening ring_mid tilt');
  close(normalTilt('ring_inner'), 0.35 * 48, 1e-3, 'listening ring_inner tilt');
  core.apply({ ...initialPose('idle'), midAngle: 90 });
  close(normalTilt('ring_mid'), 62, 1e-3, 'spin stays in the ring plane');
  core.apply({ ...initialPose('speaking'), voice: 1 });
  close(core.nodes.core_faces.scale.x, 1 + CORE_SCALE_GAIN.full, 1e-12, 'full core faces scale');
  close(core.nodes.core_edges.scale.x, 1 + CORE_SCALE_GAIN.full, 1e-12, 'full core edges scale');
  assert.equal(core.nodes.core_edges.material.opacity, 1, 'full core edges stay at 1');
  core.apply(initialPose('offline'));
  const steel = new Color(CORE_COLORS.steel).getHexString();
  for (const name of [...PRIMARY_LINES, ...SECONDARY_LINES]) {
    assert.equal(core.nodes[name].material.color.getHexString(), steel, name);
    close(core.nodes[name].material.opacity, 0.5, 1e-12, `${name} offline opacity`);
    assert.equal(core.nodes[name].material.transparent, true);
  }
  assert.equal(core.nodes.beads.material.color.getHexString(), steel);
  close(core.nodes.beads.material.opacity, 0.5, 1e-12, 'beads offline opacity');
  assert.equal(core.nodes.core_faces.material.color.getHexString(), CORE_COLORS.faceOffline.slice(1).toLowerCase());
  core.apply(initialPose('idle'));
  assert.equal(core.nodes.ring_outer.material.transparent, false);
  assert.doesNotThrow(() => core.dispose());
});

test('core scene: small-LOD voice glow and swell, working sweep', async () => {
  assert.deepEqual({ ...CORE_SCALE_GAIN }, { small: 0.30, full: 0.12 });
  assert.deepEqual({ ...EDGE_GLOW }, { base: 0.35, gain: 0.65 });
  const core = createCore(await parseCore(), { lod: 'small', cssSize: 64 });
  const edges = core.nodes.core_edges, arc = core.nodes.arc_band;
  for (const voice of [0, 0.4, 1]) {
    core.apply({ ...initialPose('speaking'), voice });
    close(core.nodes.core_faces.scale.x, 1 + 0.30 * voice, 1e-12, `small scale at voice ${voice}`);
    close(edges.scale.x, 1 + 0.30 * voice, 1e-12, `small edge scale at voice ${voice}`);
    close(edges.material.opacity, 0.35 + 0.65 * voice, 1e-12, `small edge glow at voice ${voice}`);
    assert.equal(edges.material.transparent, true);
  }
  core.apply({ ...initialPose('speaking'), voice: 1, offline: 1 });
  close(edges.material.opacity, 0.5, 1e-12, 'offline mix on top of the glow');
  // Sweep: the arc band shows at small LOD only while working or still fading out.
  for (const state of ['idle', 'listening', 'speaking', 'offline']) {
    core.apply(initialPose(state));
    assert.equal(shown(arc), false, `${state} hides the arc band`);
  }
  core.apply(initialPose('working'));
  assert.equal(shown(arc), true, 'working shows the arc band');
  close(arc.material.opacity, 1, 1e-12, 'working arc opacity');
  let pose = initialPose('working'), frames = 0;
  while (pose.sweep > 0.001 && frames < 1000) {
    pose = stepPose(pose, coreTarget('idle'), 16);
    core.apply(pose);
    if (pose.sweep > 0.001) {
      assert.equal(shown(arc), true, 'visible while fading');
      close(arc.material.opacity, pose.sweep, 1e-12, 'arc opacity follows sweep');
    }
    frames++;
  }
  assert.equal(shown(arc), false, 'hidden once faded');
  core.apply({ ...initialPose('working'), offline: 1 });
  close(arc.material.opacity, 0.5, 1e-12, 'offline mix on top of the sweep');
  core.apply({ ...initialPose('working'), arcAngle: 37 });
  close(arc.quaternion.angleTo(core.nodes.ring_outer.quaternion) / DEG, 37, 1e-6, 'arc spins about its local Z');
  core.setLod('full');
  core.apply(initialPose('idle'));
  assert.equal(shown(arc), true, 'full LOD always shows the arc band');
  close(arc.material.opacity, 0.35, 1e-12, 'full LOD arc opacity unchanged');
  core.apply({ ...initialPose('speaking'), voice: 1 });
  close(core.nodes.core_faces.scale.x, 1.12, 1e-12, 'full scale gain');
  core.dispose();
});

// Asset ----------------------------------------------------------------------------------

test('published GLB matches its ownership entry and the reviewed build', () => {
  const sha = crypto.createHash('sha256').update(fs.readFileSync(GLB)).digest('hex');
  const registry = JSON.parse(fs.readFileSync(path.join(ROOT, 'docs', 'ASSET_OWNERSHIP.json'), 'utf8'));
  const entry = registry.entries.find(item => item.path === 'src/assets/models/jarvis-core.glb');
  assert.ok(entry, 'ownership entry');
  assert.equal(entry.sha256, sha);
  assert.match(entry.origin, /^owner-generated: art\/blender\/jarvis-core\.py \(sha256 [0-9a-f]{64}\), Blender 5\.2\.\d+$/);
  const manifest = path.join(ROOT, '.runtime', 'blender', 'review', 'jarvis-core.manifest.json');
  if (fs.existsSync(manifest)) assert.equal(JSON.parse(fs.readFileSync(manifest, 'utf8')).outputs['jarvis-core.glb'].sha256, sha);
});
