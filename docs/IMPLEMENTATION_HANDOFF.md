# INARA implementation handoff and model choice

Updated 19 October 2026. Implement against the [architecture](INARA_REVAMP_PLAN.md), [project review](PROJECT_REVIEW.md) and [code cleanup and JARVIS interface plan](UI_AND_CODE_CLEANUP_PLAN.md).

The core/persistence milestones, polished JARVIS workspace, native resident, offline CAD worker, typed scene assembly, optional Blender bridge, Image atelier/job adapter, Vision studio v2, R2a core composition/session extraction and R2b1-R2b5 policy groups and R2c retirement are implemented. Real image generation remains unverified and unconfigured. Actual Blender execution remains unverified because it is not installed. Read [Implementation status](IMPLEMENTATION_STATUS.md), [CAD Studio](CAD_STUDIO.md), [Scene Studio](SCENE_STUDIO.md), [Image atelier](IMAGE_ATELIER.md), [Vision studio](VISION_STUDIO.md), [Native resident evidence](NATIVE_RESIDENT.md), [Persistence](PERSISTENCE.md), [Core composition](CORE_COMPOSITION.md), [Route policy migration](ROUTE_POLICY_MIGRATION.md) and [Settings/lifecycle policy](SETTINGS_LIFECYCLE_POLICY.md) and [Device/print workflow policy](DEVICE_PRINT_POLICY.md) and [Workspace policy](WORKSPACE_POLICY.md) and [Shared voice/connection policy](VOICE_CONNECTION_POLICY.md) before continuing. The user explicitly deferred the real-game benchmark; API configuration remains deferred.

Use GPT-6.1 Sol as the primary implementation model, with Medium reasoning and Standard speed. Use High reasoning for difficult migrations or debugging. Reserve GPT-6 Astra for unusually demanding architecture, security and final integration reviews. Use GPT-6 Luna for small, clearly specified edits once contracts and examples are established.

