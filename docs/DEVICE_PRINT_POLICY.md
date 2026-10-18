# Device, printing and workflow policy checkpoint (R2b3)

Updated 19 October 2026. This combined batch follows R2b1/R2b2 and keeps the supported application root and existing socket event names. It does not complete every R2b route.

## Implemented boundaries

`DevicePrinterService` owns Kasa discovery/control and printer discovery/add/profile access. Strict inputs, authenticated owner renderer checks, shared denial/approval, atomic settings preservation, scoped responses and origin-disconnect/resource/close cancellation replace direct facade work. Kasa discovery preserves saved and offline entries. Manual printer setup preserves the selected endpoint and protocol without implicitly probing or changing it. Adapters and monitoring remain lazy.

`PrintService` binds an owner, captured project, UUID request and printer endpoint to immutable STL/profile snapshots. Inputs resolve inside the project, including junction/symlink checks; an exact installed slicer-profile catalog entry may also be copied into the project. STL/profile/GCode size limits are 50/2/100 MB. Original source, endpoint and hashes appear in stage approvals and are checked again after approval.

The root `print_stl` permission is followed by independent `slice_stl`, `upload_gcode` and `start_print` gates. Upload explicitly disables automatic print start. Internal stages are hidden from provider schemas and require the bound plan. The slicer runs in a fixed child worker owned by a Windows kill-on-close Job Object, with a 330-second deadline; upload/start have separate 35-second execution deadlines. Gaming/resource restrictions and application shutdown cancel the workflow. The creative slot is shared with CAD/images; there is no automatic queue.

A protected SQLite request ledger is written before effects. Exact completed duplicates return the saved result; conflicts are rejected. Stopped, preparing and uncertain requests do not replay, including after service restart. Upload/start cancellation or failure is conservatively uncertain: inspect the printer before making a new request. Successful HTTP acceptance does not establish physical print completion. Snapshots are retained; each owner/project is capped at 32 attempted requests pending a deliberate retention/export flow.

Separate start requests follow the official [Moonraker print-start API](https://moonraker.readthedocs.io/en/latest/external_api/printer/) and [OctoPrint file-selection API](https://docs.octoprint.org/en/main/api/files.html). HTTP contract checks use injected clients and do not contact printers.

Reminder reads/mutations/dismissals now require the authenticated desktop owner renderer. Receipt ACKs use a strict UUID schema; the trusted same-owner resident may ACK while the face gate is locked. Control channels cannot read, mutate or claim reminders. Receipt retry/idempotent completion and pending-origin cancellation remain covered. Scheduler-created events carry owner context.

`cad_plan` now dispatches `plan_cad` using the canonical `generate_cad` permission, with owner authorization, resource checks, approval and planner cancellation/deadlines. Alias denial cannot weaken the canonical permission. The UI allows time for approval plus execution. No provider was configured or called during verification.

## Verification and limits

Tests use injected Kasa/printer adapters, fixture STL/GCode bytes, a labelled fixed worker fixture and injected HTTP clients. They verify policy, ownership, snapshots, tampering, containment, cancellation and no replay, rather than printable geometry or slicer quality. Provider-visible schemas also pass conversion through the installed Google SDK without making requests.

The initial combined run exposed an intermittent real CAD worker failure. An isolated diagnostic worker reproduced `PermissionError` while replacing `progress.json` on Windows. Advisory progress replacement now tolerates that sharing failure; output writes and final validation still fail normally. A regression runs the actual worker body with every progress replacement denied and validates exported bracket volume/formats. All 30 CAD tests and the subsequent actual CAD desktop integration pass. The production image worker has the same progress-replacement pattern; apply and verify the same advisory-update hardening in a later image-worker cleanup.

All 26 frontend tests, scoped Ruff checks and the Vite production build pass. [Native evidence](qa/r2b3-native-verification.json) covers fresh owner registration, actual socket policy denials, lazy denied workflows, settings persistence, reminders, crash/reopen, gaming and graceful stop. Short idle measured 67.22 MB, zero Electron processes after close, and 0.312% of one CPU core over 10 seconds; this is not a gaming benchmark. Two preceding native runs timed out before completing fresh-owner checks; the passing run does not establish that timing issue is resolved. Timeout diagnostics now include role/workspace state.

[CAD desktop evidence](qa/r2b3-cad-verification.json) verifies actual box/bracket/enclosure exports, Three.js GLB import, scene operations, responsive widths, missing-key planner behavior and four worker exits; warmed resident recovery was about 66 MB. Two preceding CAD desktop runs failed before the progress fix. [Fallback evidence](qa/r2b3-fallback-verification.json) verifies close/reopen, reminder receipt, gaming and quit. Tests run locally; hosted CI has not run.

The final combined regression passes **377 Python checks**, with one Blender-dependent skip and one existing FastAPI/httpx deprecation warning. The same full command is recorded in `.github/workflows/lean-core.yml`.

No real network discovery, device control, slicing, printer upload/start, camera, paid provider call or phone action was performed. Installed profile inheritance, optional slicer dependencies, API-key printer setups, physical endpoint behavior and actual print quality need hardware acceptance. The root remains lean when these workflows are denied.

## Next batch

Migrate the remaining memory/media/legacy CAD/browser routes and unstamped legacy events through strict owned services. Preserve useful adapters and accepted UI payloads; cover direct and typed policy, request lifetime and disconnect behavior. Legacy AudioLoop device/printer paths still use their separate policy and old printer workflow; this checkpoint does not retrofit them. Consolidate declarations/references in R2c after those boundaries are established, then proceed to R3 UI/contracts work.

Provider setup and the real-game benchmark remain deferred. WhatsApp reply drafting/sending remains excluded until specifically requested.
