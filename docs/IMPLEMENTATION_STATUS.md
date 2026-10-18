# INARA revival implementation status

Updated 19 October 2026. This records the completed core/persistence milestones, JARVIS workspace, native resident, offline CAD, typed scene assembly, Image atelier and Vision studio v2 from [Implementation handoff](IMPLEMENTATION_HANDOFF.md). Read [Persistence](PERSISTENCE.md) for storage, migration and recovery contracts. The broader [architecture](INARA_REVAMP_PLAN.md) and [JARVIS interface plan](UI_AND_CODE_CLEANUP_PLAN.md) remain the roadmap.

## Completed behavior

The supported `backend/server.py` now starts with the lean core environment and serves typed conversation without an `AudioLoop`, microphone permission, camera or voice connection. Google SDK clients initialize on a text request and are closed afterwards. `INARA_TEXT_MODEL` selects the text model; the initial default is `gemini-3.8-flash`.

Requests and results are validated and carry UUID conversation/request IDs. Durable encrypted conversation history is scoped to the desktop client and project, with bounded restored context and serialized turns. Duplicate request IDs return the prior result or error without replaying the provider work; conflicting payloads are rejected. Missing credentials, invalid input, provider failure and timeout have structured, sanitized errors.

Project file reading/writing and app launching use the common dispatcher. Arguments are validated, configured denials are enforced, approvals expire and are bound to the requesting client, and authorization is checked again before execution. File access rejects traversal, absolute/drive/UNC paths and alternate-data-stream syntax, resolving existing symlinks/junctions before containment checks. Voice file operations use the same containment rule.

Temporary projects and the selected project survive startup. Reminder claiming, schedule advancement and occurrence records commit together; leased delivery retries retain their IDs, and authenticated receipt/completion survives restart. Legacy reminder, routine and project chat migration preserves originals and encrypted snapshots. UTC/IANA recurrence and missed-occurrence policy are documented in [Persistence](PERSISTENCE.md).

Optional audio, camera, CAD, browser, Kasa and printer implementations are imported on demand. Printer hydration/monitoring starts on printer or voice activation; semantic camera watches run when requested frames and watches are present. The FastAPI lifespan owns background-task cleanup. Legacy socket names remain available through the supported server.

The native desktop supplies stable client identity and a random launch token over an inherited pipe and trusted preload IPC. Explicitly configured manual-development tokens are supported. Allowed browser origins are restricted. The chat input shows processing/disconnected states, and duplicate typed response events do not append the same reply twice. The development command sets `INARA_DEV_SERVER=1` correctly.

## Development baseline

A local Git repository and pre-change checkpoint were created: `db88277`. Existing settings, keys and project data remain outside source control. Python 3.12.10 and checksum-verified portable Node 24.21.0 were used locally. Core and development dependency versions are recorded in separate lockfiles. The original full `requirements.txt` remains the optional legacy-feature installation path.

Use `scripts/bootstrap.ps1 -Dev` for the reproducible environment and frontend build. If the normal npm registry cannot establish a valid TLS connection, `-Registry https://registry.npmmirror.com` selects the mirror explicitly while preserving npm integrity checks. No global registry setting or disabled TLS validation is required.

`scripts/start.ps1 -BackendOnly` starts the lean backend. `scripts/start.ps1 -Dev` starts the development desktop, and `scripts/start.ps1` opens the built desktop once Electron's executable is installed. AI responses require a valid `GEMINI_API_KEY` in `.env`.

## Verification

- 31 deterministic checks passed across the new conversation tests and the retained desktop runtime smoke tests.
- Covered independent text responses, credentials and invalid requests, provider failure redaction, conversation/project ownership, duplicate IDs, real SDK schema conversion and tool signatures, permission denial, approval owner binding/expiry, path escape rejection, temporary-artifact preservation, startup and cleanup, and the legacy event contracts.
- Ruff checks passed for the new services and milestone tests. Python dependency compatibility checks passed.
- The Vite production build passed, transforming 2,054 modules. The existing large single JavaScript bundle remains a performance issue for the planned UI/lazy-loading milestone.
- Changed desktop and transport JavaScript passed Node syntax checks.

The npm download initially failed certificate validation on the primary registry connection. Installation succeeded through a TLS-verified mirror with the checked-in lockfile's integrity checks. The build required execution outside the sandbox because esbuild's parent-directory resolution was denied inside it.

