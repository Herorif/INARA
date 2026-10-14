# Vision studio v2

Implemented 14 October 2026 (roadmap R1). Open **Studio > Vision studio**, choose a source and click **Start camera**. Preview is local. Enable hand landmarks separately to load the bundled model in a Web Worker. Choose skeleton/points/hidden overlays, mirrored/natural display and a 5 or 10 FPS tracking budget. Switching an active source starts a fresh preview and turns tracking off until explicitly enabled again.

[Desktop, camera off](qa/vision-idle-desktop.png), [labelled synthetic tracking](qa/vision-tracking-desktop.png), [narrow preview](qa/vision-mobile-preview.png), [narrow controls](qa/vision-mobile-controls.png).

## Behavior and boundaries

The camera is off on entry. No microphone, recording, image upload, semantic-vision request, gesture-triggered action or face authentication is started. Source enumeration does not acquire a camera; device labels may remain unavailable until permission is granted. Device preference uses the existing frontend selection state. Camera sessions and landmarks are transient and are not stored in the private database or artifact directories.

The preview requests 640 x 480 ideally, with 1280 x 720 / 30 FPS caps and no audio. Inference frames preserve aspect ratio and fit within 640 x 480. The overlay canvas follows the video's actual dimensions; video and overlay share one mirror transform and contain-fit presentation so letterboxing stays aligned. Two hands and 21 landmarks per detected hand are supported. The side score is **left/right classification confidence**, not owner identity or a calibrated measure of tracking quality. Mirror changes only the display. No hands, missing frames and unavailable metrics are shown honestly.

Stopping, changing source, device-ended, panel closure, page hide, document-hidden, native minimize/hide, system suspend/lock and gaming release the appropriate stream/model. Resume is manual. An OS permission dialog itself cannot be forcibly dismissed by this code; cancelling the request invalidates it and stops a stream if it arrives later. Source-list requests also use an epoch so an old enumeration cannot overwrite newer state. Busy/unavailable/denied sources have recovery text rather than silently opening another lens.

## Code ownership and resource lifetime

- `capture.js` owns acquisition epochs, track release, ended listeners and failure cleanup.
- `session.js` coordinates capture and opt-in tracking without React/global store assumptions.
- `trackingLoop.js` owns bounded sampling, one frame in flight, duplicate video timestamps and stale-result rejection. Results older than 500 ms are discarded; stale overlays clear after roughly 700 ms without a fresh result.
- `trackingClient.js` owns the worker protocol, 15-second initialization / 4-second inference timeout and termination. Only one frame request is pending. Late bitmaps are closed; transferred frames close in the worker even on inference failure.
- `tracking.worker.js` loads `tracker.js` and the version-matched local MediaPipe/WASM/model assets. It returns landmarks/handedness and measured inference duration, not image data. The classic worker format supports the bundled Emscripten loader's `importScripts` path. No renderer-side inference fallback or CDN fetch is used.
- `overlay.js` draws validated landmark geometry independently of capture and application actions. `CameraPanel.jsx` owns presentation and source controls. Camera styles are lazy feature CSS, replacing the old global camera block.
- `electron/capture-lifecycle.cjs` provides bounded lifecycle-reason messages through preload for native and retained fallback hosts. Listeners detach when their window closes. No frame or media handle crosses this bridge. The existing native Windows Job Object still owns the Electron tree; model execution is a Web Worker within that workspace, not a new resident Python model process.

MediaPipe documents synchronous inference and recommends moving it off the UI thread; the implementation follows its [web hand-landmark guide](https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker/web_js). CPU delegate selection does not prove that Chromium never uses graphics resources for frame/canvas handling.

The unused `src/hooks/useHandTracking.js` and `useVideoCapture.js` were removed after checking repository consumers. Neither had a runtime import. Their duplicate GPU/CDN tracking and frame-upload loops are recoverable in source control; the supported preview now has one capture/tracking path. Legacy semantic watches remain a separate adapter and are not fed by this local preview. Face/pose, calibrated controls, phone-camera input and selected-frame questions remain later capabilities.

## Verification and limits

**146 Python and 26 frontend checks pass**; the existing real-Blender check remains skipped. Build, Ruff and Python dependency consistency pass. The initial JS remains approximately 242 KB; Vision studio is a lazy approximately 19 KB JS / 7 KB CSS panel. Its approximately 129 KB worker, bundled WASM and model are requested only after tracking activation. Existing build/deprecation warnings remain.

Frontend checks cover late permission results, duplicate starts, source changes, attachment failure, device-ended cleanup, session disposal/pause, late model readiness, one-frame backpressure, duplicate/stale timestamps, bitmap release, inference failure, worker init/frame timeout, postMessage/source failure, overlay dimensions and native lifecycle listener cleanup.

`scripts/verify-workspace.cjs` retains shell/layout/accessibility/lazy-asset checks and initializes the real bundled model using a synthetic canvas stream. `scripts/verify-vision.py` additionally launches the real native host and hidden renderer with fresh isolated settings/profile/projects/private storage. It verifies:

- No camera acquisition on panel entry and no model/worker request before opt-in; denied access has useful recovery.
- The actual bundled worker/model initializes and infers blank synthetic camera frames with zero hands. No physical camera is opened.
- A separately labelled synthetic-landmark fixture exercises overlay/classification presentation, mirror alignment, hide/show and bounded 5 FPS submissions. Fixture landmarks do not establish hand-detection accuracy.
- 1440/768/390 layouts, source switching, native suspend/minimize message handling, synthetic device loss, panel-close/late-permission cleanup and gaming release. Native events are deliberately emitted in the isolated test; this is not a physical sleep/minimize/hardware-disconnection test.
- Seven workers start and terminate; all synthetic tracks end. No remote asset requests occur. Model libraries remain absent from the resident core. Graceful core stop passes.

The retained Electron fallback lifecycle check also passes. It exposed and now covers a reminder routing race: resident mode prefers the tray/native recipient over a stale closed-renderer connection, while Studio prefers the renderer. Two deterministic destination checks cover that policy.

After workspace closure, six samples over ten seconds show **63.63-63.83 MB aggregate working set / 46.60-46.86 MB private bytes**, including the venv launcher; before opening, 62.51/45.97 MB. This is short resource recovery, not a new ten-minute or real-game benchmark. [Recorded evidence](qa/vision-verification.json).

Physical camera behavior, real-hand accuracy/latency, OEM permission/device behavior, actual sleep/resume and deployed Windows DPI/graphics behavior still need owner-hardware acceptance. Tests use synthetic streams and labelled overlays. No provider, image model, Blender, printer, phone or paid API action ran. Provider/model configuration and real-game benchmarking remain deferred; WhatsApp replies remain excluded.

## Next implementation

R2a: extract application construction/lifetime, session identity, project context and event delivery from `backend/server.py` into explicit dependencies and thin feature transports. Preserve the supported entry point, native lifecycle, reminders, existing CAD/image contracts and the new vision UI. Follow with R2b's route/policy matrix and legacy authorization migration. Do not combine the entire backend rewrite or Android pairing into R2a.
