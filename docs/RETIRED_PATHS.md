# R2c obsolete-path retirement

Completed 19 October 2026. This cleanup preserves the supported runtime and existing settings/data. The active inventory remains **52 socket routes, 53 shared tools (40 text-visible) and 37 voice functions**.

## Retirement map

| Retired path | Supported replacement |
| --- | --- |
| `backend/tools.py` static declarations and `inara.py` duplicate declarations/global config | `VoiceBridge.schemas()` from dispatcher contracts; lazy `services/live_config.py` preserves AUDIO/transcription/Kore configuration |
| AudioLoop ad-hoc CAD/browser/filesystem helpers and detached task spawning | Session-owned `VoiceBridge.call()` through the shared dispatcher; root-owned workspace/creative adapters |
| `services/voice_policy.py`, AudioLoop pending confirmations and workspace public/internal confirmation mapping | Shared ToolDispatcher approval deadlines, owner binding and pre/post authorization; strict `ConfirmationTransport` renderer socket route |
| AudioLoop injected unused agents, permissions copy and unused creative/device callbacks | Application-owned adapters and event delivery; current settings read by shared dispatch |
| Facade unused agent/state aliases, settings-permission synchronization and printer activation helpers | Injected application services and transports; printer activation follows the supported compatibility service |
| `stop_legacy`, `stop_resource_media`, and root `settings_changed` injection hooks | Explicit workspace/connection/device/creative cleanup owners; settings transport owns accepted changes |

The separate archived experimental `backend/core/server.py` and `backend/voice/pipeline.py` were not rewritten or promoted. Supported event-bus/reminder modules under `backend/core` remain active.

## Preserved consumer contracts

`server.py` remains the supported facade. Native host/QA consumers retain runtime identity, ASGI/Uvicorn ownership, socket and client registry aliases, resources, reminders, CAD service, connect/disconnect, lifecycle and wire method aliases. Extracted transports do not import the facade. Native identity/token/owner registration, private hydration, face setup/generation guards and reminder receipts remain covered.

## Verification

- 668 Python checks pass, one Blender-dependent skip. The 18-file regression includes core-safe LiveConnectConfig/schema and device/client ownership checks. After strengthening the registered confirmation route test, all 61 route-policy checks pass again.
- 26 frontend checks, Ruff, diff whitespace checks and the production Vite build pass. Existing Vite CJS/Browserslist/chunk-size and Node module-type notices remain; no dependency upgrade was attempted.
- [Native report](qa/r2c-native-verification.json): fresh registration, private hydration, socket denials/lazy imports, failure recovery, crash/reopen, reminders, gaming and final core stop pass. Ten-second idle mean/peak working set 67.12 MB, zero Electron processes, 0.3125% of one CPU core. The busy-port error is deliberately injected. Uvicorn logged cancellation of one remaining task at its graceful-shutdown deadline; the final report confirms `graceful_core_stop: true`. Clean shutdown without that diagnostic is not claimed.
- [Electron fallback report](qa/r2c-fallback-verification.json): close/reopen, reminder receipt, gaming and explicit quit pass; application shutdown completed.
- [CAD report](qa/r2c-cad-verification.json): offline model/scene rendering, STL/GLB/JSON downloads, Three.js import, saved history/preview restore and widths 1440/390/768 pass. All four workers exited, geometry stayed outside the resident, warmed recovery 66.64 MB. Screenshots remain in the report's local QA run directory.

Tests use isolated data and injected adapters or offline workers. No real microphone/camera, voice provider, printer, diffusion model or Blender acceptance is claimed. Configuration and the real-game benchmark remain deferred. WhatsApp replies remain excluded. Hosted CI is updated but has not run remotely.

## Next

R3 starts with shared UI/RPC lifecycle and typed/generated contracts, then reusable JARVIS panels. Follow the bounded next task in [Implementation handoff](IMPLEMENTATION_HANDOFF.md). Worker hard isolation/reservations, creative provider acceptance, consolidated physical audio and Android remain subsequent milestones.

## R6 production voice retirement

