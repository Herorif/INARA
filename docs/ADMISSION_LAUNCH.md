# Renewable authorization and guarded resident launch

Implemented 22 October 2026. The trusted controller now prepares unsigned launch-grant requests, reviews/applies externally signed grants and launches a selected version under a lifetime guard. Both checked-in production policies remain disabled. No actual production grant, signing identity, installation or resident was configured by this milestone.

## Explicit renewal of exact installed bytes

`scripts/admission.py` introduces a separate `INARA:installation-launch-grant:v1` signing domain. The closed statement binds canonical installation root, installation ID, selected slot, exact package manifest/attestation hashes, external release and Windows policy hashes, package sequence, grant number, previous grant hash and UTC issue/expiry. Publisher and reviewer thresholds use the existing independently pinned production public-key policy. Unknown/revoked/duplicate signers, missing roles and invalid signatures refuse. The whole grant window must fit each contributing signer's enrollment window, with a maximum of 30 days. The default unsigned request asks for 24 hours; it never signs or admits itself.

A new signed grant deliberately reauthorizes the exact retained package after its original one-hour window expires. Original package signatures, approved review ledger and exact installed inventory are still verified, with the original signature checked at its signed issuance time. Current authorization comes from the **new** grant's signatures and live validity, not from silently ignoring expiry on the old launch-check path. Renewal can occur after the previous grant has expired, but requires fresh external signatures. Fixture/disabled policies, missing admission evidence and unsigned requests cannot authorize launch.

Unlike the prior local receipt metadata, the grant cryptographically binds root and installation ID to the authorized slot and source hashes. It does not sign all installation metadata, private profile contents, settings, Windows ACLs or filesystem metadata. Owned profile markers and recovery compatibility are separately checked; no profile is adopted or migrated.

## Review, commit and replay boundary

`prepare-grant` writes only a new external request directory. `review-grant` checks the signed input, current source/profile and Windows signatures, returning a digest binding the exact grant bytes, previous head, installation state, profile path, number and sequence. `admit-grant` requires that exact review, rechecks under the manager lease and commits the retained grant before atomically replacing its local head pointer. Neither operation selects a version or launches anything. Native trust/cache failures refuse admission.

Grant history is retained at `authorizations/<raw-grant-sha256>.json`, with `authorizations/state.json` as the current pointer. A renewal must name the exact previous grant, increment its number by one and keep package sequence and issue time from moving backwards. An interrupted pointer commit can reuse only an identical complete orphan grant; partial or conflicting evidence refuses and remains retained. No signing key or new local secret is created.

Every operation requires an external expected head. Use `new` only for initial enrollment when no local head exists. After admission, retain the returned `expected_head` through an independently trusted route and supply it for launch/renewal. Replaying a prior grant or restoring an old local pointer refuses against that latest pin. The editable local pointer is **not a hardware monotonic counter**: accepting a stale externally supplied pin or deliberately restarting with `new` after deleting state weakens that premise. Automatic durable pin storage, policy rotation, atomic signed version updates and explicit signed downgrade authorization remain future work. This milestone does not globally constrain legacy unsigned management paths.

## Process lifetime

The new `launch` command validates the externally pinned grant before traversing application files. It takes Windows read handles denying writes/deletion on the installed payload, retained evidence, external policies, installation/head metadata and profile ownership markers. It then rereads trust/state and verifies exact payload bytes, historical package signatures/reviews, current profile binding and current cache-only native signer/timestamp checks before execution. The manager lease remains held throughout the resident lifetime; selection, recovery and renewal through the manager refuse while it is busy.

The controller starts only the selected slot's `runtime/python/python.exe -I -B backend/resident_main.py`, with optional `--resident-only`. It constructs owned profile paths and removes Python path/home overrides, the dev-server override and Electron-as-Node mode. Arguments use Windows argument quoting, with no shell or payload-provided installer/validator. Private settings/data remain writable; program files remain leased.