No paid AI requests, real app launches, camera sessions, printer actions or phone calls were used in verification. Electron's executable was installed separately after the frontend build-only dependency install; the native desktop window has not been visually verified. Optional legacy audio/CAD/device libraries and current provider-model compatibility still need their own integration tests. The Windows CI workflow is configured but has not run on GitHub.

## Remaining boundaries

The typed tool path exposes project files, configured app launching, validated local reminders and offline parametric CAD jobs. Direct snooze/cancel uses the common dispatcher; CAD builds share the existing generation permission. Typed scene assembly and an optional Blender bridge are implemented; actual Blender execution awaits an installation. Image atelier and its local generation adapter are implemented; real diffusion inference remains unconfigured/unverified. Local speech, advanced vision, Android and telephony remain subsequent work. Some legacy direct handlers still require policy migration, and the legacy voice dispatcher remains separate. This is a local desktop implementation, not a remotely exposed automation service.

Completed typed history and request ledgers are encrypted before SQLite/WAL writes. Restored context is limited to twenty completed messages. Windows DPAPI is user-bound; portable private export, device pairing, scoped credentials and retention controls remain planned. CAD worker ownership and manual resource/gaming policy are implemented; GPU/thermal admission and isolation of other legacy workers remain open. Legacy voice histories remain a separate adapter; existing settings/artifacts retain their formats. The legacy face-landmark gate does not become strong OS authentication through this change.

The command deck, responsive workspace, local reminder panel, lazy 3D/camera loading and resident close/reopen are implemented. Electron is now pinned to 44.7.0 and runs only while a workspace is open; the native host replaces its resident overhead. Optional adapter interiors and creative worker isolation remain subsequent work. WhatsApp reply drafting and sending are excluded until specifically requested; no automatic replies were added.

## Next milestone

R2b3 Kasa/printer compatibility is next. R2b1 and R2b2 are implemented; the whole R2b milestone remains incomplete. [Settings/lifecycle policy](SETTINGS_LIFECYCLE_POLICY.md) records the independent owner gate, strict transports, atomic settings and native/fallback evidence. The matrix identifies remaining groups. Configuration and real-game benchmarking remain deferred.

## Second milestone verification (13 October 2026)

- Versioned encrypted SQLite user data, request ledger, project selection and reminder delivery are implemented without API configuration.
- 56 Python checks pass, covering both milestones, Windows DPAPI round trips, protected database/backups, migration validation/rollback, session restart without tool replay, uncertain requests, concurrent services/pollers, transport failure, acknowledgements, stale alert edits, cancellation/snooze, timezone filtering and DST recurrence.
- Two Node state tests pass for simultaneous alert queueing, duplicate deliveries and reconnect snapshots. The production Vite build passes. Ruff and dependency consistency pass.
- Tests use temporary user data, fake providers and fake transport. No production data migration, paid requests, phone/device actions or native desktop visual verification was performed. The build still reports the existing large bundle, old browsers data and Vite CJS warnings; the JARVIS/lazy workspace milestone will address the frontend structure.
- The local desktop recipient rule does not implement Android delivery ownership or pairing. Closing the current desktop shell still stops its backend; resident lifetime is next. WhatsApp replies remain excluded.


## Resident and JARVIS workspace verification (13 October 2026)

The command deck and resident lifecycle foundation are implemented, including tray/hotkey reopen, explicit graceful quit, generic resident reminder notices, gaming suppression/gating, responsive command/Studio/connections views, local reminder creation and deferred camera/landmark loading. Source modules are separated by lifecycle and feature responsibility.

61 Python checks and eight Node checks pass, along with lint, dependency consistency and production build. Hidden renderer tests verify 1440, 768 and 390 CSS-pixel layouts, modal behavior, icon labels and absence of heavy startup assets. Rendered screenshots are in [docs/qa](qa/command-desktop.png). Native close/reopen uses the same backend and verifies reminder receipt, gaming state and graceful quit with fresh isolated data. Notification display is stubbed. Bundled tracking initialization passes with an empty test stream; no real camera or paid provider is used.

