# Usage budgets and quality evaluations

The second post-revamp source milestone adds a responsive Usage & quality dashboard, shared cloud admission allowances, provider-reported token receipts, local creative-job duration receipts and an explicit offline product-contract suite. It does not configure providers, install models/tools, quote current model prices or make paid requests.

## Use and budget meaning

Open **Usage & quality** from Command quick launch or the command palette. The default is **Monitor only**. Supported calls record usage metadata without enabling a spending policy or changing provider setup. The dashboard distinguishes owner-wide daily/monthly totals from the current project's latest 50 receipts for this month.

Review budget sets integer micro-USD allowances, daily/monthly limits and a per-call output-token limit. One USD is 1,000,000 micro-USD; decimal input accepts at most six places and never uses floating point for budget arithmetic. Enabling requires a positive per-call allowance. A zero daily or monthly limit deliberately blocks new cloud admissions.

These are **owner-chosen INARA authorization allowances, not provider prices, measured dollars billed or a guaranteed invoice ceiling**. A fixed allowance is reserved before every supported provider invocation, including each conversation tool-loop step. Daily/monthly limits reject an invocation before the provider's generate call if its allowance would exceed either limit. Separate provider billing controls and later price/invoice calibration remain necessary for invoice-level acceptance. No price table or inferred zero-cost claim was introduced.

The full allowance remains consumed after completion, timeout, cancellation, missing usage metadata or an ambiguous provider failure. It is never automatically refunded based on a guessed token price. Limits therefore conservatively govern how many authorizations INARA grants under the chosen allowance. Lowering a policy never erases previously admitted usage. Changing/turning off caps does not reset totals. Already admitted work is not retroactively cancelled or made bounded by a newer policy.

UTC periods are evaluated at atomic admission, with a persisted clock high-water mark preventing a small backwards clock adjustment from reopening an older budget period. Larger backwards changes block cloud accounting until corrected; local tools remain available. Calls admitted before midnight belong to that admission period even if their response arrives in the next period. This is not a provider billing-calendar reconciliation.

## Covered paths and safety boundaries

| Path | Accounting |
| --- | --- |
| Desktop typed and reviewed-speech answers | Every shared conversation provider step, with original request reference and provider-step number |
| Approved tool-free phone chat | Charged to the paired desktop owner's same global budget; no mobile budget-management route |
| Typed CAD blueprints/change proposals | Shared dispatcher binds a scoped accounting operation around the fixed planner; existing owner approvals/resource checks remain |
| Transcription | Actual SDK streaming call is admitted first; final reported metadata is recorded without treating missing stream counters as zero |
| Local CAD/image workers | Scoped job reference, state and measured duration; no cloud allowance charged; existing CPU/RAM/worker admission stays authoritative |

SDK calls in the supported Gemini adapter disable automatic retries. Tool responses remain under INARA's existing dispatch/approval path; SDK automatic function execution is disabled. Capped calls set the configured output-token maximum. This bound does not turn an owner-assigned dollar allowance into a verified invoice maximum. Provider input, output, thinking, cached, tool-prompt and total token counts are whitelisted when reported. Missing or invalid counters stay unknown, and subtotals are not blindly added as if billing categories were disjoint. The [official token-usage documentation](https://ai.google.dev/gemini-api/docs/generate-content/tokens) explains the reported counters.

Legacy cloud browser/generated-code/vision/live-media adapters are not represented as metered. Enabling caps blocks their shared tools and compatibility aliases before execution. Active legacy work, old media sessions and watches must stop before enabling caps. Monitor-only totals describe supported metered paths, not a claim that uninstrumented legacy activity was free. Local reminders, files, project memory, offline CAD/image work and safety controls remain usable. Future cloud adapters must join the meter before being allowed under caps.

Only the unlocked pinned owner renderer can inspect or change policy. Policy edits require the captured revision. No model budget-management tools, phone permissions, WhatsApp actions or call answering were added. Pairing, grants, protected memory/conversations, approvals and resource rules remain separate authorities.

## Durable ledger and privacy

Policy/rollups and scoped invocation/job receipts use the existing user-bound DPAPI SQLite store. Cloud admission writes its receipt and increments owner-wide counters in one transaction before network work. Concurrent requests across projects/channels cannot each spend the same remaining allowance. A duplicate provider-step receipt rejects replay within its admission month; conversation/phone request ledgers additionally retain their own durable request deduplication. Direct planner requests remain deliberate new operations, not a new retry/outbox feature.

