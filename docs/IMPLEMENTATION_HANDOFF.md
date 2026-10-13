# INARA implementation handoff and model choice

Updated 14 October 2026. Implement against the [architecture](INARA_REVAMP_PLAN.md), [project review](PROJECT_REVIEW.md) and [code cleanup and JARVIS interface plan](UI_AND_CODE_CLEANUP_PLAN.md).

The core/persistence milestones, polished responsive JARVIS workspace and native resident follow-up are implemented. Read [Implementation status](IMPLEMENTATION_STATUS.md), [Native resident evidence](NATIVE_RESIDENT.md) and [Persistence](PERSISTENCE.md) before continuing. The user explicitly deferred the real-game benchmark; API configuration remains deferred.

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

1. Preserve the native host, typed tools, protected persistence, old profile/identity and tested JARVIS command deck. Keep API configuration deferred and WhatsApp replies excluded.
2. Build a typed CAD/Blender job contract through the existing dispatcher: validate geometry/job arguments, enforce project containment and configured authorization, and return artifact metadata with durable request IDs.
3. Start with deterministic offline parametric geometry and a real preview/export workflow. Add an optional model adapter for natural-language plans without making local preview require a provider key.
4. Run creative work in an owned, isolated process with bounded admission, timeout, cancellation, sanitized errors and explicit cleanup. Gaming mode rejects new jobs. Heavy dependencies/models remain absent from the resident process.
5. Verify generated artifact geometry and actual close/cancel/failure cleanup. Re-measure resident use after worker exit; do not accept a successful preview that leaves a persistent worker/model behind.
6. Keep image generation workers, advanced vision and Android pairing/calls as subsequent bounded tasks. The deferred real-game benchmark and signed packaging remain acceptance/release work.

## Keep model use efficient

Give each task a bounded objective, relevant files, accepted contracts and concrete completion criteria. Read the review once and avoid repeating the entire repository audit for every feature. Keep task status and important decisions in compact project notes so the next turn can resume without reconstructing the conversation.

Use Medium as the default, increase effort when complexity or a demonstrated failure warrants it, and evaluate quality on completed tasks. A failed check needs diagnosis, not repeated blind regeneration. Reserve expensive reviews for integration boundaries and release gates. Reuse valid outputs, incremental builds and relevant checks; avoid unnecessary paid end-to-end runs.

## Prompt for the next implementation session

> Implement the isolated CAD/Blender worker milestone in docs/IMPLEMENTATION_HANDOFF.md. Read docs/IMPLEMENTATION_STATUS.md, docs/PERSISTENCE.md and docs/NATIVE_RESIDENT.md. Preserve the native tray/core lifetime, polished JARVIS workspace and durable authorization/request contracts. Start with deterministic offline geometry, typed job validation and a real artifact preview/export loop; add an optional natural-language provider adapter. Own and clean up the worker process, support cancellation/timeouts, reject jobs in gaming mode and verify geometry plus resource recovery. Keep API configuration deferred and WhatsApp replies excluded. The real-game benchmark remains deferred by the user.

The implementation model is a development choice. INARA's own local/cloud runtime models remain separately configured through the capability router, with dedicated speech, image and vision adapters where needed.
