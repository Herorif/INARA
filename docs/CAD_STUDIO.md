# Offline CAD Studio and owned creative jobs

Implemented 14 October 2026. Open **Studio → 3D studio** after `scripts/start.ps1`. Build a solid box, L bracket or open enclosure with editable millimetre dimensions, inspect it with orbit/zoom or wireframe, and download STL, GLB or its editable JSON recipe. Each successful build creates a separate revision. The previous voice CAD view remains available when a legacy design is present.

The interface follows the JARVIS command deck, with a blueprint sidebar, model viewport, validation summary, export actions and recent revisions. Narrow layouts stack these sections and scroll within the modal. [Desktop preview](qa/cad-desktop.png), [narrow controls](qa/cad-mobile.png), [narrow model view](qa/cad-mobile-preview.png).

## Geometry and exports

The initial engine builds bounded grid-based solids using the Python standard library in a separate worker. Adjacent occupied cells share coordinates; internal faces are removed. The worker checks finite coordinates, non-degenerate triangles, paired boundary edges, consistent winding and positive enclosed volume before exporting. Boxes, brackets and enclosures have independent analytic-volume tests, including inspection of exported binary coordinates.

Dimensions range from 1–1000 mm, with wall thickness from 0.5–100 mm. Bracket legs and enclosure openings must retain at least 0.5 mm beyond their walls/base, preventing features from collapsing when exported to float32 coordinates. This milestone supports those three parametric forms. It does not create arbitrary sculpted meshes, holes, fillets or native CAD boundary representations, and does not establish printing tolerances or physical part suitability.

STL keeps CAD coordinates in millimetres with Z up. GLB uses metres with Y up and embeds geometry, normals and material data in one file, without remote textures. The format conversion follows the [Khronos glTF/GLB specification](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html). GLB supports a later Blender workflow through its [glTF importer](https://github.com/KhronosGroup/glTF-Blender-IO). Actual Blender execution, `.blend` project generation, scene editing and rendering are subsequent work; this milestone verifies GLB loading with Three.js.

Successful artifacts live under the current project's `cad/designs/<derived-UUID>/`. Staging uses a fresh directory in `cad/.work/`. Existing revisions and legacy files are not replaced. The exports and recipes are ordinary project artifacts; they are not claimed to be encrypted. Each export has a SHA-256 digest and a 64 KiB limit, checked by the core and again by the download/preview client. A changed/missing file fails visibly rather than silently serving another artifact.

## Jobs, authorization and persistence

`backend/services/cad.py` owns typed requests, admission, durable records and lifecycle. `cad_transport.py` exposes acknowledged, authenticated workspace RPCs. `backend/workers/cad_worker.py` owns geometry/export execution; the resident does not import `creative.geometry`, initialize a CAD kernel or load Blender.

Builds use the existing `generate_cad` permission and common dispatcher. Existing approval/denial settings apply, with authentication and denial rechecked after approval. A pending duplicate cannot replace the original approval or make it uncancellable. The optional planner proposes recipe data only; it cannot execute code or write files. Unsupported arguments, executable snippets, nonfinite numbers and invalid wall dimensions are rejected.

CAD records use the existing encrypted document store: the record kind hashes the desktop owner and resolved project path, and the record ID is the build request UUID. Recipes, states, errors and artifact metadata are protected with DPAPI. No schema migration or rewrite of older data is required. Completed duplicates return the existing result; conflicting dimensions reject the reused ID. Interrupted claims remain preserved and surface as interrupted; they are never automatically rerun. Check artifacts before starting a new request. The current bound is 128 retained builds per owner/project, with the twelve newest exposed to the UI; archival is future work.

The Socket.IO methods are `cad_submit`, `cad_cancel`, `cad_list`, `cad_artifact`, `cad_plan` and `cad_close`; `cad_job` carries scoped progress/results. Renderer identity, project and configured authorization determine access. The control socket cannot read Studio artifacts. Binary exports travel through the existing authenticated socket, without tokens in download URLs or a new public file server.

One worker runs at a time per core. Gaming/resident mode rejects activation; switching to those modes cancels an active build. Closing Studio, losing the last renderer or quitting the core cancels owned CAD work and pending CAD approvals/planning. Timeout is thirty seconds. The existing atomic Win32 Job Object boundary owns the process and descendants, excludes provider credentials from its inherited environment, passes bootstrap through stdin, hides console creation and checks exit status. Process isolation is a lifetime/resource boundary, not an OS security sandbox; the worker runs the fixed bundled engine, not generated Python.

Only known staging files are removed, with path/link checks and no recursive traversal of user directories. Unexpected entries and completed project artifacts remain preserved. If private history cannot save after a claim, the worker is still released and the request remains uncertain rather than being replayed.

## AI blueprint adapter

The optional **AI blueprint** action uses the existing lazy provider factory and typed recipe schema. It returns proposed dimensions for review, never builds automatically and never needs microphone/audio activation. A missing provider configuration leaves manual modeling and the current preview usable. The adapter has a bounded request and closes its provider. Tests use a fake provider or an explicit placeholder key; no paid requests ran. API configuration remains deferred.

## Verification and resource evidence

The current suite has **98 Python checks and nine frontend checks**, covering the prior core/persistence/resident behavior plus geometry, real workers, durable scopes, tampered exports, denial/recheck, duplicate approval cancellation, interruption, storage failure, timeout and worker cleanup. Production build, Ruff and dependency consistency pass. The initial application bundle remains approximately 241 KB; the approximately 839 KB CAD/Three.js chunk is lazy, with its CSS and the old voice adapter separate. Existing build/deprecation warnings remain.

`scripts/verify-cad.py` launches the actual native host and a hidden offscreen workspace with fresh settings, profile, projects and protected storage. It builds each shape, verifies expected volume and preview, exercises real STL/GLB/recipe downloads into the test directory, imports GLB with Three.js, checks wireframe and 1440/768/390-pixel layouts, restores history/preview on panel reopen without rebuilding, and checks the optional planner's missing-key behavior. Geometry-related remote asset requests are zero. Three worker processes start and exit; `creative.geometry` stays absent from the resident. Screenshots and [recorded evidence](qa/cad-verification.json) come from the rendered application.

The final recovery sample, after three builds and workspace exit, remained at approximately **64.86 MB combined resident working set / 47.32 MB private bytes** across six samples over ten seconds, including the virtual-environment launcher. Before opening the workspace it sampled 62.38/46.00 MB. These are development-machine recovery samples, not another ten-minute idle or real-game benchmark. The earlier [native ten-minute idle evidence](NATIVE_RESIDENT.md) remains separate. No production files, cameras, microphones, printers, phones or real API credentials were used.

Native lifecycle/crash checks still pass with bounded shutdown. An injected workspace crash can leave a pending transport poll that Uvicorn cancels at its shutdown deadline; worker/job cleanup and process exit remain verified. Notification presentation, installed-release gaming/thermal behavior, full Blender round trips and remote CI are not verified here. The user deferred the real-game benchmark. WhatsApp replies remain excluded.

## Next bounded implementation

Add controlled Blender scene jobs: typed objects, transforms and material operations, owned Blender process execution when an installation is available, `.blend`/GLB revisions, cancellation and artifact validation. Keep the offline parametric engine available without Blender or a provider key. Verify actual Blender import/render/export and warmed resident recovery before adding image-generation workers or further vision adapters.