Initial JavaScript is approximately 241 KB uncompressed / 76 KB gzip; CAD is a separate approximately 902 KB chunk. The immediate resident snapshot retained roughly 400 MB of Electron working sets; the 150 MB resident target is not met, and a ten-minute idle/game benchmark is outstanding. The implementation is a functional foundation, with resident footprint reduction explicitly remaining open. Details and limits are in [Resident and workspace](RESIDENT_AND_WORKSPACE.md).

## Native resident follow-up (13 October 2026)

The default Windows host now runs Win32 tray/hotkey and the ASGI core in one Python process, with Electron solely for an open workspace. It preserves the old profile/identity, transfers credentials by pipe/IPC, owns the entire workspace tree through an atomic Windows job, delivers scoped reminders directly and treats native gaming selection as authoritative. Startup/registration timeout, busy-port failure and tray retry are implemented. The older Electron host remains an explicit fallback.

69 Python and eight frontend checks pass. Electron 44.7.0 passes hidden responsive UI/tracking initialization and the retained fallback lifecycle integration. The final ten-minute run, including the owned Python launcher, averaged 64.86 MB working set (65.30 MB peak) at 0.3802% of one CPU core, with 47.54 MB peak private bytes and no resident Electron processes. First workspace open/reopen took 2.516/2.188 seconds after core readiness. Busy-port retry, workspace crash cleanup and graceful quit pass. Final combined-process evidence, acceptance limits and the deferred game benchmark are recorded in [Native resident](NATIVE_RESIDENT.md). The earlier approximately 400 MB Electron measurement above is historical.

## Offline CAD Studio verification (14 October 2026)

The shared typed generation tool now builds boxes, L brackets and open enclosures in an owned stdlib worker, without audio, a CAD kernel or an API key. The responsive JARVIS panel offers dimensions, orbit/wireframe, scoped history and real STL/GLB/recipe downloads. An optional provider proposes schema-validated recipe data for review. Existing voice CAD remains available.

98 Python and nine frontend checks pass, with build, lint and dependency consistency. Real native UI verification covers each shape's expected volume, rendered preview, GLB import, all downloads, narrow layouts, history restoration without rebuilding and missing-key planner behavior. Three workers exit; geometry stays outside the resident. After workspace exit, six recovery samples remained around 64.86 MB combined working set / 47.32 MB private bytes. This is a ten-second recovery observation, not a new idle/game benchmark. [CAD evidence and limits](CAD_STUDIO.md) records actual Blender/STEP/complex-shape exclusions and the bounded transport shutdown behavior after injected crashes.


## Scene assembly verification (14 October 2026)

Typed scenes now support up to eight boxes/brackets/enclosures with per-object dimensions, positive scale, XYZ rotation, translation and four materials. The responsive Studio adds object selection, add/duplicate/remove, material-aware GLB preview and immutable STL/GLB/recipe revisions. Scene bounds and summed part volumes are shown accurately; this does not add boolean unions or arbitrary modeling. Existing encrypted scopes, permissions, old recipe deduplication and owned worker cleanup are retained.

The optional bridge detects an installed Blender and runs a fixed background import/export/project/render script as an owned descendant, with bounded CPU threads, timeout and artifacts. No Blender installation exists here, so the real round-trip test is skipped and actual `.blend`/render/export remains unverified. Offline scenes work without it or API configuration.

116 Python and nine frontend checks pass, along with build, Ruff and dependency consistency. Actual hidden renderer verification passes three-solid regression, scene object editing/transforms/materials, GLB download/import, narrow layouts and history restoration without rebuild. Four workers exit, scene/geometry modules remain outside the resident, and six post-workspace samples stay at 64.97-65.04 MB working set / 47.54 MB private bytes. This is a ten-second recovery observation. [Scene Studio](SCENE_STUDIO.md) records contracts, screenshots, evidence and remaining Blender limits. No paid or phone actions ran; the real-game benchmark remains deferred.


## Image atelier verification (14 October 2026)

Image atelier now offers prompts, frame/seed/quality controls, preview, PNG/recipe download and protected revisions. A fixed local SD/SDXL adapter loads only in an owned worker after explicit generation, without downloads or a cloud API. Configuration remains deferred and no real image model ran. The normal UI explains missing setup and disables generation.