`scripts/windows-launch.py` creates the process suspended, assigns it to a Job Object with kill-on-close and no breakaway permission, rechecks expiry, then resumes it. Assignment failure terminates the suspended process without running application code. Normal exit, guard failure and controller death close the job and terminate remaining descendants. While running, the guard checks expiry every 250 ms subject to OS scheduling and terminates the job when the grant expires. Nonzero resident exit propagates as a failed controller command. See Microsoft's [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects) and [CreateFile sharing rules](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew).

The Job Object is a lifetime boundary, not a security sandbox. Trusted clock, OS and controller delivery remain assumptions; these leases do not prevent a compromised privileged account from injecting code or adding new directory entries. There is no general claim of isolation from arbitrary same-account attackers. Actual Electron sandbox/nested-job behavior, native UI lifetime and real certificate/cache conditions still require owned production/clean-machine acceptance. The existing unsigned Setup/CLI remains a separate owner-operated path. `launch-check` retains its earlier read-only, one-hour-source contract and is never reused as an execution permit.

## Commands

Run through the independently trusted bootstrap and external controller inventory pin, using explicit owner-enrolled policies. These placeholders refuse against the checked-in disabled policies.

```powershell
# Common arguments: --root, --policy, --expected-policy, --windows-policy,
# --expected-windows-policy, --sequence. All trust inputs live outside the root.
controller prepare-grant <common arguments> --expected-head new --hours 24 --output C:/new-request
# External publisher/reviewer sign the exact request bytes in the new domain.
# Envelope shape: {"statement": <exact statement.json>, "signatures": [{"key_id": ..., "signature": ...}, ...]}
controller review-grant <common arguments> --expected-head new --grant C:/signed-grant.json
controller admit-grant <common arguments> --expected-head new --grant C:/signed-grant.json --expected-review '<review digest>'
# Retain the returned head independently, then launch with that pin:
controller launch <common arguments> --expected-head '<current grant hash>' --resident-only
# Stop the resident before preparing/admitting a renewal; use the current hash
# instead of `new` for BOTH the new request and review/apply.
```

Here `controller` means the fixed `scripts/controller.py` entry through `scripts/open-trusted-controller.ps1`, not a newly installed global command. Packaging includes both new guard modules; it still uses existing local runtime inputs and downloads nothing. Grant preparation/signing and runtime model/provider configuration are separate concerns.

## Acceptance and next implementation

**250 focused Python checks pass**, including 33 new grant/process checks; scoped Ruff passes. Synthetic production-purpose keys and inert package fixtures cover signatures, binding, expiry, source-independent renewal after both old windows expire, exact review, interrupted commits, stale-head refusal, leased launch context and manager exclusion. These are protocol fixtures, not real approvals or production signing.

Actual development-host acceptance uses the existing isolated Python runtime for a finite owned process, expiry termination and a child/grandchild tree killed by controller death. File write denial is exercised. [Sanitized evidence](qa/admission-launch-verification.json) also records the updated portable controller/bootstrap checks. No actual INARA resident or UI is started by those fixtures, and no real profile/production installation is created. Both production policies remain disabled; the original 85-subject review ledger remains pending.

The initial full bootstrap run exceeded its 120-second acceptance timeout during repeated PowerShell ancestor inspections. Direct filesystem attribute reads now perform those same link checks without constructing provider objects for every ancestor of thousands of files. Full acceptance passes after that change, with an additional real junction-ancestor refusal regression. This is a corrected acceptance bottleneck, not a general startup-latency or gaming-performance benchmark.

The next source milestone is now implemented in [managed updates](MANAGED_UPDATES.md): protected external checkpoint history, dual-policy trust rotation, reviewed update/rollback and guarded transaction recovery/cancellation. This document records the earlier format-1/2 grant flow; managed format-3 roots use the newer commands. Controller-specific provenance/notices, native managed lifecycle UX and owned bootstrap signing/delivery remain ahead of clean-machine resident/UI acceptance. Owned certificates/reviewer decisions, Android builds and physical SIM/personal WhatsApp control/duplex media remain separate gates. WhatsApp text/outgoing actions stay off; provider/toolchain/model configuration and the real-game benchmark remain deferred.
