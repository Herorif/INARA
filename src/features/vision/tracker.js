import { HandLandmarker } from '@mediapipe/tasks-vision';
import loader from '../../../node_modules/@mediapipe/tasks-vision/wasm/vision_wasm_internal.js?url';
import binary from '../../../node_modules/@mediapipe/tasks-vision/wasm/vision_wasm_internal.wasm?url';
export async function createTracker() {
  // Emscripten's file-URL binary fallback fails in packaged Electron. A scoped
  // browser blob uses the standard fetch path while keeping every byte local.
  const response = await fetch(binary);
  if (!response.ok) throw new Error('The local tracking runtime could not be read.');
  const wasmURL = URL.createObjectURL(new Blob([await response.arrayBuffer()], { type: 'application/wasm' }));
  try {
    return await HandLandmarker.createFromOptions({
      wasmLoaderPath: loader,
      wasmBinaryPath: wasmURL
    }, {
      baseOptions: {
        modelAssetPath: new URL('../../../public/hand_landmarker.task', import.meta.url).href,
        delegate: 'CPU'
      },
      runningMode: 'VIDEO',
      numHands: 2
    });
  } finally {
    URL.revokeObjectURL(wasmURL);
  }
}
