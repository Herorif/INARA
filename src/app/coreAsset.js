// The only module that imports the core GLB. Vite inlines it as a base64 data URL, so the
// production file:// renderer parses it in memory: no fetch(), no network, no CSP change.
import url from '../assets/models/jarvis-core.glb?inline';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

let bytes = null;

/** Decodes a base64 data URL into an ArrayBuffer. */
export function dataUrlBuffer(value) {
  const comma = value.indexOf(',');
  if (!value.startsWith('data:') || comma < 0 || !value.slice(0, comma).endsWith(';base64')) throw Error('Core model is not an inline base64 asset');
  const text = atob(value.slice(comma + 1));
  const buffer = new Uint8Array(text.length);
  for (let index = 0; index < text.length; index++) buffer[index] = text.charCodeAt(index);
  return buffer.buffer;
}

/** Parses a fresh copy of the core scene (each mount owns and disposes its own). */
export function loadCoreScene() {
  return new Promise((resolve, reject) => {
    try {
      bytes ||= dataUrlBuffer(url);
      new GLTFLoader().parse(bytes.slice(0), '', gltf => resolve(gltf.scene), reject);
    } catch (error) {
      reject(error);
    }
  });
}