`backend/inara.py:AudioLoop` now raises `voice_migrated` before any device/SDK initialization. `backend/voice/pipeline.py:VoicePipeline` aliases that shim; importing the voice namespace no longer imports camera/audio helpers. Former always-on capture, provider receive and playback loops are removed. `services/voice.py` and `services/live_config.py` remain dormant compatibility schema/policy fixtures, and legacy WorkspaceService accepts injected audio fixtures; neither is the production voice entry. Production uses `services/speech.py` plus renderer-owned explicit PTT and local playback. [R6 details](R6_QUICK_ASSISTANT.md).

## Dead-path removal, 26 October 2026

Code that could never work, or that no supported entry point reached, was deleted. Reachability was checked with an import-graph walk from `backend/server.py`, `backend/resident_main.py`, `backend/application.py`, every `backend/workers/*.py` entry and the `LazyService` module names. History for everything below is in git (the commit that removes it and its parent).

| Removed | Why |
| --- | --- |
| Socket routes and dispatcher tools `start_audio`, `resume_audio`, `upload_memory`, `video_frame`, plus the `pause_audio`/`stop_audio` safety routes; WorkspaceService audio/frame state; `StartAudio`, `UploadMemory` and `VideoFrame` contracts; Settings "Memory data" upload control | Every path constructed the retired `AudioLoop`, which raised `voice_migrated`, or required its session. The renderer never sent `video_frame`, `start_audio` or the stop/pause routes; its only `upload_memory` emitter always failed. `start_audio` stays as the permission key used by push-to-talk `speech_capture`, now accepted through the tool specs' permission keys. |
| `backend/inara.py` (retired `AudioLoop` shim) | Its only consumer was `start_audio`. |
| Model tools `describe_camera`, `detect_presence`, `watch_for`, `list_watches` and the `stop_watching` route; `backend/agents/vision_agent.py`, `backend/vision/vision_loop.py`; `vision_watches`/`vision_alert`/`vision_description`/`vision_presence` delivery; `src/components/VisionWindow.jsx`, `src/store/visionSlice.js`, `showVisionWindow` | Nothing fed camera frames (the only feeder was `video_frame`), so the tools could only answer "No camera frame available" and scene watches could never fire. Screen description lives in `agents/desktop_agent.py` / `desktop/screen_capture.py` and is unaffected. Camera understanding on top of the Vision studio is backlog ([deferred work](DEFERRED_WORK.md)). |
| `backend/core/server.py`, `backend/core/tool_registry.py`, `backend/core/config.py` | Archived experimental rewrite; never imported by the supported runtime. `core/__init__.py` no longer imports `Config`. |
| `backend/telephony/*` (Twilio/PJSIP providers, routes, call session) and `backend/agents/phone_agent.py` | Unreachable legacy telephony; the Twilio routes had no request-signature checks. Telephony will be rewritten separately. |
| `backend/voice/*` (`audio_io`, `greetings`, `stt`, `tts`, `wake_word`, `pipeline`) | Legacy always-on voice pipeline and wake word; unreachable. |
| `backend/agents/{auth,cad,kasa,printer,web}_agent.py`, `backend/web_agent.py`, `backend/calls/voice.py`, `src/services/socketEvents.js` | Unreachable duplicates/shims (the root `cad_agent.py`, `kasa_agent.py`, `printer_agent.py` and `calls/local_voice.py` are the used versions); `socketEvents.js` was imported nowhere. |
| Root `python3` (empty), `check_cuda.py`, `debug_mdns.py`, `debug_printer_connection.py`, `grep_trace.py`, `read_trace.py`, `hand_gesture_test.py`, `test_cad_install.py`, `test_face_rec.py`, `test_imports.py` | Unreferenced one-off diagnostics. |

Moved: `backend/capture_face.py`, `backend/verify_cad.py` and `backend/verify_iteration_mock.py` are manual tools in [`scripts/manual/`](../scripts/manual/README.md). Renamed: `backend/calls/test_contracts.py` to `backend/calls/testing_contracts.py` (a production module). Kept although currently unwired: `services/voice.py` and `services/live_config.py` (replaced by a later voice task; `VoiceBridge` is no longer constructed by the runtime), `backend/llm/*` (in use) and `backend/devices/homeassistant.py` (future Home Assistant integration).
