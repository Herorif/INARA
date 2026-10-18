# Shared voice dispatch and connection/face ownership (R2b5)

Implemented 19 October 2026. This completes the two authorized follow-up steps from [Workspace policy](WORKSPACE_POLICY.md): shared voice execution and connection/face-task ownership.

## One active tool authority

`VoiceBridge` generates the live catalog from dispatcher argument models and sends every function call through `ToolDispatcher`. The old `AudioLoop.receive_audio` tool switch no longer executes. The old inventory recorded only 26 declarations in `tools.py`; the live config had additional declarations in `inara.py`. The replacement explicitly maps **37 active voice names** to shared targets, including the retained prototype alias. The original static metadata remains unused by the active catalog pending R2c deletion.

The root now registers 53 tools, 40 provider-visible for text. Strict shared contracts were added for project selection, directory listing/search, routines, desktop/window/clipboard actions, camera/watch actions, device state and configured-printer status. Existing file, reminder, local action, printer pipeline and workspace services remain the authorities. Compatibility aliases retain canonical and target denials. Voice CAD prompts use the same retained legacy workflow as the old direct panel, rather than replacing the typed parametric-build schema. Project search/listing stays inside the captured project and is bounded; it no longer implies arbitrary home-directory traversal.

Voice calls validate arguments, use the same owner-bound approval/expiry/denial path and recheck their trusted session before and after waiting. Stopping voice cancels its pending approval/execution tasks even if sibling/native channels remain. Unsupported functions return a structured unavailable result. Implicit Google Search is omitted; browser work remains an explicitly approved shared action. UUID/binary review values are serialized safely for sockets while execution retains typed validated objects.

Each call captures owner, origin and project. A bound project-manager view keeps voice history and file tools independent of unrelated global project changes. An authorized voice project switch updates the binding for subsequent calls. Delayed bus events capture a trusted session guard and are discarded after that generation stops. Voice results reflect awaited work rather than claiming success when detached work merely starts.

Live SDK declarations are validated locally through the installed Google SDK. The optional audio constructor no longer creates CAD/browser/Kasa/printer agents. Its SDK client and audio engine belong to the session instance; the stop path closes its streams/client/engine. Physical microphone/speaker behavior and driver-blocking calls remain unverified. The unchanged audio transport still needs R6 acceptance and potential worker isolation.

## Owner-only connection state

`ConnectionTransport` owns connect/disconnect, initial hydration and the optional face generation. Token/UUID validation remains in `DesktopSessions`. Foreign principals are rejected at the connection boundary after the desktop owner is pinned. The native control channel may register the first owner before renderer startup.

Control/resident channels receive no project/settings/printer/watch/reminder hydration. Locked owner renderers receive only connection/resource/authentication metadata and scoped face frames. Successful authentication hydrates verified owner renderer rooms. There are no global authentication broadcasts. Last-renderer disconnect, settings changes, gaming/resident restrictions and shutdown invalidate the generation before cleanup; stale worker frames/status cannot unlock a later generation. Reopening a face-enabled workspace requires authentication again.

Concurrent renderer connects share one face task. A failed/completed generation is retained until explicit settings/reconnect lifecycle changes, avoiding silent repeated camera acquisition. Setup validation rejects enabling face verification before persistence when the installed model or reference image is missing. It does not download models automatically. Reference lookup prefers `backend/reference.jpg`, then `<workspace_root>/reference.jpg`; the installed model is `backend/face_landmarker.task`. No model/reference/hardware was configured in this batch.

## Owned face process

The optional `FaceWorker` uses the existing Windows kill-on-close Job Object, a fixed worker entry point and a pipe-only bootstrap. Heavy OpenCV/MediaPipe imports and blocking camera work stay in that child. The worker accepts only a trusted reference/output path, emits bounded local status/frame reports and has a 120-second deadline. Process close stops the owned tree, then removes transient frame/status files. Bounded cleanup accommodates Windows retaining a stopped process's working-directory handle briefly.

The worker adapter uses the Windows camera backend rather than the prior macOS-only backend constant. This is an implementation correction, not a physical-camera acceptance result. Face landmarks remain a convenience gate and are not OS-grade identity verification. A corrupted/missing face setup fails closed with a scoped error. Model inference and matching accuracy are unverified.

## Verification and limits

Tests cover all 37 functions for canonical denial, extra/invalid identity arguments, locked/stopped/wrong-role/gaming behavior; shared approval ownership/expiry and post-approval alias disablement; captured project/history behavior; stale event guards; socket-safe print reviews; and explicit unsupported functions. Audio cleanup is checked with the actual method body and fake resources without importing or acquiring audio devices.

Connection tests cover control/resident/foreign hydration denial, native first-owner registration, locked/unlocked state, concurrent single-worker startup, stale generations, last-renderer and gaming/settings/shutdown cancellation, setup-before-persistence validation and sanitized failure. A fixed real owned-process fixture verifies result consumption and cleanup without a model or camera. Another fixture verifies the deadline/malformed report path. No live provider, website, generated script, physical camera/microphone/printer or phone action was used.

The initial full regression passed 665 Python checks, with one Blender-dependent skip. A subsequent regression verifies socket-safe UUID-bearing print approvals before any adapter loads; the final combined run passes **666 Python checks**, with one Blender-dependent skip and one existing FastAPI/httpx deprecation warning. All 26 frontend checks, scoped Ruff, Python compilation and the Vite production build pass. No new visual styling is claimed.

Legacy generated-code CAD and autonomous browser internals retain their cooperative cancellation/isolation limitations from the prior checkpoint; shared dispatch does not sandbox their effects. Real live voice/provider compatibility, actual printer/slicer output, diffusion/Blender and hardware acceptance remain unconfigured or unverified. The real-game benchmark remains deferred. WhatsApp reply drafting/sending is excluded.

## Next: R2c

Remove unused static declarations and ad-hoc AudioLoop helper methods, the obsolete standalone voice approval gate/fallback, and dead facade/reference paths. Verify every remaining consumer before deletion and keep supported launchers/adapters. Reconcile historical docs with the active matrix, retain the regression gates, then proceed to R3 UI/TypeScript/shared RPC consolidation. Keep R4 worker reservations/isolation, R5 creative acceptance and R6 audio-stack work separate from this completed policy migration.

[Native evidence](qa/r2b5-native-verification.json) verifies fresh owner registration, private startup hydration denial for control channels, actual socket policy checks, lazy imports, reminders, gaming, crash/reopen and graceful stop. A ten-second sample measured 67.41 MB mean working set with zero Electron processes and 0.625% of one CPU core. This is not a game benchmark. [Fallback evidence](qa/r2b5-fallback-verification.json) covers close/reopen/reminder/gaming/quit. [CAD desktop evidence](qa/r2b5-cad-verification.json) covers real offline exports, scene editing, Three.js GLB import, responsive widths and four worker exits; warmed resident recovery was about 67 MB. Hosted CI is configured but has not run remotely.
