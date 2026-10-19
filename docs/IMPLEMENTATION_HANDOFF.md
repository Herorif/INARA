# INARA implementation handoff and model choice

Updated 19 October 2026. Implement against the [architecture](INARA_REVAMP_PLAN.md), [project review](PROJECT_REVIEW.md) and [code cleanup and JARVIS interface plan](UI_AND_CODE_CLEANUP_PLAN.md).

The core/persistence milestones, polished JARVIS workspace, native resident, offline CAD worker, typed scene assembly, optional Blender bridge, Image atelier/job adapter, Vision studio v2, R2a core composition/session extraction and R2b1-R2b5 policy groups, R2c retirement, the R3 UI/contracts milestone, R4 capabilities/resource lifetime and R5 offline creative workflows plus R6 quick assistant/reviewed speech are implemented. R7 desktop/server pairing and native Android source are now implemented; Android compilation/device acceptance is still gated by missing tooling. Real image generation remains unverified and unconfigured. Actual Blender execution remains unverified because it is not installed. Read [Implementation status](IMPLEMENTATION_STATUS.md), [CAD Studio](CAD_STUDIO.md), [Scene Studio](SCENE_STUDIO.md), [Image atelier](IMAGE_ATELIER.md), [Vision studio](VISION_STUDIO.md), [Native resident evidence](NATIVE_RESIDENT.md), [Persistence](PERSISTENCE.md), [Core composition](CORE_COMPOSITION.md), [Route policy migration](ROUTE_POLICY_MIGRATION.md) and [Settings/lifecycle policy](SETTINGS_LIFECYCLE_POLICY.md) and [Device/print workflow policy](DEVICE_PRINT_POLICY.md) and [Workspace policy](WORKSPACE_POLICY.md) and [Shared voice/connection policy](VOICE_CONNECTION_POLICY.md) before continuing. The user explicitly deferred the real-game benchmark; API configuration remains deferred.

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
| R3 implemented | Consistent JARVIS panels, command palette and activity/artifact view | Incremental TypeScript/generated contracts, shared UI/RPC lifecycle, scoped styles/state |
| R4 implemented | Capability/setup diagnostics and resource-aware job controls | Worker launch profiles, reservations/queue, hardware probes, explicit background-job lifetime |
| R5 offline workflows implemented; optional adapters gated | Deeper 3D vibe coding and image workflows | Validated change sets, selected-revision edits, kernel/Blender/image adapters with real acceptance gates |
| R6 implemented; physical speech acceptance pending | Quick assistant and push-to-talk voice | One audio/session stack feeding existing conversation and tool services; optional wake profile later |
| R7 source/protocol implemented; APK/device acceptance pending | Native foldable Android companion and secure pairing | Device/project context, scoped grants, revocation and idempotent sync |
| R8 | Read-only selected-notification inbox and summaries | Native ingestion, dedupe, retention and owner-controlled summarization; no WhatsApp reply tools |

R1 software, R2a and R2b1-R2b5 policy groups and R2c retirement are implemented. The two latest authorized steps are complete: live voice uses shared schemas/dispatch, and owner-only connection hydration plus owned face-process lifetime replace facade callbacks. Optional provider/hardware behavior and legacy generated-code/browser hard isolation remain separate acceptance work.

## Next implementation task

1. R8 selected **read-only** notification inbox/summaries is the next source milestone. Read [R7 implementation and acceptance limits](R7_ANDROID_FOUNDATION.md) and [Android build notes](../android/README.md) first. R7 APK compilation and physical Fold8/Keystore/Doze acceptance remain unverified; do not represent source guards or Python fixtures as Android execution.
2. Inspect available Android tooling before attempting a build. This environment has no configured JDK/Gradle/SDK/ADB. No tool/model/dependency download is automatic. The supplied Android build entry defaults offline and requires pre-existing tools/SDK; a later authorized dependency resolution/build must record verification/locks and actual compile/test results.
3. For R8, design native explicit notification-access consent, app/conversation allowlists, minimal/redacted ingestion, bounded encrypted retention, dedupe/idempotent sync and visible revocation. Add server device/project-scoped read-only notification grants; R7 grants alone must not authorize notification upload/read or remote tool/approval mutations.
4. Verify parsing, scope, duplicates, expiry, disconnect/process-death and permission revocation using fixtures. Keep real notification access disabled until the native build/device acceptance and explicit owner permission are available. Do not read or transmit real notification content during implementation QA.
5. Keep summaries clearly distinguished from replies. WhatsApp reply drafting, sending, automatic acknowledgements and notification action execution remain excluded until specifically requested. No call answering/default dialer/forwarding, SIM/account migration or live messages are authorized by this milestone.
6. Preserve R6 speech, R7 opt-in TLS/identity/replay/grants, protected data, reminder/job lifetime and resident behavior. Exact hardware/provider/Blender/image/kernel acceptance, physical microphone/camera and real-game benchmarking remain deferred.

## R7 source/protocol milestone and Android acceptance gap

The responsive desktop companion panel, explicit private-address TLS listener, two-minute single-use invitations, owner fingerprint approval, DPAPI-protected device/key/replay state, 30-day device/project grants, revocation and isolated read-only mobile API are implemented. Optional phone chat uses the shared conversation ledger with an empty tool dispatcher and its own explicit grant. Request receipts do not replay uncertain sends or import desktop history.

