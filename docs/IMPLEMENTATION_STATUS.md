# INARA revival implementation status

Updated 13 October 2026. This records the first bounded milestone from [Implementation handoff](IMPLEMENTATION_HANDOFF.md). The broader [architecture](INARA_REVAMP_PLAN.md) and [JARVIS interface plan](UI_AND_CODE_CLEANUP_PLAN.md) remain the roadmap.

## Completed behavior

The supported `backend/server.py` now starts with the lean core environment and serves typed conversation without an `AudioLoop`, microphone permission, camera or voice connection. Google SDK clients initialize on a text request and are closed afterwards. `INARA_TEXT_MODEL` selects the text model; the initial default is `gemini-3.8-flash`.

Requests and results are validated and carry UUID conversation/request IDs. In-memory conversation history is scoped to the desktop client and project, with bounded storage and serialized turns. Duplicate request IDs return the prior result or error without replaying the provider work; conflicting payloads are rejected. Missing credentials, invalid input, provider failure and timeout have structured, sanitized errors.

Project file reading/writing and app launching use the common dispatcher. Arguments are validated, configured denials are enforced, approvals expire and are bound to the requesting client, and authorization is checked again before execution. File access rejects traversal, absolute/drive/UNC paths and alternate-data-stream syntax, resolving existing symlinks/junctions before containment checks. Voice file operations use the same containment rule.

Temporary projects are preserved on startup. Due reminders transition out of pending state before notification, preventing the repeated ten-second emission in the old loop. Full transactional reminder delivery, recurrence/timezone policy and crash recovery remain a later milestone.

Optional audio, camera, CAD, browser, Kasa and printer implementations are imported on demand. Printer hydration/monitoring starts on printer or voice activation; semantic camera watches run when requested frames and watches are present. The FastAPI lifespan owns background-task cleanup. Legacy socket names remain available through the supported server.

The desktop supplies stable client identity and, when Electron owns the backend, a random launch token. Explicitly configured manual-development tokens are supported. Allowed browser origins are restricted. The chat input shows processing/disconnected states, and duplicate typed response events do not append the same reply twice. The development command now sets `INARA_DEV_SERVER=1` correctly.

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

The new typed tool path currently exposes project files and configured app launching. CAD, image generation, local speech, Android and telephony are not implemented through that path yet. Some legacy direct handlers still require migration to the shared policy service, and the legacy voice dispatcher remains separate. This is a local desktop milestone, not a remotely exposed automation service.

Conversation history is bounded in memory rather than durable across backend restarts. Full device pairing, scoped persistent credentials, encrypted storage, worker isolation and the resource governor remain planned. The legacy face-landmark gate is retained for compatibility and does not become strong OS authentication through this change.

The complete JARVIS UI redesign, responsive workspace, lazy 3D/camera loading and supported Electron upgrade remain subsequent work. WhatsApp reply drafting and sending are excluded until specifically requested; no automatic replies were added.

## Next milestone

Implement transactional reminders and durable recoverable project/conversation sessions, then separate the resident assistant lifetime from the desktop window. Establish JARVIS design tokens and the responsive workspace shell before migrating the creative workers. Reuse this checkpoint and the verified core instead of repeating the repository audit.
