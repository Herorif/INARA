# R3 UI, contracts and activity workspace

Implemented 19 October 2026. R3 now covers the shared desktop shell, creative transport lifecycle, generated contracts, command search, metadata activity/artifacts and embedded tool interiors. Existing JavaScript remains supported; a mass rename was never the acceptance criterion.

## What changed

- **Commands:** one feature catalog drives labels, flags and search. Ctrl/Cmd+K or Find a tool opens a searchable keyboard palette. Gaming disables heavy workspaces, locked sessions cannot open tools, and selecting a command opens the existing workspace rather than executing an assistant action.
- **Activity:** one project-scoped view collects CAD/image jobs, known errors, pending approvals and available exports. It restores recent saved histories, filters by feature, opens the selected revision with its editable recipe, and verifies artifact bytes before download. History is bounded by the existing service's recent-revision window; project files remain preserved. New live updates survive an older list snapshot. Global state contains metadata, not prompts, base64 previews, geometry or streams.
- **Panels:** nine retained controls use embedded layout instead of floating root coordinates. Headers/close controls, loading/offline/error/recovery states, creative revision history, status/progress, labelled fields and approval dialogs are shared. Tokens and dialog layout are separated from command-deck styles. Shared typography uses rem units; responsive layouts and reduced-motion rules remain scoped. Opening Print workshop no longer starts discovery automatically.
- **Events:** conversation/project, creative, devices and reminders have separate removable socket/store registrars. Duplicate desktop info/screenshot listeners were merged while retaining raw/nested screenshot envelopes. App hot reload releases its bridge. Legacy action emission also refuses disconnected sockets rather than buffering actions for a later replay. High-frequency audio/frame buffers remain outside the new activity store.
- **Conversation continuity:** legacy text buttons now submit through the main composer contract. Typed progress, transcription, errors and idle carry captured conversation/project/request scope; late results cannot alter a newly selected project. Disconnect clears stale approvals and uncommitted activity, and project changes clear the prior project's metadata view.

## Contracts and lifecycle

`transport/rpc.ts` owns acknowledgement deadlines and listeners per panel. Disconnect/dispose settle pending calls once, late acknowledgements do nothing, and requests are never automatically replayed. Unknown outcomes remain distinguishable from known denial/failure. CAD, its optional planner, image generation, previews and Activity downloads use this boundary. Server ownership, permissions, physical-effect review and artifact checks remain authoritative.

Pydantic image and CAD/scene request models generate TypeScript declarations and JSON Schema through `scripts/export-ui-contracts.py`; `--check` rejects drift. Shared runtime guards check ACK/job/export envelope shape. Handwritten response interfaces are explicitly not represented as generated backend response schemas. UI contract version **1** is generated for the renderer and advertised at `/status`; additions retain old fields and all existing wire names.

`npm run check:types` checks the transport modules and positive/negative contract examples in `tests/types`. A compatible TypeScript **5.0.4 development baseline** is pinned in the lockfile. Registry certificate/access failures prevented normal installation, so the locally available compiler was used after its version/integrity metadata was matched with the [official registry entry](https://registry.npmjs.org/typescript/5.0.4). Offline npm lock validation and the project-local semantic gate pass. This is not a claim to use the latest TypeScript release; dependency upgrades remain a separate compatible batch. Compiler code is excluded from the renderer/resident runtime.

## Acceptance

- **669 Python checks pass**, one Blender-dependent skip. The suite covers the unchanged 52 socket routes, 53 dispatcher tools and 37 voice functions, plus captured text-event scope and UI contract metadata.
- **41 Node checks pass**, including search/gaming policy, activity scope/bounds/privacy/history races, feature subscription cleanup and CAD/image cancellation/uncertain-result handling.
- Scoped TypeScript semantic and negative checks, generated-schema drift, Ruff, whitespace checks and Vite production build pass. Initial JavaScript is about **248 KB**, with creative/vision/palette/activity assets loaded on demand. Existing build/module-type/deprecation notices remain; hosted CI has been updated but not run remotely.
- [Workspace evidence](qa/r3-workspace-verification.json) covers all nine interiors via command search, Ctrl+K/Enter/Escape, narrow/tablet/desktop/ultrawide widths, 200% zoom, actual shared body-text enlargement, reduced motion and bundled tracking against synthetic frames. It verifies lazy startup and visible controls. Logical zoom is not a measurement of every physical monitor/Windows DPI combination.
- [Native CAD evidence](qa/r3-cad-verification.json) covers approval/denial, Escape preserving the parent panel, real offline model/scene builds and exports, selected-revision restoration from Activity, responsive widths, long revision names and all four owned worker exits; warmed resident recovery was 66.95 MB.
- [Native image evidence](qa/r3-image-verification.json) covers explicit recovery, labelled fixture revisions/downloads, cancellation, selected image/recipe restoration from Activity, narrow layout and all three worker exits; warmed resident recovery was 66.45 MB. No diffusion model ran.

The expanded renderer check exposed a synthetic-source mismatch: the mocked stream was absent from the enumerated device list, so the production device-loss guard correctly paused capture. The fixture now supplies matching synthetic device IDs and waits for capture readiness. Production visibility/device-loss guards were preserved. An early overlapping offscreen run also hit UnknownVizError; final GUI acceptance runs were serialized.

Visual evidence: [command palette](qa/r3-commands-desktop.png), [Activity](qa/r3-activity-tablet.png), [narrow Activity](qa/r3-activity-mobile.png), [approval](qa/r3-approval-desktop.png), [preferences](qa/r3-preferences-mobile.png).

## Boundaries and next milestone

R3 completes this software/UI milestone. It does not claim a full React TypeScript conversion, universal hardware/DPI acceptance, arbitrary legacy generated-code/browser isolation or a measured game benchmark. The optional legacy CAD viewer remains a compatibility path. Native/fallback identity, settings, grants and reminders retain their existing behavior.

R4 is next: a capability/setup center, truthful readiness/configuration descriptors, worker launch profiles and CPU/RAM/VRAM reservations/admission/release. Keep models and optional probes lazy, preserve panel-close cancellation until an explicit background-job mode exists, and avoid installing/configuring providers automatically. Actual image/Blender/audio/camera/printer acceptance, Android pairing/SIM handling and the deferred game benchmark remain separate. WhatsApp reply drafting and sending stay excluded.