Native Kotlin/Compose source provides single/two-pane layouts, file/paste invitation import, certificate validation, Android Keystore signing/encrypted state, bounded job previews and explicit chat/receipt recovery. Only INTERNET permission is declared. No Android build was possible with the available tools; no APK, native rendering, key hardware placement, process death, fold/unfold or battery acceptance is claimed. Optional QR rendering was not installed; invitation-file transfer is verified. See [R7 evidence and remaining acceptance](R7_ANDROID_FOUNDATION.md).

773 Python tests and 63 Node checks pass, with one Blender skip. Types, generated-contract drift, Ruff, production web build, source/manifest guards and native loopback TLS/desktop pairing checks pass. The final request-body and embedded-listener refinements also pass the focused 40 Python mobile checks. Android compilation/JVM/Keystore/device tests remain unrun because tooling is unavailable; no hosted CI run is claimed.

R8 is next for source work. Completing the deferred Android build/device gate is required before enabling phone features; no additional R7 lettered implementation substep is scheduled.

## Completed R6 quick assistant and voice consolidation

A lazy compact JARVIS surface opens with Ctrl+Shift+Space, the command palette or Quick assistant. Typed chat shares the existing conversation. Voice uses explicit prepare/permission, hold, release, streaming transcription after release, review/edit and Send. Only Send reaches the shared conversation/tool dispatcher. Optional local-only speech playback has interruption. One bounded PCM/device/session owner replaces the two old always-on loops; both old constructors now return a migration message. Closing, disconnecting, source loss, project/lock changes, suspend and resource restrictions release or invalidate work without replay.

733 Python tests and 60 Node checks pass, with one Blender skip. TypeScript, generated-contract drift, Ruff and the production build pass. Native synthetic-speech and Electron fallback lifecycle acceptance pass; post-close native resident recovery is about 66 MB. Actual microphone/provider/local voice, Bluetooth/sleep and creative/device acceptance remain deferred.

Fixture-based acceptance is recorded in [R6 implementation and limits](R6_QUICK_ASSISTANT.md). Real microphones, Bluetooth/sleep behavior, installed local voice quality and provider transcription accuracy/latency remain unverified. No API/model/device setup was performed. R7 secure pairing is next; no further R6 substep is scheduled for the completed fixture-tested implementation.

## Completed R5 offline Creative Studio milestone

Shared draft undo/redo, explicit branch ancestry, recipe fingerprints, selected-object editing, separate draft blockouts/translation gizmo, saved camera views, revision comparisons, image gallery/recipe reuse and reviewed bounded change proposals are implemented. Parent/stale/owner checks preserve existing revisions, and worker generation still requires the existing admission/approval. Typed Blender presentation presets extend the fixed bridge, while actual Blender/provider/image/kernel acceptance remains deferred; holes/fillets/booleans/STEP are explicitly unavailable.

707 Python and 52 Node checks pass, with one Blender skip; types/drift/lint/build and native CAD/image acceptance pass. Nine workers exited and short post-worker resident recovery remains about 67 MB. See [behavior, evidence and material limits](R5_CREATIVE_STUDIO.md). R6 is next; no additional R5 substep is scheduled for the completed offline workflow.

## Completed R4 capability/resource milestone

The responsive Capability center, on-demand Windows CPU/RAM diagnostics, explicit unknown GPU information, centralized capability/model/worker profiles, shared bounded FIFO creative queue, capacity checks and explicit job release are implemented. Panel closure cancels by default; owner-scoped per-job background continuation lasts only within the current connected workspace/core session. Gaming/resident restrictions, interruption and cleanup-fault handling preserve ownership. Image generation now uses an explicit CPU profile rather than automatic CUDA selection.

690 Python and 46 Node checks pass, with one Blender skip; types/drift/lint/build and native image/CAD/lifecycle acceptance pass. Short native idle remains about 67 MB with zero Electron processes after closure. See [implementation, acceptance evidence and limitations](R4_RESOURCE_LIFETIME.md). R5 offline workflows are now implemented; no additional R4 substep is pending.

## Completed R3 UI and contract milestone

The shared JARVIS design/panel/approval system, embedded legacy interiors, keyboard command palette and project-scoped CAD/image Activity/artifact view are implemented. CAD/image/planner/preview calls share scoped lifetime and runtime guards; schemas/types and UI contract version 1 are generated. Feature-specific event registrars replace the monolithic store bridge, and typed conversation updates retain their captured project/session scope. The pinned development compiler and semantic checks now pass, resolving the earlier installation/check gap.

669 Python and 41 Node checks pass, with one Blender skip, alongside type checks, drift/lint/build and native/renderer acceptance. [Evidence, screenshots and remaining physical/provider limits](R3_UI_RPC.md). R4 is now implemented; no additional R3 substep is pending.

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

> Implement the R8 read-only selected-notification foundation from docs/IMPLEMENTATION_HANDOFF.md and docs/R7_ANDROID_FOUNDATION.md. Preserve R7 opt-in transport, per-device/project grants, replay protection and tool-free phone chat. Check tool availability; keep missing Android build/device acceptance explicit and do not install tooling automatically. Add explicit native access/allowlist/retention controls, scoped encrypted minimal ingestion, dedupe and read-only summary contracts using fixtures. No real notifications, phone calls, message actions or WhatsApp reply drafting/sending are part of this task.


The implementation model is a development choice. INARA's own local/cloud runtime models remain separately configured through the capability router, with dedicated speech, image and vision adapters where needed.
