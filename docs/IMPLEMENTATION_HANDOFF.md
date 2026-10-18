# INARA implementation handoff and model choice

Updated 19 October 2026. Implement against the [architecture](INARA_REVAMP_PLAN.md), [project review](PROJECT_REVIEW.md) and [code cleanup and JARVIS interface plan](UI_AND_CODE_CLEANUP_PLAN.md).

The core/persistence milestones, polished JARVIS workspace, native resident, offline CAD worker, typed scene assembly, optional Blender bridge, Image atelier/job adapter, Vision studio v2, R2a core composition/session extraction and R2b1/R2b2/R2b3 route-policy groups are implemented. Real image generation remains unverified and unconfigured. Actual Blender execution remains unverified because it is not installed. Read [Implementation status](IMPLEMENTATION_STATUS.md), [CAD Studio](CAD_STUDIO.md), [Scene Studio](SCENE_STUDIO.md), [Image atelier](IMAGE_ATELIER.md), [Vision studio](VISION_STUDIO.md), [Native resident evidence](NATIVE_RESIDENT.md), [Persistence](PERSISTENCE.md), [Core composition](CORE_COMPOSITION.md), [Route policy migration](ROUTE_POLICY_MIGRATION.md) and [Settings/lifecycle policy](SETTINGS_LIFECYCLE_POLICY.md) and [Device/print workflow policy](DEVICE_PRINT_POLICY.md) before continuing. The user explicitly deferred the real-game benchmark; API configuration remains deferred.

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
| R2a/R2b1/R2b2/R2b3 implemented; remaining R2b/R2c next | Reliable shared actions and errors | Composition root, thin transports, route/policy matrix, one schema/tool authority, mapped legacy retirement |
| R3 | Consistent JARVIS panels, command palette and activity/artifact view | Incremental TypeScript/generated contracts, shared UI/RPC lifecycle, scoped styles/state |
| R4 | Capability/setup diagnostics and resource-aware job controls | Worker launch profiles, reservations/queue, hardware probes, explicit background-job lifetime |
| R5 | Deeper 3D vibe coding and image workflows | Validated change sets, selected-revision edits, kernel/Blender/image adapters with real acceptance gates |
| R6 | Quick assistant and push-to-talk voice | One audio/session stack feeding existing conversation and tool services; optional wake profile later |
| R7 | Native foldable Android companion and secure pairing | Device/project context, scoped grants, revocation and idempotent sync |
| R8 | Read-only selected-notification inbox and summaries | Native ingestion, dedupe, retention and owner-controlled summarization; no WhatsApp reply tools |

R1 software, R2a and R2b1-R2b3 are implemented. Vision/device/printer hardware acceptance remains pending. The combined R2b3 batch covers Kasa/printer setup, a separately authorized print pipeline, reminder receipt/role policy and CAD planner authorization. Remaining legacy routes and voice ownership keep R2b unfinished; R2c follows them.

## Next implementation task

1. Read [Device/print workflow policy](DEVICE_PRINT_POLICY.md), [Route matrix](ROUTE_POLICY_MATRIX.md), [Route policy migration](ROUTE_POLICY_MIGRATION.md) and [Core composition](CORE_COMPOSITION.md).
2. Continue a related batch of remaining memory/media/legacy creative/browser routes. Inventory actual consumers and payloads first; preserve useful adapters and migrate policy/ownership/lifetime without enabling devices or providers.
3. Add strict schemas, owner/role checks, shared permissions where applicable, scoped results and owned cancellation. Cover direct/model denial, malformed inputs, immutable project context, origin disconnect and resource/close behavior.
4. Address unstamped voice/event ownership and legacy confirmation binding explicitly. The AudioLoop device/printer path remains separate from the new desktop print pipeline. Do not claim parity until it is tested.
5. Retire obsolete declarations/references at R2c only after replacement consumers are verified. Keep the supported application root; do not replace it with the archive. R3 UI/contracts consolidation follows these boundaries.
6. Preserve native identity/token, reminder receipt, quit/gaming authority and atomic settings. Run focused checks, production build and affected native/fallback integration. Provider setup, hardware/model acceptance and real-game benchmarking remain deferred; WhatsApp replies remain excluded.

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