On restart, unfinished receipts display uncertain and retain their allowances. Receipt metadata contains feature/model, project scope, request reference, state, timestamps, counters and duration. It contains no prompt, reply, microphone payload, API key or raw provider error. Current-month reads are bounded to 4,096 cloud receipts and 50 displayed rows. Hitting that admission capacity stops new cloud calls. Daily rollups retain 62 period entries and monthly rollups 24; older receipt documents remain encrypted historical metadata, not a promised automatic purge. No refund/reset/delete-budget endpoint exists.

Local usage receipt persistence is secondary to actual job history: a receipt failure does not discard an existing artifact, change a worker's outcome or prevent resource release. No usage poller, SDK connection or model starts merely because the assistant is resident.

## Offline evaluations

**Run offline checks** starts one fixed Python worker with an inherited pipe bootstrap and a Windows kill-on-close Job Object. It uses a newly created, checked workspace-owned temporary directory, an isolated encrypted profile, synthetic notes/recipes and injected providers. Credentials are excluded from the inherited environment; the worker installs a Python socket audit guard and does not start the server/listener. Its fixed cases accept no user script, URL, selected file or arbitrary command.

The 20-second deadline, Stop checks, panel closure, origin disconnect and core shutdown stop the owned process tree. Cleanup only removes the exact checked disposable directory. Latest reports are protected and owner/project-scoped; stale panel acknowledgements are dropped and runs are never replayed automatically.

Suite version 1 has 12 explicit pass/fail cases:

1. Assistant response and durable request deduplication.
2. Permission denial without opening the requested file.
3. Memory consent and project isolation.
4. Shared owner budget admission across channels.
5. Box volume and binary STL consistency.
6. Bracket volume.
7. Open-enclosure volume.
8. Typed scene transforms, bounds, volume and names.
9. Unsupported geometry rejection.
10. Synthetic PNG dimensions, CRCs and decoded pixel size.
11. Wrong image-size rejection.
12. Production rejection of fixture provenance.

Expected CAD quantities and artifact checks are independently specified; image pixels are synthetic, not diffusion output. Reports carry `fixture_only=true`, `provider_used=false` and `model_quality_verified=false`. The UI does not turn green fixture results into claims about real model accuracy, creativity, image quality, provider latency or engineering-kernel support.

The same suite is available without opening the UI:

```powershell
.venv/Scripts/python.exe scripts/evaluate-quality.py
```

A failed case produces a failed report and nonzero CLI exit. Hosted CI wiring includes the suite and new tests; no hosted run is claimed.

## Verification and remaining work

Final regression checks passed **911 Python tests with one Blender skip and all 78 Node tests**, plus types, generated-contract drift, Ruff, the production build and all 12 offline cases. Native evidence is recorded under docs/qa/usage-quality-*. No hosted CI run is claimed. Deterministic checks cover atomic reservations, shared budgets, policy revisions, midnight/month boundaries and clock skew, restart/uncertainty, duplicate steps, cancellations, unknown counters, SDK retry/output controls, transcription streams, phone scope, legacy guard aliases, local jobs and owned quality-worker cancellation. Native acceptance uses arbitrary fixture amounts and a synthetic provider to prove the second call is denied before generation, renders desktop/390px views, runs all 12 checks and releases the evaluation/workspace/core processes.

Provider pricing/invoice reconciliation and representative real-model quality/latency evaluations remain deferred until configuration is chosen. Android build/device acceptance, signed standalone packaging/update recovery, real media/creative/device acceptance and the real-game benchmark remain open under their existing deferrals. Next source implementation: owned browser/desktop automation and device-adapter cleanup, preserving these meters, approvals and process ownership.


Final native fixture acceptance passed: default monitor-only, explicit policy, one admitted call, second-call denial before provider generation, reported token counters, all provider instances closed, all 12 checks passed, evaluation child/workspace released and graceful core shutdown. Desktop/390px screenshots were visually reviewed. Resident working set was about 65.2 MB before opening and 68.0 MB after closing, with no heavy model modules and the mobile listener off. This is a short fixture observation, not a long-run Legion/game benchmark.
