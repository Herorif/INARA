// three.js scene for the live JARVIS core (no React; no DOM besides the renderer the caller
// owns). Takes the parsed GLB scene of art/blender/jarvis-core.py, swaps its LINES for
// 1 CSS px LineSegments2, sets the approved materials and lights, and applies coreModel poses.
import {
  AmbientLight, Color, DirectionalLight, MeshBasicMaterial, MeshLambertMaterial, PerspectiveCamera,
  Quaternion, Scene, Vector3,
} from 'three';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
import { LineSegments2 } from 'three/examples/jsm/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/examples/jsm/lines/LineSegmentsGeometry.js';
import { CORE_SCALE_GAIN, EDGE_GLOW, SWEEP_VISIBLE, cameraFor } from './coreModel.js';

export const CORE_COLORS = Object.freeze({ accent: '#70E0ED', steel: '#5B6B73', face: '#0A1418', faceOffline: '#0C0F11' });
export const CORE_NODES = Object.freeze(['ring_outer', 'ticks_minor', 'ticks_major', 'arc_band', 'ring_mid', 'beads',
  'ring_inner', 'core_edges', 'core_faces', 'reticle']);
export const PRIMARY_LINES = Object.freeze(['ring_outer', 'ticks_major', 'ring_mid', 'core_edges']);
export const SECONDARY_LINES = Object.freeze(['ticks_minor', 'arc_band', 'ring_inner', 'reticle']);
export const SMALL_LOD_NODES = Object.freeze(['ring_outer', 'ring_mid', 'beads', 'core_faces', 'core_edges']);
const SECONDARY_OPACITY = 0.35, OFFLINE_OPACITY = 0.5;

const Z_AXIS = new Vector3(0, 0, 1);
const IDENTITY = new Quaternion();
const DEG = Math.PI / 180;

/** Replace `node` (a LINES primitive) by a LineSegments2 with the same name, transform and children. */
function toWideLines(node, material) {
  const source = node.geometry.index ? node.geometry.toNonIndexed() : node.geometry;
  const geometry = new LineSegmentsGeometry();
  geometry.setPositions(source.attributes.position.array);
  const line = new LineSegments2(geometry, material);
  line.name = node.name;
  line.position.copy(node.position);
  line.quaternion.copy(node.quaternion);
  line.scale.copy(node.scale);
  line.visible = node.visible;
  for (const child of [...node.children]) line.add(child);
  const parent = node.parent;
  parent.children[parent.children.indexOf(node)] = line;
  line.parent = parent;
  node.parent = null;
  if (source !== node.geometry) source.dispose();
  node.geometry.dispose();
  [node.material].flat().forEach(item => item?.dispose());
  return line;
}

/**
 * createCore(gltfScene, { lod: 'small'|'full', cssSize }) → controller.
 * The controller owns the scene graph it builds (`scene`, `camera`); the caller renders it.
 */
