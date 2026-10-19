# Web inspector and adapter cleanup

Implemented 19 October 2026. This is the completed read-only research milestone. Interactive browser control, arbitrary desktop sequences and real device acceptance remain future work.

## Behavior

Studio > Web inspector opens a responsive JARVIS-style research panel. Enter one explicit public HTTPS URL and review the existing `run_web_agent` permission request. The service retrieves one page, returns bounded inert text and up to 30 addresses, then exits. Discovered addresses are displayed as text; each new inspection requires another explicit request. No scripts, browser profile, cookies, credentials, form submissions, model inference, automatic link following or account actions are enabled.

The retired `prompt_web_agent` and `run_web_agent` compatibility names fail closed with migration guidance. Both old WebAgent imports reject construction. The old implementation's automatic safety acknowledgement and autonomous computer-use loop are removed, and the retired prompt tool is no longer advertised to the conversation model. Existing permission settings remain in place. Other unmetered legacy paths retain their usage-cap guard.

## Boundaries and ownership

`BrowserInspect` is a generated strict Pydantic/TypeScript contract accepting only `url`. `BrowserTransport` accepts only the authenticated desktop owner renderer, captures the current project and origin SID and dispatches through shared permission/approval policy. ACK results belong only to the requesting renderer. One inspection runs at a time. The shared permission is rechecked after approval, and owner authorization is checked again before returning results.

`BrowserService` launches a fixed GET-only worker through the existing Windows kill-on-close process job. It receives only the explicit URL and a task-owned staging directory, with filtered environment inheritance and no credential bootstrap. There is a 25 second worker deadline, 30 second dispatcher execution deadline and 60 second approval deadline. Cancel also stops pending approvals; origin disconnect, resource restriction, panel/project close and application shutdown cancel owned work. No reconnect replay or automatic retry is added. Staged reports are size/schema checked and removed on every owned exit path; UI results are ephemeral and cleared on project change/disconnect/close. Forced OS/power termination can leave ephemeral staging files; there is no persistent browser history or crash-recovery guarantee.

URLs must use HTTPS on port 443 without credentials, fragments, IP literals or local/internal suffixes. Every request resolves DNS, rejects private/mixed/special addresses, and pins the checked numeric address while retaining TLS hostname verification. No proxy environment is consulted. Redirects are revalidated and limited to three hops within the original hostname. Only status 200 uncompressed HTML/plain text is accepted, at most 512 KiB; text is limited to 12,000 characters and title to 240. Binary content is rejected. Cookies/authentication are never forwarded. GET-only retrieval does not guarantee the remote server has no side effects.

HTML is parsed without rendering or executing it. Hidden script/style/template content is omitted; extracted page text remains explicitly untrusted. React renders it as text; no HTML injection, provider context, instructions, tool calls or automatic actions are derived from page content. This is an HTTP text inspector, not a full DOM browser or an OS sandbox. JS-only, non-UTF-8, compressed-only, authenticated and cross-origin-redirect sites may be unsupported. Live public websites have not been exercised in this milestone.

There are no provider calls, so inspections do not consume cloud allowances or create provider-token receipts. Adding any AI planning or page summarization later requires shared usage admission for every provider step and explicit untrusted-content treatment; this milestone does not lift legacy cloud guards.

## Device separation

`PrinterMonitor` now owns observation independently from setup, endpoint persistence, Kasa control and the print pipeline. It starts only on explicit printer setup/discovery, checks owner authority and renderer presence before each poll and after each result, and drops results after authority loss. Last-owner-renderer disconnect, resource restriction and application close release it. A sibling owner renderer preserves it. No startup discovery, real printer polling/control, device configuration or dependency installation was performed. Further Kasa/printer protocol decomposition and physical acceptance remain pending.

## Acceptance

- Supported regression: **954 Python passed, one installation-dependent Blender skip; 83 Node passed**.
- Type checking, generated-contract drift, Ruff, production UI build and diff whitespace checks passed. Existing build chunk-size/Browserslist and Starlette deprecation notices remain.
- Tests use synthetic HTTP/DNS/TLS adapters for GET-only behavior, redirect/private-network rejection, size/type bounds, inert hostile text and TLS address pinning. Identity, denial, pending-approval cancellation, busy/SID separation, disconnect/no replay, report validation/staging cleanup and observation lifecycle are covered.
- `scripts/verify-browser.py` passed using the actual hidden native renderer, an isolated synthetic page adapter and the real fixed worker bootstrap/output path with a QA-only offline fetch adapter. The worker fixture forbids network access. No public website, provider or real user data was used. No hosted CI run is claimed.
- Screenshots were visually inspected at 1440 and 390px. Native short resident samples were **65.34 MB before workspace / 67.27 MB after exit**; tasks were released, no heavyweight model/browser SDK was imported into the resident and the mobile listener stayed off. This is not a real-game benchmark or a long-run performance guarantee.

Evidence: [desktop](qa/browser-desktop.png), [390px](qa/browser-390.png), [empty state](qa/browser-empty-desktop.png), [sanitized native report](qa/browser-verification.json).

## Next implementation

Build a reviewed desktop task queue on top of existing typed dispatcher operations: bounded plans, captured owner/project scope, per-step approval, durable non-replayable step receipts, progress/cancel UI and disconnect/restart recovery that never silently resumes effects. Page text must never become a task plan without explicit user review. Keep browser interactions and AI planner/provider calls disabled until their contracts, per-call usage admission and action-specific review are implemented. Continue network adapter separation using fixtures; hardware acceptance stays separate. Android tooling/device acceptance, self-contained signed distribution and update rollback remain release work. WhatsApp reply/call actions remain excluded.
