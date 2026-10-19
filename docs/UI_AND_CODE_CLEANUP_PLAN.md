# INARA code cleanup and JARVIS interface plan

Updated 14 October 2026. The core/native/creative foundation is already implemented; the ordered remaining work is R1-R8 in [the reconciled roadmap](INARA_REVAMP_PLAN.md#current-baseline-and-implementation-sequence-14-october-2026). This extends the [system architecture](INARA_REVAMP_PLAN.md) and translates the [project findings](PROJECT_REVIEW.md) into implementation work. Make the application easier to maintain and give it a responsive JARVIS-style interface while meeting the laptop resource budgets.

The cleanup and interface changes should ship in reviewable increments. Preserve existing user data and working integrations, establish shared contracts, then move features behind those contracts. The interface should reveal actual assistant state and make creative work easy to inspect and revise.

## Code organization

Use four clear boundaries: interface, assistant services, adapters and workers. Interface code presents state and sends requests. Services own tasks, conversations, permissions and persistence. Adapters integrate applications and devices. Workers own expensive computation and their dependency environments.

| Current area | Target responsibility | Concrete changes |
| --- | --- | --- |
| `backend/server.py` | Transport and lifecycle entry point | Move orchestration and tool implementations into services; retain thin validated routes and startup/shutdown hooks. |
| `backend/inara.py` | Voice adapter | Extract audio-device handling, session lifecycle and transcript processing; move conversation and tool dispatch to the independent core. |
| `backend/core/server.py` | Archived migration reference | Compare behavior and contracts, port useful pieces individually, then archive with a clear boundary; do not maintain two supported servers. |
| `backend/tools.py`, `backend/llm/tools.py`, `backend/core/tool_registry.py` | One authoritative tool contract | Deduplicate declarations; generate provider-specific tool schemas and client types from the same definitions. |
| `backend/llm/` and model literals elsewhere | Provider adapters and model profiles | Remove import-time client creation and scattered model IDs; validate credentials and capabilities lazily. |
| Legacy and newer CAD/web agent implementations | One implementation per capability | Keep adapters thin, port validated behavior and remove duplicates only once parity checks pass. |
| `backend/project_manager.py` and reminder storage | Project and persistence services | Add non-destructive migration, unique revision paths, transactional reminder transitions and explicit retention. |
| Telephony and phone agent | Call adapter and restricted call service | Keep codec handling at adapter boundaries; callers never inherit the owner's permissions. |
| `src/App.jsx` | Application shell | Extract navigation, workspace layout, window controls and status; feature components own their local view behavior. |
| `src/services/socketSubscriptions.js` | Typed transport adapter | Replace status-string parsing with structured events; preserve a compatibility bridge during migration. |
| `src/store/` | Feature state with narrow subscriptions | Separate persistent domain state from temporary UI state and frame/audio buffers; avoid whole-app updates for high-frequency signals. |
| `src/hooks/useVideoCapture.js`, `useHandTracking.js` | Shared capture and tracking clients | Load on activation, bundle matched runtime assets and release resources on disable/unmount. |
| Components with repeated window markup | Shared presentation primitives | Reuse panel, toolbar, status badge, progress, empty state, error boundary, modal and confirmation components. |
| Root test/debug scripts and `trace.txt` | Manual diagnostics and generated output | Move purposeful scripts into `scripts/`; exclude generated logs and experiments from release artifacts. |

Within the desktop app, organize by feature rather than one growing components directory:

```text
src/
  app/                     Shell navigation routes and bootstrap
  features/
    assistant/             Chat voice and activation views
    studio/                Workspace layout and project controls
    cad/                   Modeling forms viewer and revisions
    images/                Generation editing and gallery
    vision/                Camera tracking and watch controls
    inbox/                 Notification summaries and owner actions
    devices/               Smart devices and printers
    jobs/                  Progress history and cancellation
    settings/              Privacy performance and integrations
  shared/
    ui/                    Reusable accessible components
    design/                Tokens typography and motion
    transport/             Typed requests and event adapter
    hooks/                 Truly shared hooks
```

Service domain code must not import FastAPI routes, Socket.IO or React assumptions. Providers must not select global projects or decide permissions. Workers must not reach directly into the owner's core database. Use explicit constructor dependencies instead of mutable module globals or monkey-patching private methods. Keep public interfaces small and document side effects.

## Cleanup sequence and quality gates

1. Establish a source-control checkpoint and a safe backup/export of existing projects, memory and settings. Separate secret configuration from shareable configuration. Inventory recoverable data before running code that currently initializes or clears temporary projects.
2. Create a reproducible development environment: locked Python dependency groups, a supported Node baseline, the frontend lockfile, documented start commands and separate optional worker installs.
3. Add formatting and static checks: Ruff for Python, TypeScript plus ESLint/formatting for the frontend. Apply formatting once per migrated area, separately from logic changes where practical, so behavior changes remain reviewable.
4. Capture the existing request/event contracts, then introduce typed request, result, error, event and capability models. Move one capability through the new dispatcher at a time.
5. Fix functional issues while extracting their owning service: permission enforcement, canonical paths, reminder state, recoverable sessions and independent typed conversations. Do not preserve an identified bug merely to achieve superficial parity.
6. Consolidate configuration and tool definitions. Add structured logs carrying request/job IDs, redact credentials and keep debugging output outside product conversations.
7. Retire duplicated code after its supported behavior is covered. Remove unused imports, dead branches and abandoned files only after checking references and installation paths.
8. Add Windows CI for the supported build and deterministic tests, with opt-in integration runs for paid APIs and real devices. Record intentional compatibility exceptions rather than blanket-disabling checks.

Tests should prove useful behavior: authorization cannot be bypassed through a direct UI route, a typed request works with no microphone, a due reminder emits once, cancelled work releases its lease, and a failed generation preserves the previous valid revision. Avoid tests that only mirror method names or accept an exception as success.

Measure module complexity and dependency direction. A growing file with multiple responsibilities should be split by ownership rather than an arbitrary line limit. Add concise architecture and contribution guidance so future implementations do not recreate the global audio-loop coupling.

## JARVIS visual direction

Use a deep graphite background, restrained cyan instrument lines, clear white body text and subtle depth. Build a recognizable voice core from concentric rings and waveform motion. Use angular panel details and small telemetry labels around useful content, with the model or artifact as the focus in Studio.

Proposed tokens:

| Token | Starting value or rule |
| --- | --- |
| Background | `#080D14` |
| Main surface | `#101B28` |
| Raised surface | `#162536` |
| Primary text | `#EAF4FF` |
| Secondary text | `#A6BDCF` |
| Primary accent | `#56DAF5` |
| Success | `#6DE2B5` |
| Attention | `#FFC670` |
| Error | `#FF8585` |
| Spacing | 4 px base scale, with consistent 8/12/16/24/32 px steps |
| Typography | Readable sans-serif body; locally bundled Share Tech Mono for selected HUD labels and telemetry |
| Motion | Short 120–220 ms interaction transitions; low-frequency ambient motion only while visible |

These colors are starting values, not a completed contrast audit. Verify actual text/surface combinations and focus states before release. Reserve glow for active state and selection. Use explicit labels as well as color. Bundle fonts locally to avoid startup network requests.

The visual state machine should represent `idle`, `listening`, `processing`, `waiting_for_owner`, `working`, `speaking`, `offline` and `error`. Listening expands the core and displays a live waveform; working puts progress in the relevant task panel; owner input pauses with a clear action card. Display real progress or an honest indeterminate state. Decorative telemetry must not imply work or measurements that are not happening.

## Responsive layouts

| Surface | Layout behavior |
| --- | --- |
| Resident | Tray status and notifications; no continuously rendered HUD |
| Quick panel | Compact voice core, transcript, composer and current action; expand only when the result needs space |
| Studio at wide widths | Navigation rail, resizable conversation/task pane, primary artifact canvas and optional inspector |
| Smaller laptop window | Collapse secondary panes into tabs or drawers; preserve the primary task and composer |
| Fold8 cover screen | One primary pane with bottom navigation and touch-sized actions |
| Fold8 unfolded | Adaptive list/detail panes, with conversation or job context beside the preview |

Use CSS Grid, flex layout and container queries within the desktop shell. Keep docked panels as the default; optional floating panels can preserve the old experience. Persist layout by viewport class and project. Clamp floating panels to usable bounds after resizing, display changes and DPI changes. Do not derive the complete interface from a set of absolute window coordinates.

The voice core must scale down when an artifact requires room. Keep typing, cancel, approval and export actions visible. Support normal window controls, keyboard navigation, a command palette, drag-and-drop reference files, local file previews and a visible way to return from full-screen views.

For creative work, provide parameter controls, object/feature selection, measurement tools, revision history and compare views. For long tasks, show stage, result location and cancel state. The phone should display a compressed preview and job status rather than attempt to run the laptop's creative stack.

## Rendering and interaction performance

Animate the voice core with a single controlled renderer and bounded work. Start with a 30 FPS decorative animation budget; use a higher rate only for visible interactions that benefit from it. Stop animation when hidden or minimized and respect reduced-motion preferences. Offer a low-motion setting that retains the same status information.

Render static CAD views on demand and cap pixel ratio on dense displays. Dispose of replaced Three.js geometry, materials, textures and listeners. Do not retain hidden viewers. Lazy-load the 3D, camera and image modules; preload only after the owner opens the feature or requests its capability.

Keep audio meters and landmark updates outside React's broad state subscriptions. Use references, narrowly subscribed state or a dedicated worker/canvas path, and send semantic events to React at a bounded rate. Capture one camera stream per chosen source, with subscriber-based start and stop. Reuse image buffers where practical and enforce backpressure on preview delivery.

Keep blur, shadows and transparent compositing bounded. Profile the interface while voice and a creative worker run, and while a game owns GPU capacity. Viewport size alone must not trigger repeated model loads, network sessions or scene reconstruction.

## Interface acceptance criteria

- At 1280×720, 1920×1080 and representative ultrawide sizes, no primary controls overlap or leave the usable viewport. Test Windows display scaling at 100%, 125%, 150% and 200%.
- At narrow widths and Fold8 posture changes, the conversation, draft input and active job survive the layout change.
- All main flows work by keyboard, focus is visible, text can scale to 200%, and screen readers receive meaningful status and action labels. Target at least 4.5:1 contrast for ordinary body text and at least 44×44 logical-pixel primary touch targets.
- The quick panel meets the architecture's activation budget on the actual Legion. Set interaction and frame-time thresholds from recorded hardware baselines; aim for immediate visible acknowledgement within 100 ms for local UI actions.
- Hidden/minimized UI performs no decorative rendering or unnecessary camera work. Closing the workspace preserves reminders/history and cancels current panel-owned creative work. A future explicitly selected background-job mode must preserve work and still release preview resources.
- No artificial dashboard numbers, simulated completion percentages or permanently spinning indicators appear in production.
- Empty, disconnected, denied, loading, cancelled and error states are designed for each feature, including a visible recovery action.
- Browser/worker failures are contained by a feature error boundary so other assistant capabilities remain usable.
- Visual checks include real artifact previews, representative conversations, long filenames and localized text; fixture-only screenshots are insufficient for the final release.

## WhatsApp scope

Notification summaries can be included with owner-enabled access. Exclude reply drafting and sending from the initial implementation. If the owner later asks for those features, each use still requires a specific draft or send instruction. A draft instruction does not authorize sending. Automatic acknowledgements, schedules and notification-triggered replies are excluded.

Apply this rule in capability exposure and backend authorization, not only in a prompt or UI toggle. Add behavioral checks before exposing a future reply tool. The initial inbox should have summary, open original message and create reminder actions, with no send action.

## Implementation checkpoints

Complete the contract and service cleanup before connecting the phone. Establish the design tokens and shared UI primitives early, then rebuild the quick panel and workspace shell. Migrate one feature at a time into that shell and profile each new viewer. Finish each checkpoint with working behavior, meaningful checks, visual review and recorded resource measurements before expanding scope.


## Remaining refactor work, tied to the implementation sequence

Keep the current `backend/`, `src/` and `electron/` roots. The tree below is an incremental ownership target, not a request to move the repository into a new monorepo layout. Change import and packaging paths only as the owning feature migrates.

```text
backend/
  server.py                 Compatible supported bootstrap/facade
  application.py            Composition root and startup/shutdown ownership
  contracts/                Versioned requests/results/events and capability types
  transport/                Socket/HTTP handlers, sessions and event delivery
  services/                 Conversation, policy, projects, jobs, artifacts, memory
  adapters/                 Speech, providers, browser, devices, printer integrations
  workers/                  Fixed owned process entry points
  resident/                 Native Windows lifetime and UI launch
src/
  app/                      Bootstrap, navigation, shell and command palette
  features/                 Assistant, CAD, images, vision, jobs, inbox, settings
  shared/
    ui/                     Accessible fields, dialogs, status and revisions
    design/                 Tokens, typography and bounded motion
    transport/              Generated types, runtime guards and RPC/event helpers
    hooks/                  Reusable request/session lifetime
mobile/android/             Native companion, introduced at R7
```

| Current code | Refactor boundary | Milestone and completion evidence |
| --- | --- | --- |
| `backend/server.py` | Composition, identity/project sessions, then thin feature transports | R2a/R2b; preserved event contracts, dependency injection, scoped emissions, no unexplained supported authorization bypass |
| `backend/inara.py` and `backend/voice/pipeline.py` | One media session/audio manager feeding one conversation/tool service | R6; text remains independent, microphone ownership/interrupt/recovery checks pass |
| `backend/core/` | Classify each module as active, migration reference or unused | R2c; reference/parity manifest before archiving or removing any file. Several core helpers remain active |
| `backend/tools.py`, provider tool declarations and registries | One schema source, provider translators and generated client contracts | R2c/R3; SDK conversion and runtime rejection checks preserve full constraints |
| Legacy CAD and browser implementations | Thin compatibility adapters to owned capability services | R2/R5/follow-on automation; previous behavior mapped before retirement; arbitrary generated-code execution excluded from the supported replacement |
| `backend/printer_agent.py` | Discovery, slicer, printer transport, monitoring and service policy | Follow-on device track; separate slice/upload/start stages and actual adapter capability tests |
| `services/creative_jobs.py` / transports | Preserve shared CAD/image lifetime; add resource reservation and explicit background policy | R4; one heavy slot, bounded queue, no cross-project leaks, no replay of uncertain work |
| `services/resources.py` | Capability registry, hardware snapshot and reservations independent of UI | R4; unknown hardware stays unknown, manual gaming wins, model imports remain outside resident |
| Camera/tracker hooks and `features/vision/` | One capture session, bounded inference and independent overlay rendering | R1; synthetic races/device loss, packaged local model, overlay alignment and cleanup |
| `socketSubscriptions.js` and direct feature RPC calls | Feature-specific event registrars and shared reconnect/request lifetime | R3; versioned payloads, duplicate/reconnect handling and identity/project scope |
| `workspace.css`, legacy panel interiors and repeated CAD/image presentation | Shared tokens/layout primitives plus scoped feature styles | R3; visual parity, accessible controls, responsive/DPI checks and lazy assets |
| Root diagnostic scripts, generated logs and duplicated launch helpers | Classify supported/manual/archive and separate release inputs | R2c/release; reference scan and clean installation smoke check before removal |

Do not use line-count reduction as a standalone success measure. `server.py` becomes a bootstrap only when extracted services own their lifecycle without circular imports or references back to transport globals. Retain a facade only for a mapped compatibility need, not a second implementation.

Every migrated route gets an entry in the route/policy matrix: event/tool name, request/result schema, identity/device/project source, allowed roles, side effects, permission/approval requirement, scoped response channel, timeout/cancel owner and legacy replacement. Test direct-route calls as well as model calls. Until a route is migrated, its mobile exposure is unavailable.

Migrate TypeScript from the contract boundary outward. Generate types from server schemas, use narrowly scoped state selectors and keep mutable media/geometry buffers outside application-wide React state. Adopt formatting/static checks for the area being migrated and update its dependency lock in the same bounded checkpoint. Audit upgrades by compatible groups: frontend renderer/Three.js, Electron/preload and each optional Python worker. Verify against official release notes and the existing renderer/native acceptance checks before changing versions.

Add request/job/device correlation IDs to structured diagnostic logs, with credentials, prompts, message text and image/camera payloads excluded by default. A user-invoked diagnostic bundle explains its scope and uses scrubbed metadata. Availability states are separate: not configured, dependencies missing, detected, integration verified, resource blocked and failed. A merely detected executable or package is not a verified capability.

Optional workers should gain explicit launch profiles at R4: selected interpreter/environment, dependency-lock identity, fixed entry point, timeout, model manifest and resource estimate. The current image worker uses the core interpreter; isolated environments must be implemented before claiming independent worker dependency bundles. Model manifests record weights/runtime versions and licences so artifact provenance and repeatability can improve without reading large weights in the resident.

Cross-platform context is an explicit value: owner/device/project/conversation/request IDs plus capability grants. Local single-owner globals must not silently become a multi-device protocol. Pairing and mobile outbox recovery require this boundary before Android can start privileged work.

Refactor completion is: one owner for the responsibility, a working user flow, meaningful regression evidence, preserved private/project data, measured startup/idle behavior when affected, and a short migration note. Formatting alone, a relocated large file, fixture-only inference or a test that swallows an exception does not complete a feature.

R1 update: camera ownership, tracking scheduling/worker protocol and overlays are separated in `features/vision/`. The old global camera style block and unreferenced `useVideoCapture`/`useHandTracking` hooks are retired. [Vision studio](VISION_STUDIO.md) records synthetic versus hardware acceptance. R2a composition/session extraction is now complete; see the update below.

R2a update: `application.py` and `transport/` now own construction/lifetime, desktop identity/project snapshots, conversation/reminder routes and event delivery. `server.py` remains the mapped facade for legacy adapters. [Core composition](CORE_COMPOSITION.md) lists preserved compatibility seams and remaining direct-route bypasses. R2b route/policy migration is next; the whole server is not yet a bootstrap-only file.

R2b1 update: `services/local_actions.py` and `transport/local_actions.py` replace seven direct bypasses with shared schemas/dispatcher policy. Event ownership and origin cancellation are explicit. [Route matrix](ROUTE_POLICY_MATRIX.md) tests cover all registered names and identify remaining groups; settings/lifecycle migration is next.

R2b2 update: `services/settings.py` and `transport/settings.py` own validated atomic settings, while `transport/lifecycle.py` owns typed resource/native/shutdown policy. The legacy settings panel waits for accepted state. [Evidence and limits](SETTINGS_LIFECYCLE_POLICY.md) map the remaining legacy hooks and R2b3 compatibility work.

## R3 implementation outcome ? 19 October 2026

R3 is implemented as one milestone: generated/versioned CAD/image contracts, checked transport TypeScript, shared request/history lifetime, separate feature event registrars, shared JARVIS panels/fields/progress/approvals, embedded control interiors, searchable commands and a project Activity/artifact view. Existing JavaScript remains supported and the optional legacy CAD viewer is retained. [Acceptance, screenshots and limits](R3_UI_RPC.md). R4 capabilities/resource reservations is next.

## R4 completed

Capability/setup diagnostics, shared fixed model/worker profiles, bounded FIFO creative admission with CPU/RAM/VRAM estimates, explicit per-job background continuation, and queue/process release are implemented. OS probes are on demand and do not import heavy models. Panel-close cancellation remains the default; workspace/core closure and gaming still stop background work. [Implementation, verification and deferred hardware acceptance](R4_RESOURCE_LIFETIME.md). The next whole milestone is R5 Creative Studio v2.
