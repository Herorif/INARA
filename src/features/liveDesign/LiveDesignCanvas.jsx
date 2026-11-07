import React, { useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import * as THREE from 'three';
import { blockParts, cadEuler } from '../cad/blockout.js';
import { CAD_MATERIALS, MODEL_NEUTRAL, themeColor } from '../../shared/design/theme.js';
import { REVEAL_MS, framing, highlightMix, partMotion } from './model.js';

/*
 * The live design's 3D view (react-three-fiber, frameloop "demand"). World units are mm; the
 * CAD scene is Z-up, so the content sits in a group turned -90° about X. Every animation reads
 * performance.now() per frame and invalidates until it settles, so idle frames cost nothing.
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
    ghost: themeColor('--text-3', '#74849a'),
    fill: themeColor('--text-2', '#9fb0bf'),
  };
}

const materialColor = name => CAD_MATERIALS[name] || MODEL_NEUTRAL;

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
 * `timeline` is the panel's { reveal, highlight, ghost } (model.js nextTimeline).
 */
export default function LiveDesignCanvas({ objects, mode = 'blueprint', timeline, ghost, hold = false, reducedMotion = false }) {
  const colors = useMemo(() => palette(), []);
  const fit = useMemo(() => framing(objects), [objects]);
  const revealAt = useMemo(() => Object.fromEntries((timeline?.reveal || []).map(item => [item.index, item.at])), [timeline]);
  if (!fit) return null;
  return <Canvas className="live-design__gl" frameloop="demand" dpr={[1, 1.5]} gl={{ antialias: true }} camera={{ fov: FOV, near: 1, far: 100000, position: [400, 300, 400] }}>
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
        : objects.map((object, i) => <BlueprintPart key={i} object={object} revealAt={revealAt[i]} highlight={timeline?.highlight?.[i]} colors={colors} />)}
      {mode !== 'solid' && ghost?.objects.map((object, i) => <GhostPart key={`ghost-${ghost.n}-${i}`} object={object} until={ghost.until} colors={colors} />)}
    </group>
  </Canvas>;
}
