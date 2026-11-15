import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import * as THREE from 'three';
import useStore from '../../store';
import socket from '../../services/socket';
import { createCadClient } from '../../transport/cadClient.ts';
import { artifactBytes } from '../cad/client';
import { blockParts, cadEuler } from '../cad/blockout.js';
import { CAD_MATERIALS, MODEL_NEUTRAL, themeColor } from '../../shared/design/theme.js';
import { REVEAL_MS, extent, framing, highlightMix, partMotion } from './model.js';
import { artifactMatches, boxFraming, createGlbCache, createLoadSequencer, flashFor, stableFraming, wantedGlb } from './liveDesignKernelModel.js';

/*
 * The live design's 3D view (react-three-fiber, frameloop "demand"). World units are mm; the
 * CAD scene is Z-up, so the content sits in a group turned -90° about X. Every animation reads
 * performance.now() per frame and invalidates until it settles, so idle frames cost nothing.
 *
 * With the CAD engine (`preview`, docs/LIVE_DESIGN.md "Draft previews") the canvas fetches the
 * draft GLB over the socket (`cad_artifact`), checks its SHA-256 with SubtleCrypto before
 * parsing, and draws the real geometry in the blueprint style; the last good model stays while
 * the next one builds. Without `preview` (box engine) nothing here changes.
 */

const FACE_OPACITY = 0.14;
const EDGE_OPACITY = 0.85;
const FOV = 38;
const FIT_MS = 450;
const ISO = new THREE.Vector3(1, 0.75, 1).normalize();
const easeOut = value => 1 - (1 - value) ** 3;

function palette() {
  return {
    background: themeColor('--bg-canvas', '#05080c'),
    grid: themeColor('--line', '#17212c'),
    accent: themeColor('--accent', '#70e0ed'),
    hot: themeColor('--accent-hot', '#dff9ff'),
    ghost: themeColor('--text-3', '#74849a'),
    fill: themeColor('--text-2', '#9fb0bf'),
  };
}

const materialColor = name => CAD_MATERIALS[name] || MODEL_NEUTRAL;

// --- CAD engine draft GLB ---------------------------------------------------------------------

const KERNEL_FACE_OPACITY = 0.12;
const KERNEL_EDGE_OPACITY = 0.95;
const EDGE_THRESHOLD_DEG = 20;
// Verified draft GLB bytes, shared by every canvas in this window (a remount reuses them).
const glbCache = createGlbCache();
// The worker's GLB is glTF (metres, Y-up: its root node turns CAD Z-up by -90° about X). Back
// to the CAD frame (mm, Z-up) so it sits in the same group as the box parts.
const GLTF_TO_CAD = new THREE.Matrix4().makeScale(1000, 1000, 1000).multiply(new THREE.Matrix4().makeRotationX(Math.PI / 2));

const parseGlb = bytes => new Promise((resolve, reject) => new GLTFLoader().parse(bytes.buffer, '', resolve, reject));

/** The GLB's meshes as CAD-frame geometries with their edge lines, and their box { min, size }. */
function kernelModel(scene, sha) {
  scene.updateMatrixWorld(true);
  const parts = [], box = new THREE.Box3();
  scene.traverse(object => {
    if (!object.isMesh || !object.geometry?.attributes?.position) return;
    const geometry = object.geometry.clone().applyMatrix4(GLTF_TO_CAD.clone().multiply(object.matrixWorld));
    geometry.computeBoundingBox();
    box.union(geometry.boundingBox);
    parts.push({ geometry, edges: new THREE.EdgesGeometry(geometry, EDGE_THRESHOLD_DEG) });
  });
  scene.traverse(object => {
    object.geometry?.dispose();
    for (const material of [object.material].flat()) material?.dispose?.();
  });
  if (!parts.length || box.isEmpty()) throw new Error('The draft preview has no geometry.');
  const min = box.min.toArray(), size = box.getSize(new THREE.Vector3()).toArray();
  return { sha, parts, box: { min, size } };
}

const disposeKernel = model => model?.parts.forEach(part => { part.geometry.dispose(); part.edges.dispose(); });

/**
 * The newest draft GLB as a CAD-frame model, or the last good one while the next is fetched,
 * built or refused. A response is dropped when a newer GLB was asked for meanwhile; a GLB
 * whose size or digest doesn't match the snapshot is never parsed.
 */
