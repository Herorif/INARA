# INARA implementation handoff and model choice

Updated 14 October 2026. Implement against the [architecture](INARA_REVAMP_PLAN.md), [project review](PROJECT_REVIEW.md) and [code cleanup and JARVIS interface plan](UI_AND_CODE_CLEANUP_PLAN.md).

The core/persistence milestones, polished JARVIS workspace, native resident, offline CAD worker, typed scene assembly, optional Blender bridge, Image atelier/job adapter and Vision studio v2 are implemented. Real image generation remains unverified and unconfigured. Actual Blender execution remains unverified because it is not installed. Read [Implementation status](IMPLEMENTATION_STATUS.md), [CAD Studio](CAD_STUDIO.md), [Scene Studio](SCENE_STUDIO.md), [Image atelier](IMAGE_ATELIER.md), [Vision studio](VISION_STUDIO.md), [Native resident evidence](NATIVE_RESIDENT.md) and [Persistence](PERSISTENCE.md) before continuing. The user explicitly deferred the real-game benchmark; API configuration remains deferred.

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
| R2a/R2b/R2c | Reliable shared actions and errors | Composition root, thin transports, route/policy matrix, one schema/tool authority, mapped legacy retirement |
| R3 | Consistent JARVIS panels, command palette and activity/artifact view | Incremental TypeScript/generated contracts, shared UI/RPC lifecycle, scoped styles/state |
| R4 | Capability/setup diagnostics and resource-aware job controls | Worker launch profiles, reservations/queue, hardware probes, explicit background-job lifetime |
| R5 | Deeper 3D vibe coding and image workflows | Validated change sets, selected-revision edits, kernel/Blender/image adapters with real acceptance gates |
| R6 | Quick assistant and push-to-talk voice | One audio/session stack feeding existing conversation and tool services; optional wake profile later |
| R7 | Native foldable Android companion and secure pairing | Device/project context, scoped grants, revocation and idempotent sync |
| R8 | Read-only selected-notification inbox and summaries | Native ingestion, dedupe, retention and owner-controlled summarization; no WhatsApp reply tools |

R1 implementation is complete with synthetic-stream/real-model verification; owner-hardware acceptance remains pending. The next bounded deliverables are R2a, R2b and R2c. The rows are milestones, not promises that a whole subsystem fits one coding turn. Memory/backup, browser/devices/printing, call feasibility and signed packaging have explicit follow-on tracks. Phone feasibility is assessed once the Android shell exists, before committing to a call engine. Keep the next task below scoped to R2a; do not implement the whole roadmap at once.

## Next implementation task

1. Implement R2a only: extract application construction/lifetime, session identity, project context and event delivery from `backend/server.py`. Preserve it as the compatible supported entry point.
2. Use explicit constructor dependencies and a composition root; move thin feature registration/transport by ownership. Keep native identity/token scope, reminders, shared CAD/image jobs and all current UI behavior intact.
3. Preserve active imports from `backend/core/` until individually mapped. Avoid replacing the supported server with its archived counterpart or introducing another authoritative runtime.
4. Keep event names/payloads compatible; verify owner/project context, reconnect/no replay, startup/shutdown and lazy model imports. Update tests away from production globals where a public injection boundary is available, retaining a narrow facade for required compatibility.
5. Run the existing deterministic/native/renderer checks affected by extraction and record any remaining legacy bypass. R2b then performs the complete route/policy migration; do not claim it is completed by moving files.
6. Provider/model configuration, real-hand/camera acceptance, real diffusion/Blender execution and the real-game benchmark remain deferred or unverified as documented. WhatsApp replies remain excluded.

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

> Implement R2a core composition/session extraction in docs/IMPLEMENTATION_HANDOFF.md. Read docs/IMPLEMENTATION_STATUS.md, docs/INARA_REVAMP_PLAN.md, docs/UI_AND_CODE_CLEANUP_PLAN.md and docs/VISION_STUDIO.md. Extract explicit construction/lifetime, identity/project context and event delivery from backend/server.py while preserving the supported entry point, event contracts, native identity/token scope, durable reminders, shared creative jobs and lazy UI/model lifetime. Do not switch to the archived server or combine the entire R2b policy migration with this checkpoint. Verify startup/shutdown, owner/project context, reconnect/no replay and affected native/renderer flows. Configuration and real-game benchmarking remain deferred; WhatsApp replies stay excluded.


The implementation model is a development choice. INARA's own local/cloud runtime models remain separately configured through the capability router, with dedicated speech, image and vision adapters where needed.
