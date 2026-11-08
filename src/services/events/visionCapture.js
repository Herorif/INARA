import { createCaptureRequests } from '../../features/vision/captureRequests.js';

/**
 * Show JARVIS by voice (docs/VISION_STUDIO.md#show-jarvis): after the owner allows
 * look_through_camera, the core asks this workspace for one photo. The Vision studio opens,
 * takes one frame and stops the camera; the answer goes back once as `vision_capture_result`.
 * Nothing here holds the photo after it is sent.
 */
export function registerVisionCaptureEvents({ onSocket, socket, store: useStore, unsubs }) {
    const requests = createCaptureRequests({
        store: useStore,
        hidden: () => document.hidden,
        reply: (requestId, result) => {
            try {
                socket.emit('vision_capture_result', { request_id: requestId, ...result }, () => {});
            } catch {
                // The core times the capture out and tells the owner.
            }
        },
    });
    unsubs.push(onSocket('vision_capture_request', data => requests.request(data)));
    unsubs.push(onSocket('disconnect', () => requests.drop()));
}
