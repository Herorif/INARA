# Settings and native lifecycle policy (R2b2)

Implemented 16 October 2026. Seven routes now have injected strict-schema transports: `get_settings`, `update_settings`, `get_tool_permissions`, `update_tool_permissions`, `set_resource_state`, `desktop_control` and `shutdown`. The [complete matrix](ROUTE_POLICY_MATRIX.md) records their current policy and the remaining R2b groups. The entire R2b milestone is not complete.

## Ownership and settings policy

`services/settings.py` owns validation, permission-name bounds, snapshots and atomic persistence. `transport/settings.py` owns owner/role/authentication checks and scoped delivery. `transport/lifecycle.py` owns typed resource/native/shutdown requests. `application.py` constructs these dependencies; `server.py` retains compatible method aliases and small explicit legacy media/settings-refresh/exit hooks.

Settings reads and writes require an authenticated renderer for the desktop owner. Native mode uses the existing registered native identity. Fallback/manual desktop mode pins the first successfully accepted connection's principal for the core lifetime, retaining it through disconnect/reconnect. Normal desktop clients use their stable UUID; manual development clients that need reconnectable administration must also supply a stable client UUID. Registering the native owner uses the existing native host registration flow and identity file, not a caller-supplied owner field.

This authorization is independent of editable tool permissions. A settings request cannot disable its own owner/role/face-gate check. The gate runs before a patch is applied; a locked renderer cannot turn face authentication off to unlock itself. Tray/control/foreign-owner channels cannot read or mutate settings. No administrative model tools were added. Local launch tokens and roles are still a trusted desktop contract, not Android device grants or strong face/OS authentication.

Patches accept only the existing face/camera booleans and tool-permission mapping. Values are strict booleans or the existing `deny` / `allow_within_scope` permission strings. Unknown keys, unknown tool names, extra identity fields, truthy strings/numbers and null updates are rejected. Known legacy settings-panel permission names are preserved until declaration consolidation at R2c. Existing unrelated configuration is retained; historical files are not automatically rewritten or migrated on startup.

The settings store serializes to a sibling temporary file, flushes/fsyncs it, then atomically replaces the configured settings file. In-memory settings commit only after save succeeds. Save failure preserves prior file/state and produces a sanitized scoped error. No mutable snapshot is returned to callers. The legacy `save_settings()` adapter now uses the same atomic writer. These settings retain their existing JSON format; this checkpoint does not turn them into encrypted credentials storage.

After a successful commit, the explicit compatibility hook refreshes active voice permissions or stops an existing face gate when disabled. If an integration refresh fails, settings remain saved and the error says a restart is needed; there is no claim to roll back an external integration. Accepted mutations refresh only the same owner's renderers; reads/errors go to their requesting SID. Face-gate changes emit the resulting auth status. The legacy settings panel waits for authoritative settings before changing its face/camera toggle state. Renderer socket startup also waits for native registration, preventing a first-launch settings-read race while the owner is still being registered.

## Lifecycle roles and cleanup

- Resource requests use `ResourceRequest` and serialized transitions. Unlocked owner renderers may select resource state. Trusted owner resident control can restrict/clean up while the optional face gate is locked. Native mode reserves the `native-resident` path for the actual host; another resident socket cannot impersonate it.
- Native identity gaming mode overrides renderer requests. The retained Electron fallback also latches manual resident-channel gaming so a renderer cannot silently lift it; the resident controller explicitly clears it. State updates go to same-owner channels instead of broadcasting across owners.
- Resident/gaming transitions close creative transports, cancel local-action requests and stop legacy audio/vision through the injected compatibility hook. All cleanup owners run even if one fails. A failed restricted transition retains the restricted governor state and reports failure. Hard isolation/deadlines for every legacy integration remain later work.
- Native control uses a strict discriminated action schema. Only the workspace channel for the registered owner may request state/close/quit/gaming; registration is allowed before the host has pinned its owner and the host validates it again. Gaming accepts a real boolean; unrelated fields are rejected. Owner native safety controls remain usable when the face gate is locked. Native control keeps its existing five-second host deadline and ACK shape.
- Socket `shutdown` is restricted to the fallback owner's resident channel. Renderers/control channels cannot stop the core through it; native mode uses its typed `desktop_control` quit path. Cleanup completes before the uvicorn exit callback runs. Failed cleanup does not report a successful exit. Native tray quit remains its existing independent safety path.

The native host no longer changes the governor before its validated resource handler runs. Its existing Python host, inherited-pipe credentials, Windows Job Object ownership, stable identity, reminder recipient/receipt and single-instance behavior are retained.

## Verification and limits

**288 Python checks pass; one existing real-Blender check remains skipped.** Sixty-six new R2b2 checks cover unauthenticated/foreign/locked/wrong-role calls, strict/malformed/escalating updates, permission compatibility, scoped snapshots, reconnect, real atomic persistence, save-failure rollback, native registration and locked cleanup, redacted failures, resource authority, gaming override/latch, shutdown ordering and cleanup failure. Previous policy/composition, protected persistence and actual CAD/scene/image fixture worker checks pass. Scoped Ruff and Python/Node syntax checks pass.

All **26 frontend checks** and the production build pass. Initial JS remains approximately 242 KB; the existing Vite CJS, Browserslist and large creative-chunk warnings remain. The settings toggle change is behavioral, with no new visual layout or hardware capability claim.

Actual isolated native verification now uses real socket clients to check settings persistence, compatibility permission mutation, malformed/wrong-role denial, scoped settings delivery and reconnect. Credentials reach the Node client only through stdin. A fresh-profile run verifies initial native owner registration before renderer hydration. It also passes busy-port recovery, close/reopen with the same identity, renderer crash cleanup, reminder receipt, gaming override and graceful core stop. The gaming test now assigns the renderer role and asserts the request was accepted, rather than passing because a request was ignored.

A short ten-second sample measured **66.72 MB mean working set / 49.48 MB peak private bytes**, including the venv launcher, with zero Electron processes after workspace close. This is not a replacement for the prior long idle baseline or the deferred real-game benchmark. The injected-crash scenario retains its existing bounded Engine.IO shutdown-timeout log. [Native verification evidence](qa/r2b2-native-verification.json). The retained Electron fallback's close/reopen, reminder receipt, gaming and explicit quit check also passes.

One initial full run saw the existing scene-worker test exit before validation. Its saved failure was `worker_failed`; the exact test passed in isolation and the subsequent sequential full run passed all 288 checks. No worker-runtime fix or root-cause resolution is claimed here; bounded worker exit diagnostics remain a follow-on concern.

No provider/model configuration, paid requests, real printer/device/app actions, real camera/face acceptance or real diffusion/Blender execution occurred. Existing camera/model/game acceptance limits and the exclusion of WhatsApp replies remain unchanged. Several other legacy routes still bypass the shared policy; the matrix labels them pending. This checkpoint does not authorize remote exposure.

## Next refactor

R2b3: migrate Kasa/printer compatibility in bounded groups. Start with strict discovery/control/printer-setup/profile schemas, role/owner checks and scoped responses using the existing dispatcher where an action permission applies. Printer file containment and slice/upload/start-print permissions need separate explicit decisions and tests; preserve their current data and useful adapters. No live network device/printer action or configuration change is required for implementation tests.

Then finish memory/media/legacy creative/browser routes, reminder receipt/role schemas, planner permission and legacy voice/event ownership. R2c schema/declaration/reference cleanup follows; it must not silently archive active `backend/core/` helpers.
