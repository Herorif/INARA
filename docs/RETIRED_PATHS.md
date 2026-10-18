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
