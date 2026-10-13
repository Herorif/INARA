# INARA implementation handoff and model choice

Updated 13 October 2026. Implement against the [architecture](INARA_REVAMP_PLAN.md), [project review](PROJECT_REVIEW.md) and [code cleanup and JARVIS interface plan](UI_AND_CODE_CLEANUP_PLAN.md).

The first two implementation milestones are complete. Read [Implementation status](IMPLEMENTATION_STATUS.md) before continuing; the resident lifecycle and polished responsive JARVIS workspace foundation are implemented. Resident footprint reduction remains open. Read [Persistence](PERSISTENCE.md) before altering stored records.

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

Tray/hotkey reopen, graceful quit, scoped resident reminder delivery, explicit gaming policy, a polished responsive command deck, local reminder creation and lazy camera/CAD panels are implemented. See [implementation evidence and resource limits](RESIDENT_AND_WORKSPACE.md). Initial JavaScript fell to approximately 241 KB, but the resident Electron footprint still exceeds the architecture target. Do not claim the full resident resource gate is complete.

## Next implementation task

1. Preserve the existing typed tools, protected persistence, identity migration and tested command deck. Keep API configuration deferred.
2. Prototype a lean Windows resident host, with Electron only when a workspace is open. Compare measured idle memory/CPU, cold/warm reopen, tray/hotkey reliability and packaged installation requirements before choosing the production host.
3. Retain one owned backend, scoped resident delivery, request deduplication, explicit quit, bounded recovery and safe child-process ownership. Avoid orphan processes and token exposure; preserve existing user data.
4. Run a ten-minute idle measurement and a representative gaming test. Keep manual gaming mode until automatic detection is separately implemented and verified. Record failures honestly; do not obscure shared-memory or backend costs.
5. Establish a supported Electron upgrade as a release gate, while retaining native/WebGL compatibility and reproducible checks.
6. Finish this bounded footprint/lifecycle follow-up before adding isolated CAD/Blender/image workers. Keep WhatsApp replies excluded; Android pairing and calls remain later milestones.

## Keep model use efficient

Give each task a bounded objective, relevant files, accepted contracts and concrete completion criteria. Read the review once and avoid repeating the entire repository audit for every feature. Keep task status and important decisions in compact project notes so the next turn can resume without reconstructing the conversation.

Use Medium as the default, increase effort when complexity or a demonstrated failure warrants it, and evaluate quality on completed tasks. A failed check needs diagnosis, not repeated blind regeneration. Reserve expensive reviews for integration boundaries and release gates. Reuse valid outputs, incremental builds and relevant checks; avoid unnecessary paid end-to-end runs.

## Prompt for the next implementation session

> Implement the resident footprint follow-up in docs/IMPLEMENTATION_HANDOFF.md. Read docs/IMPLEMENTATION_STATUS.md, docs/PERSISTENCE.md and docs/RESIDENT_AND_WORKSPACE.md. Preserve the polished JARVIS workspace and durable tool/reminder contracts. Prototype a lean Windows resident host with Electron only while the workspace is open; retain owned-backend lifecycle, scoped delivery, hotkey/tray reopen and protected identity. Compare actual memory/CPU and validate close/reopen, quit and failure recovery. Keep API configuration deferred and WhatsApp replies excluded. Report the measured result before expanding into creative workers.

The implementation model is a development choice. INARA's own local/cloud runtime models remain separately configured through the capability router, with dedicated speech, image and vision adapters where needed.
