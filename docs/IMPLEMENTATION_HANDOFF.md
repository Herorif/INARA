# INARA implementation handoff and model choice

Updated 13 October 2026. Implement against the [architecture](INARA_REVAMP_PLAN.md), [project review](PROJECT_REVIEW.md) and [code cleanup and JARVIS interface plan](UI_AND_CODE_CLEANUP_PLAN.md).

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

## First implementation task

Start with a reproducible development baseline and a single independent typed-conversation path. Do not attempt the full architecture in one patch.

1. Inspect the current workspace and preserve existing data before executing initialization code. Establish source-control checkpoints if this downloaded copy still has no repository metadata.
2. Check installed Node/Python tools and create the minimum reproducible environment needed for this milestone. The previous review environment lacked Node and application dependencies; verify again rather than assuming this remains true.
3. Extract a conversation service and lazy provider initialization. Typed input must not require a running `AudioLoop` or microphone permission. Preserve the desktop transport contract through an adapter.
4. Introduce validated requests and results, stable conversation identity, structured errors and the common tool-dispatch boundary. Fix project-path containment before allowing writes through the new path.
5. Verify a successful typed exchange with microphone access disabled, missing/invalid provider configuration, provider failure, and correct scope enforcement for a representative tool. Keep real API tests opt-in and ensure deterministic checks do not depend on paid calls.
6. Record changed behavior, checks and remaining limitations. Continue next with transactional reminders and recoverable project sessions, then the resident lifecycle and new UI shell.

## Keep model use efficient

Give each task a bounded objective, relevant files, accepted contracts and concrete completion criteria. Read the review once and avoid repeating the entire repository audit for every feature. Keep task status and important decisions in compact project notes so the next turn can resume without reconstructing the conversation.

Use Medium as the default, increase effort when complexity or a demonstrated failure warrants it, and evaluate quality on completed tasks. A failed check needs diagnosis, not repeated blind regeneration. Reserve expensive reviews for integration boundaries and release gates. Reuse valid outputs, incremental builds and relevant checks; avoid unnecessary paid end-to-end runs.

## Prompt for the next implementation session

> Implement the first milestone in docs/IMPLEMENTATION_HANDOFF.md. Read docs/PROJECT_REVIEW.md, docs/INARA_REVAMP_PLAN.md and docs/UI_AND_CODE_CLEANUP_PLAN.md, then inspect the relevant code. Preserve existing projects and settings. Establish a reproducible baseline and make typed conversation independent of the live audio loop, with validated requests, lazy provider initialization and a shared authorization boundary. Keep the existing desktop contract working through an adapter. WhatsApp replies remain out of scope unless I specifically request them. Complete this bounded milestone, run meaningful checks and report the result and remaining limitations before expanding into other features.

The implementation model is a development choice. INARA's own local/cloud runtime models remain separately configured through the capability router, with dedicated speech, image and vision adapters where needed.
