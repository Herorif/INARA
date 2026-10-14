# Route policy migration: R2b1

Implemented 14 October 2026. This is the first bounded group within R2b; the whole milestone is not complete. The [route matrix](ROUTE_POLICY_MATRIX.md) and [machine-readable inventory](ROUTE_POLICY_MATRIX.json) cover 52 socket routes, `/status`, 15 shared tools and 26 separate legacy voice declarations. A regression check compares actual registered route/tool names, shared runtime schema names and legacy declaration names against that inventory.

## Implemented behavior

Seven direct actions now share validated tool execution with typed model calls: `launch_app`, `take_screenshot`, `read_clipboard`, `get_system_info`, `list_all_devices`, `control_device` and `stop_watching`.

`services/local_actions.py` owns strict finite request schemas and lazy desktop/device/vision adapters. `transport/local_actions.py` owns renderer identity checks, approval requests, scoped results/errors and request cancellation. Registration moved out of the legacy server, which retains compatible method names. No lazy adapter loads before schema/auth/policy checks and approval. The application composition root owns both boundaries; extracted code does not import `server`.

Direct calls require a connected, authenticated renderer. Invalid payloads, extra fields, coercible brightness booleans, unsupported actions and blank required names are rejected before adapter execution. Existing tool policy semantics are preserved: `False` / `allow_within_scope` allows within scope; `deny` rejects; `True` / missing policy requires owner approval. Tool names and request/result events stay compatible with existing panels. These seven tools are also registered in the typed conversation dispatcher; their legacy voice counterparts remain separate pending migration.

`confirm_tool` now checks renderer role/authentication and a strict ID/boolean schema before accessing either confirmation path. The shared dispatcher still binds approvals to the principal, expires them and rechecks authentication/disablement before execution. Voice fallback confirmation remains a mapped legacy seam; strict input/role validation does not establish per-session voice approval binding.

The transport tracks requests by their originating channel. Disconnect cancels that channel's pending approval/execution without cancelling another channel's requests, and application shutdown cancels all tracked local requests. A disconnected approval ID cannot be resolved later to replay the action. Direct actions do not gain durable idempotency through this checkpoint; a new explicit request remains a new action.

New local ToolSpecs opt into a 30-second cooperative execution deadline; existing creative/file/reminder specs retain their lifetimes. Cancellation/deadlines stop awaited Python work, but cannot undo an app launch/device change already made or forcibly terminate a synchronous operation or executor thread. Timeout text asks the owner to check state before retrying. Hard process isolation and worker reservations remain R4. No automatic retries were added.

## Event ownership

`Event` captures an optional trusted principal from a ContextVar at construction. Local adapters set/reset that scope around execution, so events scheduled with `emit_nowait` retain the correct owner even after the action returns. `EventDelivery` sends stamped events only to the authenticated owner's renderer channels, excluding other owners, tray and workspace-control channels. Direct result/error events use the originating SID.

Unstamped producers still use the explicitly inventoried legacy bridge and may broadcast. Payload fields cannot set the trusted event scope; the new schemas reject caller-supplied owner/project keys. The selected project is still desktop-global; request snapshots and persistent service owner/project checks are retained. This is not a mobile authorization protocol.

## Verification

**222 Python checks pass; one existing real-Blender check is skipped.** This includes 61 new policy checks across all seven actions: unconnected/locked/wrong-role rejection; direct/model denial and malformed-input parity; successful direct contracts; actual-boolean confirmation validation; owner-bound approval, double resolution and post-approval disablement; expiry/disconnect without replay; scoped delayed agent events; cooperative execution timeout; sanitized unexpected failures; and complete inventory/schema coverage. Existing isolated composition, persistence, CAD/scene/image worker and legacy smoke regressions pass.

All **26 frontend checks pass** and scoped Ruff checks pass. No frontend source changed and no new visual design or build outcome is claimed for this backend checkpoint. Existing UI event payloads were checked against the desktop/device/confirmation panels. New device/desktop action tests use injected agents, not real apps, screenshots, clipboard content, cameras or hardware. Actual OS/device capability acceptance remains separate.

Actual native verification passes busy-port recovery, same-identity close/reopen, hotkey-message reopen, renderer crash cleanup, reminder receipt, gaming guard and graceful core stop. A short 10-second sample measured **65.61 MB mean working set / 47.97 MB peak private bytes**, including the venv launcher, with zero Electron processes after close. This is not a new long idle or gaming benchmark. The injected-crash case retains the existing bounded Engine.IO shutdown-timeout log. [Recorded native evidence](qa/r2b1-native-verification.json).

## Next implementation: R2b2

Migrate settings/permission mutation and native/resource lifecycle routes. These currently include unauthenticated direct settings changes, unrestricted connected-role controls and broad settings/state broadcasts; they are marked pending/partial in the matrix. Add strict schemas, renderer/native role and owner checks, scoped errors/responses, and an explicit settings policy that cannot be bypassed by changing its own permission gate. Preserve native token/identity, reminder receipt, explicit quit and gaming override. Use injected feature transports rather than adding a second runtime.

Then migrate Kasa/printer compatibility, memory/media/legacy creative/browser routes; finish receipt schemas, planner permission, legacy event producers and voice confirmation binding. R2c declaration/reference cleanup follows. Provider/model setup, physical camera/hand accuracy, real diffusion/Blender execution, real-game benchmarking and WhatsApp replies remain deferred or unverified as previously recorded.