export function createCore(gltfScene, { lod = 'full', cssSize = 64 } = {}) {
  const accent = new Color(CORE_COLORS.accent), steel = new Color(CORE_COLORS.steel);
  const face = new Color(CORE_COLORS.face), faceOffline = new Color(CORE_COLORS.faceOffline);
  const scene = new Scene();
  scene.add(new AmbientLight(0xffffff, 1.1));
  const key = new DirectionalLight(0xffffff, 1.8);
  key.position.set(-0.45, 0.62, 0.65);
  scene.add(key, key.target);
  scene.add(gltfScene);

  const found = {};
  gltfScene.traverse(node => { if (CORE_NODES.includes(node.name)) found[node.name] = node; });
  const missing = CORE_NODES.filter(name => !found[name]);
  if (missing.length) throw Error(`Core model is missing ${missing.join(', ')}`);

  const lines = {};
  for (const name of [...PRIMARY_LINES, ...SECONDARY_LINES]) {
    if (!found[name].isLineSegments) throw Error(`Core node ${name} is not a LINES primitive`);
    const secondary = SECONDARY_LINES.includes(name);
    const material = new LineMaterial({
      color: accent.clone(), linewidth: 1, worldUnits: false,
      transparent: secondary, opacity: secondary ? SECONDARY_OPACITY : 1, depthWrite: !secondary,
    });
    material.resolution.set(cssSize, cssSize);
    lines[name] = toWideLines(found[name], material);
    found[name] = lines[name];
  }
  const faces = found.core_faces, beads = found.beads;
  [faces.material].flat().forEach(item => item?.dispose());
  faces.material = new MeshLambertMaterial({
    color: face.clone(), flatShading: true, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1,
  });
  [beads.material].flat().forEach(item => item?.dispose());
  beads.material = new MeshBasicMaterial({ color: accent.clone() });

  const rest = Object.fromEntries(['ring_mid', 'ring_inner', 'arc_band'].map(name => [name, found[name].quaternion.clone()]));
  const camera = new PerspectiveCamera(50, 1, 0.1, 100);
  const spin = new Quaternion(), tilted = new Quaternion();
  let currentLod = null, size = cssSize, lastPose = null;

  const small = () => currentLod === 'small';
  // Base (non-offline) opacity of each line at the current LOD and pose. At small LOD the
  // crystal edges glow with the voice and the arc band sweeps in while working.
  const baseOpacity = (name, pose) => {
    if (name === 'arc_band') return small() ? (pose ? pose.sweep : 0) : (pose ? pose.arcOpacity : SECONDARY_OPACITY);
    if (name === 'core_edges') return small() ? EDGE_GLOW.base + EDGE_GLOW.gain * (pose ? pose.voice : 0) : 1;
    return SECONDARY_LINES.includes(name) ? SECONDARY_OPACITY : 1;
  };
  const setTransparent = (material, value) => {
    if (material.transparent === value) return;
    material.transparent = value; // depthWrite stays as created: on for primary, off for secondary
    material.needsUpdate = true;
  };
  const paint = pose => {
    const offline = pose ? pose.offline : 0;
    const scale = 1 + CORE_SCALE_GAIN[small() ? 'small' : 'full'] * (pose ? pose.voice : 0);
    faces.scale.setScalar(scale);
    found.core_edges.scale.setScalar(scale);
    if (small()) found.arc_band.visible = !!pose && pose.sweep > SWEEP_VISIBLE;
    for (const [name, line] of Object.entries(lines)) {
      const material = line.material;
      const opacity = baseOpacity(name, pose) + (OFFLINE_OPACITY - baseOpacity(name, pose)) * offline;
      material.color.copy(accent).lerp(steel, offline);
      material.opacity = opacity;
      // Secondary lines and the small-LOD crystal edges are always blended (the glow moves with
      // the voice); other primary lines only while they are see-through.
      setTransparent(material, SECONDARY_LINES.includes(name) || (name === 'core_edges' && small()) || opacity < 1);
    }
    beads.material.color.copy(accent).lerp(steel, offline);
    beads.material.opacity = 1 + (OFFLINE_OPACITY - 1) * offline;
    if (beads.material.transparent !== offline > 0) { beads.material.transparent = offline > 0; beads.material.needsUpdate = true; }
    faces.material.color.copy(face).lerp(faceOffline, offline);
  };

  const controller = {
    scene, camera, nodes: found,
    get lod() { return currentLod; },
    setLod(value) {
      const next = value === 'small' ? 'small' : 'full';
      if (next === currentLod) return;
      currentLod = next;
      for (const name of CORE_NODES) found[name].visible = next === 'full' || SMALL_LOD_NODES.includes(name);
      const view = cameraFor(size, next);
      camera.fov = view.fov; camera.aspect = view.aspect; camera.near = view.near; camera.far = view.far;
      camera.position.set(...view.position);
      camera.up.set(...view.up);
      camera.lookAt(...view.target);
      camera.updateProjectionMatrix();
      paint(lastPose);
    },
    setCssSize(value) {
      size = value;
      for (const line of Object.values(lines)) line.material.resolution.set(value, value);
    },
    apply(pose) {
      lastPose = pose;
      for (const [name, angle] of [['ring_mid', pose.midAngle], ['ring_inner', pose.innerAngle]]) {
        tilted.slerpQuaternions(IDENTITY, rest[name], pose.tilt);
        found[name].quaternion.copy(tilted).multiply(spin.setFromAxisAngle(Z_AXIS, angle * DEG));
      }
      found.arc_band.quaternion.copy(rest.arc_band).multiply(spin.setFromAxisAngle(Z_AXIS, pose.arcAngle * DEG));
      paint(pose);
    },
    dispose() {
      scene.traverse(node => {
        node.geometry?.dispose();
        [node.material].flat().forEach(item => item?.dispose());
      });
      scene.clear();
    },
  };
  controller.setLod(lod);
  return controller;
}