function useKernelModel(preview, reducedMotion) {
  const connected = useStore(state => state.backendConnected);
  const [state, setState] = useState({ model: null, flash: null });
  const client = useRef(null), sequencer = useRef(null), shown = useRef(null), motion = useRef(reducedMotion);
  motion.current = reducedMotion;
  useEffect(() => {
    client.current = createCadClient(socket);
    sequencer.current = createLoadSequencer();
    return () => { sequencer.current.cancel(); client.current.dispose(); client.current = null; };
  }, []);
  const wanted = wantedGlb(preview);
  const requestId = wanted?.request_id, sha = wanted?.sha256, bytes = wanted?.bytes;
  useEffect(() => {
    if (!requestId || !connected || shown.current === sha) return;
    const want = { request_id: requestId, sha256: sha, bytes };
    const ticket = sequencer.current.next(sha);
    (async () => {
      let data = glbCache.get(sha);
      if (!data) {
        const { artifact } = await client.current.call('cad_artifact', { request_id: requestId, format: 'glb' }, 20000);
        if (!artifactMatches(artifact, want)) throw new Error('The draft preview did not match the design.');
        data = await artifactBytes(artifact); // length and SHA-256 (SubtleCrypto) of the decoded bytes
        glbCache.set(sha, data);
      }
      if (!sequencer.current?.accept(ticket)) return;
      const gltf = await parseGlb(data);
      if (!sequencer.current?.accept(ticket)) return;
      const model = kernelModel(gltf.scene, sha);
      const previous = shown.current;
      shown.current = sha;
      setState({ model, flash: flashFor(previous, sha, { now: performance.now(), reducedMotion: motion.current }) });
    })().catch(() => { /* keep the last good model; the core's state chip tells the story */ });
  }, [requestId, sha, bytes, connected]);
  useEffect(() => () => disposeKernel(state.model), [state.model]);
  return state;
}

/** The draft GLB in the blueprint style: accent-tinted faces, accent edges, a hot flash on change. */
function KernelPart({ model, flash, colors }) {
  const { invalidate } = useThree();
  const accent = useMemo(() => new THREE.Color(colors.accent), [colors.accent]);
  const hot = useMemo(() => new THREE.Color(colors.hot), [colors.hot]);
  const face = useMemo(() => new THREE.MeshBasicMaterial({ color: accent, transparent: true, opacity: KERNEL_FACE_OPACITY, depthWrite: false, side: THREE.DoubleSide }), [accent]);
  const edge = useMemo(() => new THREE.LineBasicMaterial({ color: accent, transparent: true, opacity: KERNEL_EDGE_OPACITY }), [accent]);
  useEffect(() => () => { face.dispose(); edge.dispose(); }, [face, edge]);
  useEffect(() => { invalidate(); }, [model, flash, invalidate]);
  useFrame(() => {
    const now = performance.now();
    edge.color.copy(accent).lerp(hot, highlightMix(flash?.until, now, flash?.from));
    if (flash && now < flash.until) invalidate();
  });
  return <group>
    {model.parts.map((part, i) => <group key={`${model.sha}:${i}`}><mesh geometry={part.geometry} material={face} renderOrder={1} /><lineSegments geometry={part.edges} material={edge} renderOrder={2} /></group>)}
  </group>;
}

/** framing() with the parts' size, for the refit rule. */
function partsFraming(objects) {
  const box = extent(objects);
  const fit = framing(objects);
  return fit && box ? { ...fit, size: box.max.map((value, i) => value - box.min[i]) } : fit;
}

/** One part's blockout boxes as geometries (positions in the part's own mm frame). */
function useBoxes(object) {
  const boxes = useMemo(() => blockParts(object).map(part => {
    const geometry = new THREE.BoxGeometry(...part.size);
    geometry.translate(...part.center);
    return { geometry, edges: new THREE.EdgesGeometry(geometry) };
  }), [object]);
  useEffect(() => () => boxes.forEach(box => { box.geometry.dispose(); box.edges.dispose(); }), [boxes]);
  return boxes;
}

function placement(object) {
  return { position: object.position, rotation: new THREE.Euler(...cadEuler(object.rotation)), scale: object.scale };
}

