# INARA implementation handoff and model choice

Updated 14 October 2026. Implement against the [architecture](INARA_REVAMP_PLAN.md), [project review](PROJECT_REVIEW.md) and [code cleanup and JARVIS interface plan](UI_AND_CODE_CLEANUP_PLAN.md).

The core/persistence milestones, polished JARVIS workspace, native resident, offline CAD worker, typed scene assembly, optional Blender bridge and Image atelier/job adapter are implemented. Real image generation remains unverified and unconfigured. Actual Blender execution remains unverified because it is not installed. Read [Implementation status](IMPLEMENTATION_STATUS.md), [CAD Studio](CAD_STUDIO.md), [Scene Studio](SCENE_STUDIO.md), [Image atelier](IMAGE_ATELIER.md), [Native resident evidence](NATIVE_RESIDENT.md) and [Persistence](PERSISTENCE.md) before continuing. The user explicitly deferred the real-game benchmark; API configuration remains deferred.

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

## Next implementation task

1. Preserve the resident, offline solids/scenes, Image atelier, shared creative-job lifetime, protected history, identity and JARVIS workspace. Keep provider/model configuration deferred and WhatsApp replies excluded.
2. Improve the on-demand Vision studio with explicit session state, local tracking overlays and useful controls. Inspect existing camera/tracker modules first; reuse working local assets.
3. Keep camera acquisition and heavy analysis opt-in. Handle permission failure, device loss, duplicate starts, panel closure, workspace loss and gaming mode without retaining streams or analysis work. Default to preview; do not add automatic recording or desktop actions.
4. Verify synthetic-stream/tracker behavior, rendered narrow/desktop controls, lazy startup assets and resource recovery. Actual owner-camera acceptance remains separate when hardware access is available.
5. Real diffusion and Blender generation remain installation-dependent acceptance checks. Do not claim quality/GPU recovery from fixture plumbing checks. Read [Image atelier](IMAGE_ATELIER.md) and [Scene Studio](SCENE_STUDIO.md).
6. Android pairing/calls follow the vision work. The real-game benchmark is deferred; signing/packaging, optional worker dependency locks and GPU/thermal admission remain release/setup work.

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

> Implement the on-demand Vision studio improvement in docs/IMPLEMENTATION_HANDOFF.md. Read docs/IMPLEMENTATION_STATUS.md, docs/IMAGE_ATELIER.md, docs/SCENE_STUDIO.md and docs/NATIVE_RESIDENT.md. Preserve shared CAD/image jobs, native lifetime, history, permissions and the JARVIS UI. Inspect existing camera/tracker code before changing it. Add explicit session state, useful local tracking overlays/controls, robust acquisition/device-loss/closure/gaming cleanup, responsive visuals and synthetic-stream verification. Do not add automatic recording or actions. Provider/model configuration and the real-game benchmark remain deferred; WhatsApp replies remain excluded. Real diffusion and Blender acceptance are still pending installation/setup.


The implementation model is a development choice. INARA's own local/cloud runtime models remain separately configured through the capability router, with dedicated speech, image and vision adapters where needed.