Official OpenAI documentation recommends GPT-6.1 Sol for complex coding and describes its capability as near Astra at a lower cost. That supports this choice; it is not a guarantee of equal results on every INARA task. Confirm quality through behavior, artifact validation and visual review. Availability depends on account, client and rollout. [Model guidance](https://learn.chatgpt.com/docs/models), [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol).

## Cost comparison

Standard API text-token prices in USD per million tokens, for requests with at most 272,000 input tokens:

| Model | Uncached input | Output | Proposed role |
| --- | --- | --- | --- |
| GPT-6.1 Sol | $2.00 | $10.00 | Main implementation |
| GPT-6 Luna | $0.10 | $0.50 | Small bounded tasks |
| GPT-6 Astra | $10.00 | $50.00 | Demanding review and problem solving |

Sol's listed input and output rates are 80% lower than Astra's. Total task savings depend on tokens, retries and tool use. Long-context, cached-input and speed-tier prices differ. These API prices are separate from subscription usage. [Official API pricing](https://developers.openai.com/api/docs/pricing).

For credit-based ChatGPT Work/Codex usage, published Standard rates per million input/output tokens are 50/250 credits for Sol, 2.5/12.5 for Luna and 250/1,250 for Astra. Included-plan allowances are not a fixed conversion to API task counts. Prefer Standard speed for this cost-saving workflow; Fast and Ultrafast consume more usage. [Work and Codex pricing](https://learn.chatgpt.com/docs/pricing).

If GPT-6.1 Sol is unavailable, use the supported Sol option exposed in the account and validate the first bounded task. Do not use Luna as the sole owner of the entire cross-platform rewrite merely because its token rate is lowest.

## Preserve these requirements

- Keep the existing SIM number and personal WhatsApp account.
- WhatsApp notification summaries are allowed with enabled access; reply drafting and sending are deferred until specifically requested. No automatic replies or acknowledgements.
- Provide a small resident laptop assistant, an on-demand Studio and a native Fold8 companion.
- Heavy models, creative workers, tracking and camera acquisition are loaded only when needed. Gaming mode respects foreground resource use.
- Make JARVIS styling the primary visual direction while keeping controls readable, responsive and accessible.
- Preserve project data and existing useful integrations. Use one supported core, one tool contract and one authorization path.
- Ordinary text assistance works independently of live audio, microphone permission and an open window.
- Introduce changes in small, verifiable steps; update these plans if an implementation discovery changes a material assumption.

## Completed first milestone

The reproducible core environment, independent typed-conversation service, lazy provider, scoped request/result contracts and representative shared tool authorization are implemented. Project path containment and non-destructive startup are in place. The retained desktop event contract and new behavior passed 31 deterministic checks, and the production frontend build passed. See the status record for boundaries and unverified integrations.

## Completed second milestone

Versioned Windows-protected SQLite persistence, scoped sessions, request deduplication across restart, validated non-destructive migration, transactional reminder claiming, receipt/completion, UTC/IANA recurrence and UI reconnect recovery are implemented. Existing artifacts and source records remain preserved. See the status record and persistence contract for limitations.

## Resident/workspace foundation

Tray/hotkey reopen, graceful quit, scoped resident reminder delivery, explicit gaming policy, a polished responsive command deck, local reminder creation and lazy camera/CAD panels are implemented. Initial JavaScript is approximately 241 KB. The default native host releases Electron entirely after workspace close, preserving core/identity lifetime. Electron 44.7.0 and actual idle/lifecycle evidence are in [Native resident](NATIVE_RESIDENT.md). Game FPS/thermals, signed packaging, actual keyboard/balloon acceptance and resource use after optional legacy worker activation remain unverified.

## Ordered roadmap for subsequent implementations

Follow [R1-R8 and the follow-on tracks](INARA_REVAMP_PLAN.md#current-baseline-and-implementation-sequence-14-october-2026), reconciled against checkpoint `5f79902`. The [refactor map](UI_AND_CODE_CLEANUP_PLAN.md#remaining-refactor-work-tied-to-the-implementation-sequence) names source areas and acceptance evidence.

| Order | Product outcome | Refactor outcome |
| --- | --- | --- |
| R1 implemented; hardware acceptance pending | Vision studio v2: reliable local preview/tracking and polished controls | One capture/inference/overlay session; legacy tracking consolidation |
| R2a/R2b1-R2b5/R2c implemented | Reliable shared actions and errors | Composition root, thin transports, route/policy matrix, one schema/tool authority, mapped legacy retirement |
| R3a foundation implemented; R3b next | Consistent JARVIS panels, command palette and activity/artifact view | Incremental TypeScript/generated contracts, shared UI/RPC lifecycle, scoped styles/state |
| R4 | Capability/setup diagnostics and resource-aware job controls | Worker launch profiles, reservations/queue, hardware probes, explicit background-job lifetime |
| R5 | Deeper 3D vibe coding and image workflows | Validated change sets, selected-revision edits, kernel/Blender/image adapters with real acceptance gates |
| R6 | Quick assistant and push-to-talk voice | One audio/session stack feeding existing conversation and tool services; optional wake profile later |
| R7 | Native foldable Android companion and secure pairing | Device/project context, scoped grants, revocation and idempotent sync |
| R8 | Read-only selected-notification inbox and summaries | Native ingestion, dedupe, retention and owner-controlled summarization; no WhatsApp reply tools |

R1 software, R2a and R2b1-R2b5 policy groups and R2c retirement are implemented. The two latest authorized steps are complete: live voice uses shared schemas/dispatch, and owner-only connection hydration plus owned face-process lifetime replace facade callbacks. Optional provider/hardware behavior and legacy generated-code/browser hard isolation remain separate acceptance work.

## Next implementation task

1. Continue R3b from [R3 UI/RPC foundation](R3_UI_RPC.md). First install/pin a verified TypeScript compiler and update the lock; run `tsc -p tsconfig.ui.json` and gate CI. Registry certificate failures prevented this in R3a; runtime tests and bundling passed, but semantic type checking is still pending.
2. Migrate CAD request/planner/artifact lifecycle to `src/transport/rpc.ts` and export its Pydantic request contracts. Keep original events, shared backend ownership/approval, scene revisions, artifact integrity and lazy Three.js behavior.
3. Consolidate repeated creative history/status/toolbar controls around the new `PanelHeader`/`PanelState` only where the behavior is shared. Keep project/reconnect/deadline/close handling explicit and test stale callbacks.
4. Visually review desktop/narrow layouts, keyboard focus, reduced motion and DPI. Run affected frontend lifecycle/backend contract checks, build/lint, schema drift and native creative integration; update this handoff with the completed slice.
5. Remaining R3: feature-specific socket/store registration, other legacy panel interiors, command palette and unified activity/artifact view. Do not claim a whole-codebase TypeScript conversion or completed R3 yet.
6. R4 reservations/hard isolation, R5 creative/provider acceptance and R6 audio-stack/physical media work remain separate. Configuration and the real-game benchmark remain deferred; WhatsApp reply drafting/sending stays excluded.

## Completed R3a foundation

Image atelier now uses a panel-owned TypeScript RPC scope with generated request declarations, disconnect/deadline/close cleanup, guarded ACKs and snapshot/live-job reconciliation. The lazy workspace shell shares a responsive JARVIS header and loading/offline/recovery states. 34 frontend and 104 focused Python checks, lint/schema drift/build and native image/CAD integration pass. [Evidence, screenshots, compiler limitation and next slice](R3_UI_RPC.md).

## Completed obsolete-path retirement (R2c)

Removed static voice declarations, ad-hoc AudioLoop CAD/browser/filesystem helpers, the standalone approval gate, fallback confirmation mapping, dead facade state and unused lifecycle injection hooks. Live configuration now builds lazily from shared schemas. `ConfirmationTransport` owns the strict renderer route and resolves only dispatcher approvals. The supported inventory remains 52 socket routes, 53 shared tools (40 text-visible) and 37 voice functions.

668 Python checks and 26 frontend checks pass, with one Blender-dependent skip; lint/build pass. [Retired paths and desktop evidence](RETIRED_PATHS.md) records the final integration results and limits. R3 UI/RPC consolidation is next.

## Completed shared voice and connection checkpoint (R2b5)

All 37 active live voice names now use generated dispatcher schemas and shared permission/approval execution. Twenty additional shared contracts/aliases cover the retained project, filesystem, routine, desktop, vision/device and printer-status actions. The inventory is 52 socket routes, 53 dispatcher tools (40 provider-visible for text) and 37 active voice functions; the original 26 static declarations remain only for cleanup reference.

`ConnectionTransport` owns private hydration and one optional face generation. Locked/control/resident/foreign channels cannot obtain private startup state. A fixed owned face worker holds the camera/model work, stops on disconnect/resource/settings/quit, drops stale callbacks and cleans transient reports. Enabling missing face setup is rejected before persistence; no model downloads or real-camera activation were performed.

666 Python checks and 26 frontend checks pass, with one Blender-dependent skip. Lint/build and actual native/fallback/CAD desktop integration pass. Short native idle is about 67 MB with zero Electron processes after workspace close. See [verification, evidence and remaining limits](VOICE_CONNECTION_POLICY.md). Actual live voice/provider, face matching and physical media acceptance remain unverified. The unused static helpers are the next cleanup target, rather than another live policy path.

## Completed workspace compatibility checkpoint (R2b4)

Ten memory/media/legacy CAD/browser wire routes now use strict owner-scoped service/transport envelopes. Memory exports stay inside the captured project and preserve existing files. Voice callbacks, bounded confirmations and detached work belong to one session generation; unstamped bus events stay internal. Direct and typed requests cancel on origin disconnect, with provider/browser cleanup. The inventory remains 52 socket routes and now contains 33 dispatcher tools (24 provider-visible), plus 26 separate legacy voice declarations.

462 Python checks pass with one Blender-dependent skip; all 26 frontend checks, lint/build and actual native/fallback/CAD desktop integration pass. Short native idle remains about 67 MB with zero Electron processes after close. See [verification and material limits](WORKSPACE_POLICY.md). Live voice/media, provider-generated CAD and autonomous browser effects were not exercised. This checkpoint does not complete voice/shared-dispatch parity or legacy worker isolation.

## Completed combined compatibility checkpoint (R2b3)

Owner-scoped Kasa/printer compatibility tools preserve saved settings and endpoint selection. The print pipeline snapshots contained project inputs, independently authorizes slice/upload/start, owns slicer process lifetime and records non-replayable attempts durably. Reminder receipts/roles and CAD planner permissions now use the owner/shared policy boundaries. The route inventory remains 52 socket routes and now contains 25 dispatcher tools, 21 provider-visible, plus 26 separate legacy voice declarations.

377 Python and 26 frontend checks pass, with one Blender-dependent skip; lint/build and actual native/fallback/CAD desktop integration pass. A reproduced Windows progress-file sharing failure no longer aborts CAD exports. Two earlier native timing failures remain a documented limitation. See [evidence, limitations and next batch](DEVICE_PRINT_POLICY.md). Real devices, printers and slicer output remain unverified; this checkpoint does not complete all R2b work.

## Completed settings/lifecycle checkpoint (R2b2)

Seven settings/permission/resource/native/shutdown routes now use injected strict-schema transports. Settings authority is an independent authenticated owner/renderer gate; a request cannot disable its own authorization. Known permission values, atomic persistence, scoped refreshes, pinned owner reconnect, strict native actions, native/fallback gaming authority and cleanup-before-exit are verified. The old settings panel waits for server acceptance before changing face/camera state; first-launch renderer connection waits for native owner registration.

288 Python and 26 frontend checks pass, plus build/lint, actual native admin socket/reopen/reminder/gaming checks and fallback lifecycle verification. Short native idle is about 67 MB with zero Electron processes after close. [Evidence and remaining limits](SETTINGS_LIFECYCLE_POLICY.md). R2b3 compatibility adapters are next; this does not complete all R2b policy migration.

## Completed route-policy checkpoint (R2b1)

The tested inventory covers 52 socket routes, `/status`, 15 shared tools and 26 separate legacy voice declarations. Seven desktop/device actions now use strict schemas and the shared dispatcher for both direct and typed model calls, with renderer checks, approval/denial, scoped responses, stamped agent event ownership, cooperative execution deadlines and origin-disconnect cancellation. Confirmation payloads now require a real boolean and an authenticated renderer; voice binding remains a legacy seam.

222 Python and 26 frontend checks pass, including 61 new policy checks. Actual native failure/reopen/reminder/gaming/shutdown verification passes; short idle is approximately 66 MB with zero Electron processes after close. New action tests use injected adapters, not real device/app actions. See [Route policy migration and limits](ROUTE_POLICY_MIGRATION.md). R2b2 is next.

## Completed core composition milestone (R2a)

`application.py` constructs the lean runtime and owns ASGI/lifespan, creative shutdown, reminder polling and event subscriptions. Injected desktop sessions own token/identity/role/native-owner checks and immutable request project snapshots. Conversation/reminder transports and event delivery are separated; the supported server retains mapped compatibility aliases and legacy handlers. Multi-channel disconnect preserves other channels' approvals. No extracted module imports the facade.

161 Python and 26 frontend checks pass, plus actual native failure/reopen/reminder/gaming verification, CAD/scene worker rendering and labelled image-fixture integration. Short native idle is approximately 66 MB with zero Electron processes after close. Remaining direct-route bypasses, legacy broadcasts and audio/face callback seams are explicitly mapped for R2b/R2c/R6. See [Core composition evidence and limits](CORE_COMPOSITION.md).

## Completed Vision studio milestone (R1)

The local camera workspace now has source/mirror/overlay/rate controls, two-hand skeletons, explicit capture/tracking state and side-classification metrics. Inference runs in an opt-in bounded Web Worker, with stream/model cleanup for source changes, device loss, close/hidden/suspend/minimize and gaming. Unused duplicate capture/tracking hooks are retired; no recording, uploads or actions were added.

146 Python and 26 frontend checks pass. Actual hidden renderer verification initializes the real bundled model and infers blank synthetic frames; labelled fixture landmarks verify overlay controls. Seven workers terminate and resident recovery is around 64 MB. Actual camera/hand accuracy and physical sleep/device acceptance remain pending. See [Vision studio](VISION_STUDIO.md).

## Completed Image atelier milestone

A responsive prompt/frame/seed/quality workspace, installation-aware local SD/SDXL adapter, owned image worker, PNG/recipe preview/download and protected revisions are implemented. CAD and image jobs now share one durable service/transport and one creative execution slot. No weights/dependencies were installed or configured. Real generation is unverified; the normal UI explains setup and disables generation. 144 Python checks and nine frontend checks pass. Actual native UI checks use labelled test-only fixtures, verify cancellation/revisions and approximately 65 MB resident recovery; production rejects fixture provenance. [Evidence and limits](IMAGE_ATELIER.md).

## Completed scene assembly milestone

Up to eight typed parametric objects, scale/XYZ rotation/translation, four materials, add/duplicate/remove, material-aware GLB preview, STL/GLB/recipe revisions and an installation-aware fixed Blender bridge are implemented. Existing job permissions, cancellation and scoped storage are retained; old revisions remain readable. The optional provider planner stays single-solid only. 116 Python checks and nine frontend checks pass; the real Blender test is skipped. Actual hidden renderer verification covers three-part editing/export/restore and approximately 65 MB resident recovery. See [Scene Studio evidence and limitations](SCENE_STUDIO.md).

## Completed CAD worker milestone

Offline box/bracket/enclosure generation, editable dimensions, real orbit/wireframe preview, STL/GLB/recipe download, protected scoped job history, shared build authorization, cancellation/timeout and owned worker cleanup are implemented. Optional AI proposals return validated recipe data for review; configuration stays deferred. The older voice adapter is preserved. See [CAD Studio evidence and limits](CAD_STUDIO.md). Typed scene assembly and an optional Blender bridge are now implemented; actual Blender execution is installation-dependent and still unverified.

## Keep model use efficient

Give each task a bounded objective, relevant files, accepted contracts and concrete completion criteria. Read the review once and avoid repeating the entire repository audit for every feature. Keep task status and important decisions in compact project notes so the next turn can resume without reconstructing the conversation.

Use Medium as the default, increase effort when complexity or a demonstrated failure warrants it, and evaluate quality on completed tasks. A failed check needs diagnosis, not repeated blind regeneration. Reserve expensive reviews for integration boundaries and release gates. Reuse valid outputs, incremental builds and relevant checks; avoid unnecessary paid end-to-end runs.

## Prompt for the next implementation session

> Implement the next bounded R2b3 Kasa/printer compatibility group in docs/IMPLEMENTATION_HANDOFF.md. Read docs/SETTINGS_LIFECYCLE_POLICY.md, docs/ROUTE_POLICY_MATRIX.md and the current migration/status records. Add strict schemas, owner/role policy, shared permission/approval where applicable and scoped responses for Kasa discovery/control and printer discovery/add/profile routes. Preserve saved configuration and useful adapters. Treat printer file containment and slice/upload/start authorization explicitly; split a separate print checkpoint if necessary and keep pending matrix rows honest. Verify direct/model denials, malformed requests, owner/project scope, approval/cancel and affected native flows using fixture adapters. Preserve native identity/token, reminders, explicit quit/gaming override and atomic owner settings. No real device/printer actions, provider setup, game benchmarking or WhatsApp replies are part of this refactor.


The implementation model is a development choice. INARA's own local/cloud runtime models remain separately configured through the capability router, with dedicated speech, image and vision adapters where needed.
