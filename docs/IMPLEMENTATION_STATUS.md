# INARA revival implementation status

Updated 14 October 2026. This records the completed core/persistence milestones, JARVIS workspace and native resident follow-up from [Implementation handoff](IMPLEMENTATION_HANDOFF.md). Read [Persistence](PERSISTENCE.md) for storage, migration and recovery contracts. The broader [architecture](INARA_REVAMP_PLAN.md) and [JARVIS interface plan](UI_AND_CODE_CLEANUP_PLAN.md) remain the roadmap.

## Completed behavior

The supported `backend/server.py` now starts with the lean core environment and serves typed conversation without an `AudioLoop`, microphone permission, camera or voice connection. Google SDK clients initialize on a text request and are closed afterwards. `INARA_TEXT_MODEL` selects the text model; the initial default is `gemini-3.8-flash`.

Requests and results are validated and carry UUID conversation/request IDs. Durable encrypted conversation history is scoped to the desktop client and project, with bounded restored context and serialized turns. Duplicate request IDs return the prior result or error without replaying the provider work; conflicting payloads are rejected. Missing credentials, invalid input, provider failure and timeout have structured, sanitized errors.

Project file reading/writing and app launching use the common dispatcher. Arguments are validated, configured denials are enforced, approvals expire and are bound to the requesting client, and authorization is checked again before execution. File access rejects traversal, absolute/drive/UNC paths and alternate-data-stream syntax, resolving existing symlinks/junctions before containment checks. Voice file operations use the same containment rule.

Temporary projects and the selected project survive startup. Reminder claiming, schedule advancement and occurrence records commit together; leased delivery retries retain their IDs, and authenticated receipt/completion survives restart. Legacy reminder, routine and project chat migration preserves originals and encrypted snapshots. UTC/IANA recurrence and missed-occurrence policy are documented in [Persistence](PERSISTENCE.md).

Optional audio, camera, CAD, browser, Kasa and printer implementations are imported on demand. Printer hydration/monitoring starts on printer or voice activation; semantic camera watches run when requested frames and watches are present. The FastAPI lifespan owns background-task cleanup. Legacy socket names remain available through the supported server.

The native desktop supplies stable client identity and a random launch token over an inherited pipe and trusted preload IPC. Explicitly configured manual-development tokens are supported. Allowed browser origins are restricted. The chat input shows processing/disconnected states, and duplicate typed response events do not append the same reply twice. The development command sets `INARA_DEV_SERVER=1` correctly.

## Development baseline

A local Git repository and pre-change checkpoint were created: `db88277`. Existing settings, keys and project data remain outside source control. Python 3.12.10 and checksum-verified portable Node 24.21.0 were used locally. Core and development dependency versions are recorded in separate lockfiles. The original full `requirements.txt` remains the optional legacy-feature installation path.

Use `scripts/bootstrap.ps1 -Dev` for the reproducible environment and frontend build. If the normal npm registry cannot establish a valid TLS connection, `-Registry https://registry.npmmirror.com` selects the mirror explicitly while preserving npm integrity checks. No global registry setting or disabled TLS validation is required.

`scripts/start.ps1 -BackendOnly` starts the lean backend. `scripts/start.ps1 -Dev` starts the development desktop, and `scripts/start.ps1` opens the built desktop once Electron's executable is installed. AI responses require a valid `GEMINI_API_KEY` in `.env`.

## Verification

- 31 deterministic checks passed across the new conversation tests and the retained desktop runtime smoke tests.
- Covered independent text responses, credentials and invalid requests, provider failure redaction, conversation/project ownership, duplicate IDs, real SDK schema conversion and tool signatures, permission denial, approval owner binding/expiry, path escape rejection, temporary-artifact preservation, startup and cleanup, and the legacy event contracts.
- Ruff checks passed for the new services and milestone tests. Python dependency compatibility checks passed.
- The Vite production build passed, transforming 2,054 modules. The existing large single JavaScript bundle remains a performance issue for the planned UI/lazy-loading milestone.
- Changed desktop and transport JavaScript passed Node syntax checks.

The npm download initially failed certificate validation on the primary registry connection. Installation succeeded through a TLS-verified mirror with the checked-in lockfile's integrity checks. The build required execution outside the sandbox because esbuild's parent-directory resolution was denied inside it.

No paid AI requests, real app launches, camera sessions, printer actions or phone calls were used in verification. Electron's executable was installed separately after the frontend build-only dependency install; the native desktop window has not been visually verified. Optional legacy audio/CAD/device libraries and current provider-model compatibility still need their own integration tests. The Windows CI workflow is configured but has not run on GitHub.

## Remaining boundaries