/** Blueprint part: translucent faces and edge lines, revealed and highlighted over time. */
function BlueprintPart({ object, revealAt, highlight, colors }) {
  const group = useRef(null);
  const boxes = useBoxes(object);
  const { invalidate } = useThree();
  const base = useMemo(() => new THREE.Color(materialColor(object.material)), [object.material]);
  const accent = useMemo(() => new THREE.Color(colors.accent), [colors.accent]);
  const face = useMemo(() => new THREE.MeshBasicMaterial({ color: base, transparent: true, opacity: FACE_OPACITY, depthWrite: false, side: THREE.DoubleSide }), [base]);
  const edge = useMemo(() => new THREE.LineBasicMaterial({ color: base, transparent: true, opacity: EDGE_OPACITY }), [base]);
  useEffect(() => () => { face.dispose(); edge.dispose(); }, [face, edge]);
  const { position, rotation, scale } = placement(object);
  useFrame(() => {
    const now = performance.now();
    const motion = partMotion(revealAt, now);
    const mix = highlightMix(highlight?.until, now, highlight?.from);
    if (group.current) {
      group.current.visible = motion.opacity > 0;
      group.current.position.set(position[0], position[1], position[2] + motion.drop);
    }
    face.opacity = FACE_OPACITY * motion.opacity;
    edge.opacity = EDGE_OPACITY * motion.opacity;
    edge.color.copy(base).lerp(accent, mix);
    const revealing = revealAt !== undefined && now < revealAt + REVEAL_MS;
    if (revealing || (highlight && now < highlight.until)) invalidate();
  });
  return <group ref={group} position={position} rotation={rotation} scale={scale}>
    {boxes.map((box, i) => <group key={i}><mesh geometry={box.geometry} material={face} renderOrder={1} /><lineSegments geometry={box.edges} material={edge} renderOrder={2} /></group>)}
  </group>;
}

/** Saved style without loaded artifacts: the recipe solid, as DraftPreview draws it. */
function SolidPart({ object }) {
  const boxes = useBoxes(object);
  const { position, rotation, scale } = placement(object);
  return <group position={position} rotation={rotation} scale={scale}>
    {boxes.map((box, i) => <mesh key={i} geometry={box.geometry}><meshStandardMaterial color={materialColor(object.material)} roughness={0.5} metalness={0.25} /></mesh>)}
  </group>;
}

/** A change's old or removed part: dashed edges only, until the ghost expires. */
function GhostPart({ object, until, colors }) {
  const boxes = useBoxes(object);
  const { invalidate } = useThree();
  const group = useRef(null);
  const material = useMemo(() => new THREE.LineDashedMaterial({ color: colors.ghost, dashSize: 4, gapSize: 3, transparent: true, opacity: 0.9 }), [colors.ghost]);
  useEffect(() => () => material.dispose(), [material]);
  const { position, rotation, scale } = placement(object);
  useFrame(() => {
    const alive = performance.now() < until;
    if (group.current && group.current.visible !== alive) { group.current.visible = alive; invalidate(); }
  });
  return <group ref={group} position={position} rotation={rotation} scale={scale}>
    {boxes.map((box, i) => <lineSegments key={i} geometry={box.edges} material={material} onUpdate={line => line.computeLineDistances()} />)}
  </group>;
}

/** Orbit on drag; frames the recipe isometrically, then eases to new bounds (keeping the orbit direction). */
function Rig({ fit, hold, reducedMotion }) {
  const { camera, gl, invalidate } = useThree();
  const orbit = useRef(null), tween = useRef(null), placed = useRef(false), pending = useRef(null), applied = useRef(null);
  // A layout effect, so the controls exist before the framing below runs on mount.
  useLayoutEffect(() => {
    const controls = new OrbitControls(camera, gl.domElement);
    controls.enableDamping = false;
    controls.addEventListener('change', invalidate);
    orbit.current = controls;
    return () => { controls.removeEventListener('change', invalidate); controls.dispose(); orbit.current = null; };
  }, [camera, gl, invalidate]);
  useLayoutEffect(() => {
    // Refit only when the bounds change; while parts are revealed, wait for the reveal to end.
    if (fit && fit.key !== applied.current) pending.current = fit;
    const controls = orbit.current, next = pending.current;
    if (!controls || !next || (hold && placed.current)) return;
    pending.current = null;
    applied.current = next.key;
    // CAD (x, y, z) is world (x, z, -y).
    const target = new THREE.Vector3(next.center[0], next.center[2], -next.center[1]);
    const distance = (next.radius / Math.sin((FOV * Math.PI / 180) / 2)) * 1.08;
    const direction = placed.current ? camera.position.clone().sub(controls.target).normalize() : ISO.clone();
    const position = target.clone().addScaledVector(direction, distance);
    camera.near = Math.max(distance / 200, 0.1);
    camera.far = distance * 40;
    camera.updateProjectionMatrix();
    controls.minDistance = distance * 0.25;
    controls.maxDistance = distance * 4;
    if (!placed.current || reducedMotion) {
      camera.position.copy(position);
      controls.target.copy(target);
      controls.update();
      placed.current = true;
      tween.current = null;
    } else {
      tween.current = { fromPosition: camera.position.clone(), fromTarget: controls.target.clone(), position, target, start: performance.now() };
    }
    invalidate();
  }, [fit, hold, reducedMotion, camera, invalidate]);
  useFrame(() => {
    const motion = tween.current, controls = orbit.current;
    if (!motion || !controls) return;
    const progress = Math.min(1, (performance.now() - motion.start) / FIT_MS);
    const eased = easeOut(progress);
    camera.position.lerpVectors(motion.fromPosition, motion.position, eased);
    controls.target.lerpVectors(motion.fromTarget, motion.target, eased);
    controls.update();
    if (progress < 1) invalidate(); else tween.current = null;
  });
  return null;
}

