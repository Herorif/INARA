# Reviewed recovery activation and project-path compatibility

Implemented 21 October 2026. `scripts/desktop-recovery.py` adds explicit compatibility review, preparation, activation and rollback to [encrypted profile recovery](ENCRYPTED_PROFILE_RECOVERY.md). It reads the authenticated encrypted backup directly and creates a new managed profile; a detached directory is not implicitly adopted. Only the exact registered source package and original Windows account are supported.

## Supported compatibility boundary

Project scopes include absolute paths and hashes. The adapter computes an explicit source/destination mapping from backed-up project directories, then changes only known structural fields and encrypted contexts:

- Workspace selection: rekey its workspace-root hash, preserving the selected project name.
- Project memory v1: verify owner/project/key, change the structural project field and key, and reencrypt under the new context. Note bodies, consent/retention values and revision ancestry are preserved.
- Conversations: validate the owner hash and source project hash, decode the original authenticated session context, and reencrypt with the new project scope. Request IDs, terminal results and uncertain/running request states are retained; nothing is replayed.
- CAD/image job history: rekey the owner/project namespace for terminal jobs without cross-studio references. Preserve recipes, revision IDs and relative artifact directories. Successful artifacts must match their recorded size/digest and owned relative path before activation.

Literal old paths in user notes, conversation text, recipe descriptions and other content remain unchanged. The adapter never performs a global string replacement or executes restored code, tools or jobs. CAD artifact acceptance uses a labelled fixture export, not a claim of a newly generated model or Blender execution.

Unknown document kinds, extra database tables/triggers/views/custom indexes, legacy migration markers, unmapped/foreign owners or scopes, active creative jobs, referenced creative handoffs and missing/changed exports reject before a managed profile is created. Mobile grants, call state, budgets/usage records, task queues and other record groups need separately reviewed adapters; they are not silently discarded or treated as compatible. This initial boundary does **not** make every existing advanced profile activatable.

## Review, preparation and atomic selection

Preview validates account, installation, owner, package and data before showing the destination, owner fingerprint, project mapping, record counts and review SHA-256. The review binds the encrypted backup, destination profile UUID, current installation generation/selection and adapter format. It also declares the installation format upgrade and older-control incompatibility.

Prepare requires that exact review. It creates only a new `recovery-profiles/<uuid>` directory and retains the source backup/original profile. The database is transformed in memory and reprotected with Windows account protection. The copied inventory is checked before its receipt changes from `incomplete` to `prepared`. Preparing never selects the copy. Failed/incomplete profiles remain retained and cannot launch; choose another new identifier after inspection rather than overwriting them.

Activate rechecks the reviewed generation/selection, owner, prepared receipt and file/directory hashes. A single flushed temporary-file replacement commits **installation format 2**, including the current/previous profile pointers. The original format-1 installation remains readable by the new tools until explicit activation. Older control scripts reject format 2, preventing silent fallback to original data. Do not downgrade the metadata manually. Launch with the current verified control script and the selected installed Python.

The existing resident-lifetime OS manager lock covers review, preparation, activation and rollback. A managed resident blocks switching. Runtime writes are allowed within the selected profile; the prepared snapshot hash is a pre-activation check, not a read-only live profile. Rollback validates the previous profile/owner and atomically toggles current/previous pointers, preserving both data directories. It does not merge subsequent changes or downgrade installation format.

New encrypted backups use archive format 2 to record the canonical source data root inside the encrypted manifest. This permits backing up an active recovery profile and reviewing another relocation. Archive format 1 remains supported for original slot profiles. Only the activation management receipt is excluded from active-profile backups; application data remains subject to the existing 64 MiB/4,096-entry limits. Cross-account, bare-metal and cross-package-version recovery remain unclaimed.

## Commands

Stop the resident first. Use a verified control candidate containing the new tools:

```powershell
$control = 'C:/path/to/verified-control-candidate'
$installation = 'C:/path/to/managed-installation'
$slot = '<exact registered source slot>'
$file = 'C:/path/to/private-backups/profile.inara'
$profile = [guid]::NewGuid().ToString('N')
& "$control/runtime/python/python.exe" -I -B "$control/scripts/desktop-recovery.py" preview --root $installation --slot $slot --file $file --profile $profile
# Review the owner, mapping, destination and format upgrade, then copy its review digest.
$review = '<review_sha256 returned by preview>'
& "$control/runtime/python/python.exe" -I -B "$control/scripts/desktop-recovery.py" prepare --root $installation --slot $slot --file $file --profile $profile --expected-review $review
& "$control/runtime/python/python.exe" -I -B "$control/scripts/desktop-recovery.py" activate --root $installation --slot $slot --profile $profile --expected-review $review
& "$installation/versions/$slot/runtime/python/python.exe" -I -B "$control/scripts/desktop-install.py" launch --root $installation --resident-only
# After quitting INARA, explicitly return to the previous profile.
& "$control/runtime/python/python.exe" -I -B "$control/scripts/desktop-recovery.py" rollback --root $installation --slot $slot
```

Any installation generation/selection or owner change invalidates the review. A prepared copy that changes before activation is refused. Do not use old control scripts or a direct resident entrypoint to bypass managed profile selection. No registry/startup setting, provider, phone permission, call or WhatsApp action is configured.

## Verification

**151 focused Python checks pass**, including 24 recovery-activation checks. They cover actual memory/conversation reads after rekeying, artifact-byte preservation, literal text preservation, legacy backups, successive active-profile backups, stale reviews, changed owner/payload/receipt, unsupported database objects and records, busy/incomplete profiles, interrupted preparation/commit, atomic format upgrade and retained-data rollback. Scoped Ruff passes.

Actual native acceptance passes restored project memory, conversation restoration and fixture CAD artifact export through a newly started isolated resident using the installed Python/core. The manager lease remains held, model/device workers stay at zero, shutdown is graceful and rollback preserves every original profile byte. The encrypted backup and recovery copies remain retained, and older control scripts reject the upgraded state. [Sanitized native evidence](qa/recovery-activation-verification.json).

Final unsigned control candidate: `.runtime/releases/recovery-activation-20261021-accepted`, 2,985 inventoried files. Its reviewed activation runs against the exact backed-up installed slot; it does not silently upgrade that application package. The native installation interface is now implemented in [Native Setup](NATIVE_SETUP.md). Signing, clean-machine and physical capability acceptance remain separate gates.

## Next implementation

[Native Setup](NATIVE_SETUP.md) now implements the Windows installation/launch/removal interface with review and data preservation. Next is distribution provenance, dependency/license notices and signing readiness. Keep signature/clean-machine acceptance visibly distinct from offline pilot integrity. Expand recovery adapters only with concrete typed records and scope tests; never bypass the unsupported-record refusal to make an advanced profile appear migrated.

Then complete signing/license ownership, clean-machine install/uninstall/interruption checks and signed opt-in updates. Android build/device acceptance, actual providers/Blender/image/speech/camera and physical SIM/personal WhatsApp duplex media remain separately gated. WhatsApp text/outgoing actions and real-game benchmarking retain their prior exclusions/deferrals.