The new typed tool path exposes project files, configured app launching and validated local reminder tools. Direct snooze/cancel also uses the common dispatcher. CAD, image generation, local speech, Android and telephony are not implemented through that path yet. Some legacy direct handlers still require migration to the shared policy service, and the legacy voice dispatcher remains separate. This is a local desktop milestone, not a remotely exposed automation service.

Completed typed history and its request ledger are durable and encrypted before SQLite/WAL writes. Restored context is limited to twenty completed messages. Windows DPAPI is user-bound; portable export, full device pairing, scoped persistent credentials, worker isolation, retention controls and the resource governor remain planned. Legacy voice histories remain a separate adapter; existing settings and artifacts retain their original formats. The legacy face-landmark gate is retained for compatibility and does not become strong OS authentication through this change.

The command deck, responsive workspace, local reminder panel, lazy 3D/camera loading and resident close/reopen are implemented. Electron is now pinned to 44.7.0 and runs only while a workspace is open; the native host replaces its resident overhead. Optional adapter interiors and creative worker isolation remain subsequent work. WhatsApp reply drafting and sending are excluded until specifically requested; no automatic replies were added.

## Next milestone

Implement the isolated CAD/Blender worker and typed artifact preview/export contract, preserving the native resident lifetime, protected sessions, reminder ownership and responsive JARVIS command deck. Keep API configuration deferred. See [native host evidence and remaining release checks](NATIVE_RESIDENT.md). The user deferred the real-game benchmark; it remains pending rather than a blocker for the next bounded capability implementation.

## Second milestone verification (13 October 2026)

- Versioned encrypted SQLite user data, request ledger, project selection and reminder delivery are implemented without API configuration.
- 56 Python checks pass, covering both milestones, Windows DPAPI round trips, protected database/backups, migration validation/rollback, session restart without tool replay, uncertain requests, concurrent services/pollers, transport failure, acknowledgements, stale alert edits, cancellation/snooze, timezone filtering and DST recurrence.
- Two Node state tests pass for simultaneous alert queueing, duplicate deliveries and reconnect snapshots. The production Vite build passes. Ruff and dependency consistency pass.
- Tests use temporary user data, fake providers and fake transport. No production data migration, paid requests, phone/device actions or native desktop visual verification was performed. The build still reports the existing large bundle, old browsers data and Vite CJS warnings; the JARVIS/lazy workspace milestone will address the frontend structure.
- The local desktop recipient rule does not implement Android delivery ownership or pairing. Closing the current desktop shell still stops its backend; resident lifetime is next. WhatsApp replies remain excluded.


## Resident and JARVIS workspace verification (13 October 2026)

The command deck and resident lifecycle foundation are implemented, including tray/hotkey reopen, explicit graceful quit, generic resident reminder notices, gaming suppression/gating, responsive command/Studio/connections views, local reminder creation and deferred camera/landmark loading. Source modules are separated by lifecycle and feature responsibility.

61 Python checks and eight Node checks pass, along with lint, dependency consistency and production build. Hidden renderer tests verify 1440, 768 and 390 CSS-pixel layouts, modal behavior, icon labels and absence of heavy startup assets. Rendered screenshots are in [docs/qa](qa/command-desktop.png). Native close/reopen uses the same backend and verifies reminder receipt, gaming state and graceful quit with fresh isolated data. Notification display is stubbed. Bundled tracking initialization passes with an empty test stream; no real camera or paid provider is used.

Initial JavaScript is approximately 241 KB uncompressed / 76 KB gzip; CAD is a separate approximately 902 KB chunk. The immediate resident snapshot retained roughly 400 MB of Electron working sets; the 150 MB resident target is not met, and a ten-minute idle/game benchmark is outstanding. The implementation is a functional foundation, with resident footprint reduction explicitly remaining open. Details and limits are in [Resident and workspace](RESIDENT_AND_WORKSPACE.md).

## Native resident follow-up (13 October 2026)

The default Windows host now runs Win32 tray/hotkey and the ASGI core in one Python process, with Electron solely for an open workspace. It preserves the old profile/identity, transfers credentials by pipe/IPC, owns the entire workspace tree through an atomic Windows job, delivers scoped reminders directly and treats native gaming selection as authoritative. Startup/registration timeout, busy-port failure and tray retry are implemented. The older Electron host remains an explicit fallback.

69 Python and eight frontend checks pass. Electron 44.7.0 passes hidden responsive UI/tracking initialization and the retained fallback lifecycle integration. The final ten-minute run, including the owned Python launcher, averaged 64.86 MB working set (65.30 MB peak) at 0.3802% of one CPU core, with 47.54 MB peak private bytes and no resident Electron processes. First workspace open/reopen took 2.516/2.188 seconds after core readiness. Busy-port retry, workspace crash cleanup and graceful quit pass. Final combined-process evidence, acceptance limits and the deferred game benchmark are recorded in [Native resident](NATIVE_RESIDENT.md). The earlier approximately 400 MB Electron measurement above is historical.