/** Floor grid under the recipe, in --line, with a cell size that suits its size. */
function Floor({ fit, color }) {
  const grid = useMemo(() => {
    const span = Math.max(fit.radius * 5, 200);
    let cell = 10;
    while (span / cell > 40) cell *= 2;
    const size = Math.ceil(span / cell) * cell;
    const helper = new THREE.GridHelper(size, size / cell, color, color);
    helper.material.transparent = true;
    helper.material.opacity = 0.9;
    return helper;
  }, [fit.radius, color]);
  useEffect(() => () => { grid.geometry.dispose(); grid.material.dispose(); }, [grid]);
  return <primitive object={grid} position={[fit.center[0], fit.floor - 0.5, -fit.center[1]]} />;
}

/** Wakes the demand loop when the timeline changes (new parts, highlights or ghosts). */
function Kick({ value }) {
  const { invalidate } = useThree();
  useEffect(() => { invalidate(); }, [value, invalidate]);
  return null;
}

/**
 * The canvas. `mode` "blueprint" (draft, building, failed) or "solid" (saved, no artifacts).
 * `timeline` is the panel's { reveal, highlight, ghost } (model.js nextTimeline). `preview`
 * is the design's CAD-engine preview (liveDesignKernelModel.js), absent on the box engine path;
 * until its first GLB loads, the box parts stand in.
 */
export default function LiveDesignCanvas({ objects, mode = 'blueprint', timeline, ghost, hold = false, reducedMotion = false, preview = null }) {
  const colors = useMemo(() => palette(), []);
  const kernel = useKernelModel(mode === 'solid' ? null : preview, reducedMotion);
  const model = mode === 'solid' ? null : kernel.model;
  // The box path refits on every change; the kernel model only when its bounds change > 20 %.
  const fitted = useRef(null);
  const fit = useMemo(() => {
    const next = model ? stableFraming(fitted.current, boxFraming(model.box)) : partsFraming(objects);
    fitted.current = next;
    return next;
  }, [objects, model]);
  const revealAt = useMemo(() => Object.fromEntries((timeline?.reveal || []).map(item => [item.index, item.at])), [timeline]);
  if (!fit) return null;
  return <Canvas className="live-design__gl" data-model={model ? 'kernel' : mode} data-model-sha={model?.sha} frameloop="demand" dpr={[1, 1.5]} gl={{ antialias: true }} camera={{ fov: FOV, near: 1, far: 100000, position: [400, 300, 400] }}>
    <color attach="background" args={[colors.background]} />
    <ambientLight intensity={1.1} />
    <directionalLight position={[400, 700, 500]} intensity={2.2} />
    <directionalLight position={[-400, 100, -200]} intensity={0.7} color={colors.fill} />
    <Rig fit={fit} hold={hold} reducedMotion={reducedMotion} />
    <Kick value={timeline} />
    <Floor fit={fit} color={colors.grid} />
    <group rotation={[-Math.PI / 2, 0, 0]}>
      {mode === 'solid'
        ? objects.map((object, i) => <SolidPart key={i} object={object} />)
        : model ? <KernelPart model={model} flash={kernel.flash} colors={colors} />
        : objects.map((object, i) => <BlueprintPart key={i} object={object} revealAt={revealAt[i]} highlight={timeline?.highlight?.[i]} colors={colors} />)}
      {mode !== 'solid' && ghost?.objects.map((object, i) => <GhostPart key={`ghost-${ghost.n}-${i}`} object={object} until={ghost.until} colors={colors} />)}
    </group>
  </Canvas>;
}
