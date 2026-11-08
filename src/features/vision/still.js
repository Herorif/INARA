// One still JPEG from the live preview (Show JARVIS). The canvas is released straight after;
// the JPEG stays in the caller's memory only and is never written anywhere.
import { MAX_IMAGE_BYTES, STILL_MAX_WIDTH, STILL_QUALITY, stillSize } from './showJarvisModel.js';

const toBlob = (canvas, quality) => new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', quality));

/** A JPEG Blob of the video's current frame, at most 1280 px wide and 1.5 MB. */
export async function captureStill(video, { doc = document, maxWidth = STILL_MAX_WIDTH, quality = STILL_QUALITY } = {}) {
  const size = video && video.readyState >= 2 ? stillSize(video.videoWidth, video.videoHeight, maxWidth) : null;
  if (!size) throw new Error('No camera frame is available.');
  const canvas = doc.createElement('canvas');
  canvas.width = size.width;
  canvas.height = size.height;
  try {
    canvas.getContext('2d').drawImage(video, 0, 0, size.width, size.height);
    let blob = await toBlob(canvas, quality);
    if (blob && blob.size > MAX_IMAGE_BYTES) blob = await toBlob(canvas, 0.6);
    if (!blob || blob.size > MAX_IMAGE_BYTES) throw new Error('The photo could not be made small enough.');
    return blob;
  } finally {
    canvas.width = 0;
    canvas.height = 0;
  }
}

/** Base64 text of a Blob, for the one request that sends it. */
export async function blobToBase64(blob) {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = '';
  for (let index = 0; index < bytes.length; index += 0x8000) binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
  return btoa(binary);
}