CAD/image lifetimes and authenticated RPCs now share services, preserving old CAD contracts and adding one creative execution slot across CAD/Blender/images. 144 Python and nine frontend checks pass, plus build, Ruff and dependency consistency. Actual native renderer verification exercises unconfigured behavior and explicitly labelled test-only fixture revisions/downloads/reopen/cancel at 1440/768/390 widths. Production rejects fixture provenance. Three fixture workers exit and six recovery samples show 65.12-65.18 MB working set / 47.51 MB private bytes; this does not measure diffusion/GPU recovery. The existing real CAD/scene workflow also passes after refactoring. [Image atelier](IMAGE_ATELIER.md) records evidence, model/setup limits and the next vision milestone. Real Blender and image-model acceptance, remote CI and gaming benchmarks remain unverified/deferred.


## Roadmap reconciliation (14 October 2026)

A planning-only review against `5f79902` now defines R1 Vision, R2 core/policy cleanup, R3 typed shared UI/activity, R4 capabilities/resources, R5 creative workflows, R6 voice/quick panel, R7 Android pairing and R8 notification summaries. Source ownership, follow-on tracks and acceptance gates are recorded in [the architecture roadmap](INARA_REVAMP_PLAN.md#current-baseline-and-implementation-sequence-14-october-2026) and [refactor map](UI_AND_CODE_CLEANUP_PLAN.md#remaining-refactor-work-tied-to-the-implementation-sequence). These are planned changes, not completed runtime features. Configuration and real-game benchmarking remain deferred, personal WhatsApp replies remain excluded, and live model/Blender/phone acceptance remains pending.


## Vision studio v2 verification (14 October 2026)

R1 implementation adds explicit camera/tracker state, source selection, mirror/overlay/rate controls and two-hand overlays. Capture/session, inference scheduling, worker protocol and rendering now have separate owners. The classic Web Worker runs the bundled local model with one transferred frame in flight, stale-result rejection and bounded initialization/inference. Stop, device loss, source switch, panel/visibility/native power events and gaming release resources; restart is explicit. Two unused legacy hooks and the global camera CSS block are retired.

146 Python and 26 frontend checks pass, plus production build, lint and dependency consistency. Real renderer/model checks use synthetic camera streams: blank-frame inference is genuine; injected overlay landmarks are visibly labelled fixtures. Seven workers terminate, all tracks end, no remote assets load and the native core stays free of vision-model imports. Six post-workspace samples remain 63.63-63.83 MB working set / 46.60-46.86 MB private bytes. [Vision evidence and acceptance limits](VISION_STUDIO.md) records actual camera/hand and physical sleep/device checks still pending. This is short recovery, not a game benchmark. R2a is the next implementation.

The retained fallback host lifecycle check passes after fixing reminder destination priority: resident mode selects its tray/native recipient ahead of stale renderer connections; Studio still prefers the renderer. Two destination regressions are included in the 146 Python checks.


## Core composition/session extraction verification (14 October 2026, R2a)

The injected application root now owns construction, FastAPI/ASGI lifetime, reminders, creative services and event delivery. Desktop sessions own handshake identity/roles/native binding and project snapshots. Conversation/reminder transports register existing wire contracts independently of the server facade. Startup rollback, repeated lifetime and shutdown failure paths release pollers/subscriptions. The final owner disconnect resolves approvals; another connected owner channel keeps its approvals.

161 Python checks pass (one real-Blender skip), including 15 new boundary checks; all 26 frontend checks and scoped Ruff pass. Actual native failure/reopen/reminder/gaming verification, CAD/scene render/export/restore and labelled image-fixture cancellation/revisions pass. Short native idle measured 65.57 MB mean working set / 48.03 MB peak private bytes including the launcher, with zero Electron processes. Existing bounded Engine.IO shutdown timeout logs remain in the injected-crash scenario. No new real-model/hardware acceptance is claimed. [Evidence, migration inventory and remaining legacy seams](CORE_COMPOSITION.md). R2b is next.


## Route-policy checkpoint verification (14 October 2026, R2b1)

52 socket routes, `/status`, 15 shared tools and 26 legacy voice declarations are inventoried with schema/caller/context/effects/policy/response/lifetime/replacement fields. Seven direct desktop/device actions now share strict schemas and dispatcher policy with typed model tools. Renderer/auth checks, scoped responses and stamped event ownership prevent those actions from broadcasting across owners. Origin disconnect/app close cancels tracked local requests; shared confirmation input is strict and owner-bound.

222 Python checks pass (one real-Blender skip), including 61 new policy checks; all 26 frontend checks and scoped lint pass. Actual native failure/reopen/reminder/gaming/shutdown verification passes, with short idle 65.61 MB mean working set and zero Electron processes. Desktop/device action tests use injected adapters; no real app/device/screenshot/clipboard action is claimed. [Migration, evidence and remaining bypasses](ROUTE_POLICY_MIGRATION.md). R2b2 settings/lifecycle is next; remaining legacy groups are explicitly pending.


## Settings/lifecycle verification (16 October 2026, R2b2)

Owner-only settings/permission reads and mutations, strict native/resource requests and fallback resident-only shutdown are implemented in injected transports. Settings authorization is outside editable tool permissions; locked/wrong-role/foreign calls cannot grant themselves access. Atomic replacement precedes in-memory commit. Native gaming and fallback resident gaming override renderer requests; restricted transitions release creative/local/media work and report cleanup failures without lifting restriction. Native identity registration and owner safety cleanup remain usable while face-locked.

288 Python checks pass (one real-Blender skip), including 66 new policy checks; all 26 frontend checks, build and lint pass. Real native admin socket checks prove persistence/reconnect, schema/role denial and scoped settings; a fresh profile verifies owner registration before renderer hydration, alongside native reopen/reminder/gaming/shutdown and fallback lifecycle checks. Short idle is 66.72 MB mean working set / 49.48 MB peak private bytes with zero Electron processes after close. The initial intermittent scene-worker failure, subsequent passing run and remaining legacy limits are recorded in [evidence and limits](SETTINGS_LIFECYCLE_POLICY.md). R2b3 is next.

## Combined compatibility and workflow policy checkpoint (R2b3)

Kasa/printer setup and a contained, staged print workflow now use injected owner-scoped services. Slice/upload/start have independent shared permissions; uploads cannot implicitly start a printer. Protected attempt records prevent replay after cancellation, uncertainty or restart. Reminder UUID receipts/role gates and canonical CAD planner authorization are implemented. See [implementation and verification limits](DEVICE_PRINT_POLICY.md) and the refreshed [route matrix](ROUTE_POLICY_MATRIX.md).

Remaining memory/media/legacy creative/browser routes and voice/event ownership keep R2b open. No provider/hardware configuration or WhatsApp reply behavior was added.

Final verification: 377 Python checks passed, one Blender-dependent skip; 26 frontend checks, scoped lint, production build and actual native/fallback/CAD desktop integration passed. CAD advisory progress now tolerates the reproduced Windows replacement sharing failure. Earlier native timing failures and hardware acceptance remain documented in the checkpoint evidence.

## Workspace compatibility checkpoint (R2b4)

Ten remaining memory/media/legacy CAD/browser wire routes use strict owned services, shared action policy and scoped callbacks. Legacy session approvals expire and cannot resolve across stopped generations; unstamped bus events remain internal. Typed conversations now carry trusted origin context and cancel on disconnect/shutdown. Project transcript exports preserve existing files. See [workspace contracts, verification and limits](WORKSPACE_POLICY.md).

Legacy voice schema/dispatcher parity, connection/face lifecycle and hard isolation remain explicit follow-up work before R2c/R3. No provider or hardware configuration and no WhatsApp reply functionality was added.

462 Python checks pass with one Blender-dependent skip; all 26 frontend checks, lint/build and actual native/fallback/CAD desktop integration pass. Short native idle remains about 67 MB with zero Electron processes after close.

## Shared voice and connection checkpoint (R2b5)

The two authorized steps are implemented: 37 live voice functions share validated dispatcher execution, and connection/private hydration plus face worker lifetime belong to the application. Owner/session guards survive approvals and delayed bus delivery. Missing face setup is rejected before enabling it; heavy camera/model work stays in a bounded owned process. See [implementation, tests and hardware limits](VOICE_CONNECTION_POLICY.md).

R2c can now retire unused voice declarations, ad-hoc helper/confirmation paths and dead facade lifecycle references. Provider/model setup, real media/face/device behavior and generated-code/browser hard isolation remain deferred/unverified. WhatsApp replies remain excluded.

666 Python checks and 26 frontend checks pass, with one Blender-dependent skip. Lint/build and actual native/fallback/CAD desktop integration pass. Short native idle is about 67 MB with zero Electron processes after workspace close.
